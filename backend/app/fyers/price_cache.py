"""
Shared, thread-safe live-price cache.

The WebSocket feed (websocket_feed.py) writes into this on every tick.
The dashboard, scanner, strategy engine, and position/risk monitoring all
READ from here instead of each independently calling the FYERS quotes
REST API for the same symbol - one live subscription, one cache, many
readers. If live mode falls back to a throttled REST refresh (because the
socket is down), that fallback writes into this same cache too, so every
consumer keeps using one source of truth either way.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class PriceTick:
    symbol: str
    ltp: float
    bid: float = 0.0
    ask: float = 0.0
    volume: float = 0.0
    exchange_timestamp: float | None = None  # epoch seconds, from FYERS' own tick if provided
    received_at: float = 0.0  # local epoch seconds when this app processed it


class PriceCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._ticks: dict[str, PriceTick] = {}

    def update(self, symbol: str, *, ltp: float, bid: float = 0.0, ask: float = 0.0,
               volume: float = 0.0, exchange_timestamp: float | None = None) -> None:
        if ltp is None or ltp <= 0:
            return
        with self._lock:
            self._ticks[symbol] = PriceTick(
                symbol=symbol, ltp=float(ltp), bid=float(bid or 0), ask=float(ask or 0),
                volume=float(volume or 0), exchange_timestamp=exchange_timestamp, received_at=time.time(),
            )

    def get(self, symbol: str) -> PriceTick | None:
        with self._lock:
            return self._ticks.get(symbol)

    def age_seconds(self, symbol: str) -> float | None:
        tick = self.get(symbol)
        if tick is None:
            return None
        return time.time() - tick.received_at

    def is_stale(self, symbol: str, max_age_seconds: float) -> bool:
        age = self.age_seconds(symbol)
        return age is None or age > max_age_seconds

    def snapshot_ages(self) -> dict:
        """For the diagnostics screen: how many symbols cached, oldest/newest tick age."""
        with self._lock:
            now = time.time()
            ages = [now - t.received_at for t in self._ticks.values()]
        if not ages:
            return {"symbol_count": 0, "oldest_age_seconds": None, "newest_age_seconds": None}
        return {
            "symbol_count": len(ages),
            "oldest_age_seconds": round(max(ages), 1),
            "newest_age_seconds": round(min(ages), 1),
        }

    def all_symbols(self) -> list[str]:
        with self._lock:
            return list(self._ticks.keys())

    def clear(self) -> None:
        with self._lock:
            self._ticks.clear()


_singleton: PriceCache | None = None
_singleton_lock = threading.Lock()


def get_price_cache() -> PriceCache:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = PriceCache()
        return _singleton


def reset_price_cache_for_tests() -> None:
    """Test-only: gives each test a clean cache instead of sharing global state."""
    global _singleton
    with _singleton_lock:
        _singleton = PriceCache()
