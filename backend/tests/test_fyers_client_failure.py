import pytest

from app.fyers.client import FyersClient, FyersApiError, FyersRateLimitError
from app.fyers.rate_limiter import FyersRateLimiter


class StubModel:
    def __init__(self, response, calls):
        self._response = response
        self._calls = calls

    def quotes(self, data):
        self._calls.append(data)
        return self._response

    def funds(self):
        return self._response

    def get_profile(self):
        return self._response

    def history(self, data):
        self._calls.append(data)
        return self._response


def _make_client(response, limiter=None):
    client = FyersClient("dummy-token", rate_limiter=limiter)
    calls = []
    client._model = StubModel(response, calls)
    return client, calls


def test_error_response_raises_fyers_api_error_and_does_not_retry():
    client, calls = _make_client({"s": "error", "message": "Invalid auth token"})
    with pytest.raises(FyersApiError):
        client.get_quotes(["NSE:RELIANCE-EQ"])
    assert len(calls) == 1  # exactly one network call - no blind retry


def test_malformed_response_raises_instead_of_guessing():
    client, calls = _make_client("not-a-dict")
    with pytest.raises(FyersApiError):
        client.get_quotes(["NSE:RELIANCE-EQ"])


def test_successful_quote_response_is_parsed():
    client, _ = _make_client({
        "s": "ok",
        "d": [{"n": "NSE:RELIANCE-EQ", "v": {"lp": 1500.5, "open_price": 1490, "high_price": 1510,
                                               "low_price": 1485, "prev_close_price": 1488, "volume": 100000}}],
    })
    quotes = client.get_quotes(["NSE:RELIANCE-EQ"])
    assert quotes["NSE:RELIANCE-EQ"].ltp == 1500.5


def test_empty_symbol_list_never_calls_the_api():
    client, calls = _make_client({"s": "ok", "d": []})
    result = client.get_quotes([])
    assert result == {}
    assert calls == []


def test_rate_limit_message_is_classified_as_fyers_rate_limit_error():
    limiter = FyersRateLimiter()
    client, _ = _make_client(
        {"s": "error", "message": "You've reached the Standard plan limit of 50 requests/minute."},
        limiter=limiter,
    )
    with pytest.raises(FyersRateLimitError):
        client.get_quotes(["NSE:RELIANCE-EQ"], caller="test")


def test_rate_limit_error_triggers_limiter_backoff():
    limiter = FyersRateLimiter()
    client, _ = _make_client(
        {"s": "error", "message": "You've reached the Standard plan limit of 50 requests/minute.", "code": -429},
        limiter=limiter,
    )
    assert limiter.is_backing_off("data") is False
    with pytest.raises(FyersRateLimitError):
        client.get_quotes(["NSE:RELIANCE-EQ"], caller="test")
    assert limiter.is_backing_off("data") is True


def test_fyers_rate_limit_error_is_a_fyers_api_error_subclass():
    # callers that only catch the generic FyersApiError still catch this
    assert issubclass(FyersRateLimitError, FyersApiError)


def test_non_rate_limit_error_does_not_trigger_backoff():
    limiter = FyersRateLimiter()
    client, _ = _make_client({"s": "error", "message": "Invalid symbol"}, limiter=limiter)
    with pytest.raises(FyersApiError):
        client.get_quotes(["NSE:RELIANCE-EQ"], caller="test")
    assert limiter.is_backing_off("data") is False


def test_caller_label_is_tracked_by_the_limiter():
    limiter = FyersRateLimiter()
    client, _ = _make_client({"s": "ok", "d": []}, limiter=limiter)
    client.get_quotes(["NSE:RELIANCE-EQ"], caller="scanner.history")
    snap = limiter.snapshot()
    assert snap["data"]["calls_by_caller"]["scanner.history"] == 1


def test_history_uses_data_category_and_is_rate_limited_consistently():
    limiter = FyersRateLimiter()
    client, _ = _make_client(
        {"s": "error", "message": "Standard plan limit of 50 requests/minute", "code": -429}, limiter=limiter,
    )
    with pytest.raises(FyersRateLimitError):
        client.get_history("NSE:RELIANCE-EQ", "5", "2026-01-01", "2026-01-01", caller="scanner.history")
    assert limiter.is_backing_off("data") is True
