import time

import pytest

from app.fyers.rate_limiter import FyersRateLimiter, RateLimitWaitExceeded, CATEGORY_LIMITS, BASE_BACKOFF_SECONDS


def test_calls_within_per_second_limit_are_instant():
    limiter = FyersRateLimiter()
    limit = CATEGORY_LIMITS["data"]["per_sec"]
    start = time.time()
    for _ in range(limit):
        limiter.acquire("data", caller="test")
    assert time.time() - start < 0.5


def test_call_past_per_second_limit_waits():
    limiter = FyersRateLimiter()
    limit = CATEGORY_LIMITS["data"]["per_sec"]
    start = time.time()
    for _ in range(limit):
        limiter.acquire("data", caller="test")
    limiter.acquire("data", caller="test", max_wait=3)
    assert time.time() - start >= 0.8


def test_per_minute_limit_raises_rather_than_blocking_a_full_minute():
    limiter = FyersRateLimiter()
    limit = CATEGORY_LIMITS["data"]["per_min"]
    now = time.time()
    state = limiter._state["data"]
    state.min_window.extend([now] * limit)
    with pytest.raises(RateLimitWaitExceeded):
        limiter.acquire("data", caller="test", max_wait=0.2)


def test_per_day_limit_raises_rather_than_blocking_a_full_day():
    limiter = FyersRateLimiter()
    limit = CATEGORY_LIMITS["data"]["per_day"]
    now = time.time()
    state = limiter._state["data"]
    state.day_window.extend([now] * limit)
    with pytest.raises(RateLimitWaitExceeded):
        limiter.acquire("data", caller="test", max_wait=0.2)


def test_categories_have_independent_budgets():
    limiter = FyersRateLimiter()
    limit = CATEGORY_LIMITS["data"]["per_min"]
    now = time.time()
    limiter._state["data"].min_window.extend([now] * limit)
    with pytest.raises(RateLimitWaitExceeded):
        limiter.acquire("data", caller="test", max_wait=0.1)
    # transaction category is untouched and should still succeed instantly
    limiter.acquire("transaction", caller="test", max_wait=0.1)


def test_unknown_category_falls_back_to_transaction():
    limiter = FyersRateLimiter()
    limiter.acquire("something_unexpected", caller="test")
    assert limiter.snapshot()["transaction"]["total_calls"] == 1


def test_rate_limit_error_triggers_backoff():
    limiter = FyersRateLimiter()
    assert limiter.is_backing_off("data") is False
    limiter.record_rate_limit_error("data", "Standard plan limit of 50 requests/minute")
    assert limiter.is_backing_off("data") is True
    assert limiter.backoff_seconds_remaining("data") > 0


def test_backing_off_category_raises_immediately_on_acquire():
    limiter = FyersRateLimiter()
    limiter.record_rate_limit_error("data", "rate limited")
    with pytest.raises(RateLimitWaitExceeded):
        limiter.acquire("data", caller="test", max_wait=0.1)


def test_backoff_escalates_on_repeated_errors():
    limiter = FyersRateLimiter()
    limiter.record_rate_limit_error("data", "err1")
    first = limiter._state["data"].backoff_until
    limiter.record_rate_limit_error("data", "err2")
    second = limiter._state["data"].backoff_until
    assert second > first  # second backoff window extends further into the future


def test_record_success_resets_the_escalation_counter():
    limiter = FyersRateLimiter()
    limiter.record_rate_limit_error("data", "err1")
    limiter.record_rate_limit_error("data", "err2")
    assert limiter._state["data"].backoff_attempt == 2
    limiter.record_success("data")
    assert limiter._state["data"].backoff_attempt == 0


def test_categories_backoff_independently():
    limiter = FyersRateLimiter()
    limiter.record_rate_limit_error("data", "err")
    assert limiter.is_backing_off("data") is True
    assert limiter.is_backing_off("transaction") is False


def test_snapshot_tracks_usage_and_caller_breakdown():
    limiter = FyersRateLimiter()
    limiter.acquire("data", caller="scanner.history")
    limiter.acquire("data", caller="scanner.history")
    limiter.acquire("transaction", caller="order_manager.place_order")
    snap = limiter.snapshot()
    assert snap["data"]["per_min_used"] == 2
    assert snap["data"]["calls_by_caller"]["scanner.history"] == 2
    assert snap["transaction"]["per_min_used"] == 1
    assert snap["transaction"]["calls_by_caller"]["order_manager.place_order"] == 1


def test_never_configured_to_use_full_documented_quota():
    """Safety margin requirement: every enforced limit must be strictly
    below the officially documented FYERS number."""
    assert CATEGORY_LIMITS["data"]["per_sec"] < 5
    assert CATEGORY_LIMITS["data"]["per_min"] < 50
    assert CATEGORY_LIMITS["data"]["per_day"] < 5000
    assert CATEGORY_LIMITS["transaction"]["per_sec"] < 10
    assert CATEGORY_LIMITS["transaction"]["per_min"] < 200
    assert CATEGORY_LIMITS["transaction"]["per_day"] < 100_000
