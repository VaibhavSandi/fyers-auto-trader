"""
Live tick feed from FYERS' market-data WebSocket - the replacement for
continuous REST quote polling (requirement: one reusable connection,
subscribe once, no duplicate subscriptions, process ticks efficiently).

Every tick is written into the shared PriceCache (price_cache.py), which is
what the dashboard, scanner, strategy engine, and position monitoring all
read from - none of them call the quotes REST endpoint anymore while this
feed is connected and fresh.

FYERS Standard plan caps a data-socket subscription at 100 symbols (shared
across all your connections to that socket, not per connection) - this
class enforces that cap rather than silently exceeding it.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from app.fyers.price_cache import PriceCache, get_price_cache

logger = logging.getLogger(__name__)

STALE_AFTER_SECONDS = 20
MAX_STANDARD_SYMBOLS = 100

STATUS_CONNECTED = "CONNECTED"
STATUS_STALE_DATA = "STALE_DATA"
STATUS_DISCONNECTED = "DISCONNECTED"


@dataclass
class LiveFeed:
    access_token: str
    client_id: str
    price_cache: PriceCache = field(default_factory=get_price_cache)
    _socket: object = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _subscribed: set[str] = field(default_factory=set)
    _last_tick_at: float = field(default_factory=time.time)
    _connected_since: float | None = None
    connected: bool = False
    started: bool = False

    # ---- FYERS websocket callbacks -----------------------------------------

    def _on_message(self, message: dict) -> None:
        symbol = message.get("symbol")
        ltp = message.get("ltp")
        if not symbol or ltp is None:
            return
        with self._lock:
            self._last_tick_at = time.time()
        self.price_cache.update(
            symbol, ltp=ltp, bid=message.get("bid_price") or 0, ask=message.get("ask_price") or 0,
            volume=message.get("vol_traded_today") or 0,
            exchange_timestamp=message.get("last_traded_time"),
        )

    def _on_connect(self) -> None:
        with self._lock:
            self.connected = True
            self._connected_since = time.time()
            self._last_tick_at = time.time()
            to_subscribe = list(self._subscribed)
        logger.info("FYERS websocket connected (%d symbols to (re)subscribe)", len(to_subscribe))
        if to_subscribe and self._socket is not None:
            self._socket.subscribe(symbols=to_subscribe, data_type="SymbolUpdate")

    def _on_close(self, *_args) -> None:
        with self._lock:
            self.connected = False
        logger.warning("FYERS websocket closed")

    def _on_error(self, message) -> None:
        """A per-symbol subscription error (e.g. a delisted/renamed symbol)
        must NOT be treated as the whole connection going down - the socket
        itself, and every other subscribed symbol, can still be fine. Only a
        genuine connection-level error marks the feed disconnected."""
        if isinstance(message, dict) and message.get("type") == "sub":
            invalid = message.get("invalid_symbols") or []
            logger.warning("FYERS rejected subscription for invalid symbol(s) %s: %s", invalid, message.get("message"))
            with self._lock:
                self._subscribed.difference_update(invalid)
            return

        with self._lock:
            self.connected = False
        logger.error("FYERS websocket error: %s", message)

    # ---- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        if self.started:
            return
        from fyers_apiv3.FyersWebsocket import data_ws

        token = f"{self.client_id}:{self.access_token}"
        self._socket = data_ws.FyersDataSocket(
            access_token=token,
            log_path="",
            litemode=False,
            write_to_file=False,
            reconnect=True,
            on_connect=self._on_connect,
            on_close=self._on_close,
            on_error=self._on_error,
            on_message=self._on_message,
        )
        thread = threading.Thread(target=self._socket.connect, daemon=True)
        thread.start()
        self.started = True

    def subscribe(self, symbols: list[str]) -> None:
        """Idempotent - already-subscribed symbols are skipped, and the
        Standard-plan 100-symbol cap is enforced rather than silently
        exceeded (extra symbols beyond the cap are logged and dropped)."""
        with self._lock:
            new_symbols = [s for s in symbols if s not in self._subscribed]
            if not new_symbols:
                return
            room = MAX_STANDARD_SYMBOLS - len(self._subscribed)
            if room <= 0:
                logger.warning(
                    "Dropping %d symbol subscription(s) - already at the %d-symbol WebSocket cap",
                    len(new_symbols), MAX_STANDARD_SYMBOLS,
                )
                return
            if len(new_symbols) > room:
                logger.warning(
                    "Only subscribing %d of %d requested symbols - WebSocket cap is %d",
                    room, len(new_symbols), MAX_STANDARD_SYMBOLS,
                )
                new_symbols = new_symbols[:room]
            self._subscribed.update(new_symbols)
            is_connected = self.connected

        if is_connected and self._socket is not None:
            self._socket.subscribe(symbols=new_symbols, data_type="SymbolUpdate")

    def subscribed_count(self) -> int:
        with self._lock:
            return len(self._subscribed)

    def subscribed_symbols(self) -> list[str]:
        with self._lock:
            return list(self._subscribed)

    # ---- reads ---------------------------------------------------------------

    def get_ltp(self, symbol: str) -> float | None:
        tick = self.price_cache.get(symbol)
        return tick.ltp if tick else None

    def is_stale(self) -> bool:
        """Overall feed staleness - no tick for ANY symbol in a while usually
        means the connection itself has gone quiet, not just one symbol."""
        with self._lock:
            return (time.time() - self._last_tick_at) > STALE_AFTER_SECONDS

    def status(self) -> str:
        if not self.connected:
            return STATUS_DISCONNECTED
        if self.is_stale():
            return STATUS_STALE_DATA
        return STATUS_CONNECTED

    def connected_seconds(self) -> float | None:
        with self._lock:
            if self._connected_since is None:
                return None
            return time.time() - self._connected_since

    def stop(self) -> None:
        with self._lock:
            self.connected = False
            self.started = False
        try:
            if self._socket:
                self._socket.close_connection()
        except Exception:
            pass
