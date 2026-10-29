"""
Centralized FYERS API rate limiter and usage tracker.

Every FyersClient instance in the process shares ONE of these (via
get_rate_limiter()), so the quota is enforced in a single place no matter
how many modules end up issuing requests - dashboard refreshes, the
scanner, strategy evaluation, health checks, background reconciliation,
all funnel through the same limiter.

Official FYERS v3 Standard plan limits (fyers.in/api-docs/v3/getting-started/plans-and-limits/):
    Data APIs (quotes, history):         5 req/sec | 50 req/min  | 5,000 req/day
    Transaction/user-info APIs
    (orders, positions, funds, profile): 10 req/sec | 200 req/min | 100,000 req/day

We never consume the full documented quota - every cap below is the
official number scaled down by SAFETY_MARGIN. FYERS also blocks an account
for the rest of the day after breaching the per-minute cap 3+ times, so
this limiter's whole purpose is to make that breach structurally impossible
rather than something we hope doesn't happen.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

SAFETY_MARGIN = 0.8  # use at most 80% of the documented quota, by design

_OFFICIAL_LIMITS = {
    "data": {"per_sec": 5, "per_min": 50, "per_day": 5_000},
    "transaction": {"per_sec": 10, "per_min": 200, "per_day": 100_000},
}

CATEGORY_LIMITS = {
    cat: {k: max(1, int(v * SAFETY_MARGIN)) for k, v in limits.items()}
    for cat, limits in _OFFICIAL_LIMITS.items()
}

MAX_BACKOFF_SECONDS = 60.0
BASE_BACKOFF_SECONDS = 2.0
DEFAULT_MAX_WAIT_SECONDS = 20.0


class RateLimitWaitExceeded(Exception):
    """Raised when honoring the limit would require blocking longer than the
    caller's max_wait - the caller should skip this cycle, not block the
    whole engine thread, and the category should be reported as RATE_LIMITED."""


@dataclass
class _CategoryState:
    sec_window: deque = field(default_factory=deque)
    min_window: deque = field(default_factory=deque)
    day_window: deque = field(default_factory=deque)
    backoff_until: float = 0.0
    backoff_attempt: int = 0
    total_calls: int = 0
    last_error: str | None = None
    last_error_at: float | None = None
    calls_by_caller: dict[str, int] = field(default_factory=dict)


class FyersRateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._state: dict[str, _CategoryState] = {cat: _CategoryState() for cat in CATEGORY_LIMITS}

    @staticmethod
    def _prune(state: _CategoryState, now: float) -> None:
        while state.sec_window and now - state.sec_window[0] > 1.0:
            state.sec_window.popleft()
        while state.min_window and now - state.min_window[0] > 60.0:
            state.min_window.popleft()
        while state.day_window and now - state.day_window[0] > 86400.0:
            state.day_window.popleft()

    def _normalize(self, category: str) -> str:
        return category if category in CATEGORY_LIMITS else "transaction"

    def acquire(self, category: str, caller: str = "unknown", max_wait: float = DEFAULT_MAX_WAIT_SECONDS) -> None:
        """Blocks (sleeping in short increments) until a request in
        `category` is safe to send, then reserves the slot. Raises
        RateLimitWaitExceeded instead of blocking past max_wait - the
        caller should treat that as "skip this cycle", never as licence to
        retry in a tight loop."""
        category = self._normalize(category)
        limits = CATEGORY_LIMITS[category]
        deadline = time.time() + max_wait

        while True:
            with self._lock:
                now = time.time()
                state = self._state[category]
                self._prune(state, now)

                wait = max(0.0, state.backoff_until - now)
                if len(state.sec_window) >= limits["per_sec"]:
                    wait = max(wait, 1.0 - (now - state.sec_window[0]))
                if len(state.min_window) >= limits["per_min"]:
                    wait = max(wait, 60.0 - (now - state.min_window[0]))
                if len(state.day_window) >= limits["per_day"]:
                    wait = max(wait, 86400.0 - (now - state.day_window[0]))

                if wait <= 0:
                    state.sec_window.append(now)
                    state.min_window.append(now)
                    state.day_window.append(now)
                    state.total_calls += 1
                    state.calls_by_caller[caller] = state.calls_by_caller.get(caller, 0) + 1
                    return

            if time.time() + wait > deadline:
                raise RateLimitWaitExceeded(
                    f"'{category}' would require waiting {wait:.1f}s (> max_wait {max_wait}s) - caller: {caller}"
                )
            time.sleep(min(wait, 1.0))

    def record_rate_limit_error(self, category: str, message: str) -> None:
        """Call when FYERS itself returns a rate-limit error (HTTP 429 /
        error code -429) despite our own pacing - applies exponential
        backoff with jitter so we never immediately retry in a tight loop."""
        category = self._normalize(category)
        with self._lock:
            state = self._state[category]
            state.backoff_attempt += 1
            backoff = min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2 ** (state.backoff_attempt - 1)))
            backoff += random.uniform(0, backoff * 0.3)
            state.backoff_until = time.time() + backoff
            state.last_error = message
            state.last_error_at = time.time()
            logger.warning("FYERS rate limit hit on '%s' - backing off %.1fs: %s", category, backoff, message)

    def record_success(self, category: str) -> None:
        category = self._normalize(category)
        with self._lock:
            self._state[category].backoff_attempt = 0

    def is_backing_off(self, category: str) -> bool:
        category = self._normalize(category)
        with self._lock:
            return time.time() < self._state[category].backoff_until

    def backoff_seconds_remaining(self, category: str) -> float:
        category = self._normalize(category)
        with self._lock:
            return max(0.0, round(self._state[category].backoff_until - time.time(), 1))

    def snapshot(self) -> dict:
        """Everything the diagnostics screen needs."""
        now = time.time()
        with self._lock:
            out = {}
            for cat, state in self._state.items():
                self._prune(state, now)
                out[cat] = {
                    "per_sec_used": len(state.sec_window), "per_sec_limit": CATEGORY_LIMITS[cat]["per_sec"],
                    "per_min_used": len(state.min_window), "per_min_limit": CATEGORY_LIMITS[cat]["per_min"],
                    "per_day_used": len(state.day_window), "per_day_limit": CATEGORY_LIMITS[cat]["per_day"],
                    "total_calls": state.total_calls,
                    "backing_off": now < state.backoff_until,
                    "backoff_seconds_remaining": max(0.0, round(state.backoff_until - now, 1)),
                    "last_error": state.last_error, "last_error_at": state.last_error_at,
                    "calls_by_caller": dict(state.calls_by_caller),
                }
            return out


_singleton: FyersRateLimiter | None = None
_singleton_lock = threading.Lock()


def get_rate_limiter() -> FyersRateLimiter:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = FyersRateLimiter()
        return _singleton


def reset_rate_limiter_for_tests() -> None:
    """Test-only: gives each test a clean limiter instead of sharing global state."""
    global _singleton
    with _singleton_lock:
        _singleton = FyersRateLimiter()
