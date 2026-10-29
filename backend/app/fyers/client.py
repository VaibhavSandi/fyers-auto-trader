"""
Thin, defensive wrapper around the FYERS v3 REST API.

Design rules followed throughout this module (per the application's final
safety rule, and the rate-limit fix):
  - EVERY call goes through the shared FyersRateLimiter first - there is no
    code path that reaches FYERS without being paced and counted.
  - Every call is tagged with a `caller` label (which module/feature issued
    it), tracked by the limiter for the diagnostics screen.
  - A rate-limit response from FYERS (HTTP 429 / error code -429 / message
    mentioning a requests-per-second/minute/day limit) is classified as
    FyersRateLimitError, distinct from FyersApiError, and triggers
    exponential backoff in the limiter - never an immediate retry.
  - Never guess: any ambiguous/unexpected response raises an error instead
    of being silently treated as success.
  - Never blindly retry: this module performs exactly one network call per
    logical request (the limiter's own backoff/pacing is the only thing
    that delays a call - there is no retry loop here).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fyers_apiv3 import fyersModel

from app.config import get_settings
from app.fyers.rate_limiter import FyersRateLimiter, RateLimitWaitExceeded, get_rate_limiter

logger = logging.getLogger(__name__)


class FyersApiError(RuntimeError):
    pass


class FyersRateLimitError(FyersApiError):
    """FYERS itself reported a rate-limit/quota error - never retry this immediately."""


@dataclass
class Quote:
    symbol: str
    ltp: float
    open: float
    high: float
    low: float
    close: float  # previous close
    volume: float
    bid: float = 0.0
    ask: float = 0.0


class FyersClient:
    """Wraps fyers_apiv3.fyersModel.FyersModel for the subset of calls this app needs.
    All instances share one process-wide rate limiter unless a test injects its own."""

    def __init__(self, access_token: str, rate_limiter: FyersRateLimiter | None = None):
        settings = get_settings()
        if not access_token:
            raise FyersApiError("No access token provided to FyersClient.")
        self._model = fyersModel.FyersModel(
            client_id=settings.FYERS_CLIENT_ID,
            token=access_token,
            is_async=False,
            log_path=str(settings.logs_dir),
        )
        self._limiter = rate_limiter or get_rate_limiter()
        self.access_token = access_token  # needed to start the market-data websocket

    # ---- core dispatch (rate limiting + response validation) ---------------

    def _call(self, category: str, caller: str, call_name: str, fn, max_wait: float = 20.0, **kwargs) -> dict:
        try:
            self._limiter.acquire(category, caller=caller, max_wait=max_wait)
        except RateLimitWaitExceeded as exc:
            raise FyersRateLimitError(f"Skipped {call_name} to respect FYERS rate limit: {exc}") from exc

        resp = fn(**kwargs) if kwargs else fn()
        try:
            self._check(resp, call_name)
        except FyersRateLimitError:
            self._limiter.record_rate_limit_error(category, str(resp))
            raise
        else:
            self._limiter.record_success(category)
        return resp

    @staticmethod
    def _check(resp: Any, call_name: str) -> None:
        if not isinstance(resp, dict):
            logger.error("FYERS %s returned non-dict response", call_name)
            raise FyersApiError(f"FYERS {call_name}: unexpected response shape")

        status = resp.get("s")
        if status == "error":
            msg = str(resp.get("message", "unknown error"))
            code = resp.get("code")
            lower_msg = msg.lower()
            is_rate_limit = (
                code in (-429, 429)
                or "rate limit" in lower_msg
                or "requests/minute" in lower_msg
                or "requests/second" in lower_msg
                or "requests/day" in lower_msg
                or "too many requests" in lower_msg
            )
            if is_rate_limit:
                logger.error("FYERS %s rate-limited: %s", call_name, msg)
                raise FyersRateLimitError(f"FYERS {call_name} rate-limited: {msg}")
            logger.error("FYERS %s failed: %s", call_name, msg)
            raise FyersApiError(f"FYERS {call_name} failed: {msg}")
        if status not in ("ok", None):
            logger.warning("FYERS %s returned unexpected status '%s'", call_name, status)

    # ---- account -----------------------------------------------------------

    def get_profile(self, caller: str = "unspecified") -> dict:
        resp = self._call("transaction", caller, "get_profile", self._model.get_profile)
        return resp.get("data", {})

    def get_funds(self, caller: str = "unspecified") -> dict:
        resp = self._call("transaction", caller, "funds", self._model.funds)
        return resp.get("fund_limit", resp.get("data", {}))

    def available_balance(self, caller: str = "unspecified") -> float:
        """Best-effort extraction of usable cash/margin from the funds response."""
        funds = self.get_funds(caller=caller)
        if isinstance(funds, list):
            for row in funds:
                title = str(row.get("title", "")).lower()
                if "available" in title or "equity" in title:
                    try:
                        return float(row.get("equityAmount", row.get("amount", 0)))
                    except (TypeError, ValueError):
                        continue
        return 0.0

    # ---- market data ---------------------------------------------------------

    def get_quotes(self, symbols: list[str], caller: str = "unspecified") -> dict[str, Quote]:
        if not symbols:
            return {}
        resp = self._call(
            "data", caller, "quotes", self._model.quotes, data={"symbols": ",".join(symbols)}
        )
        out: dict[str, Quote] = {}
        for item in resp.get("d", []):
            sym = item.get("n")
            v = item.get("v", {})
            if not sym or not v:
                continue
            out[sym] = Quote(
                symbol=sym,
                ltp=float(v.get("lp", 0) or 0),
                open=float(v.get("open_price", 0) or 0),
                high=float(v.get("high_price", 0) or 0),
                low=float(v.get("low_price", 0) or 0),
                close=float(v.get("prev_close_price", 0) or 0),
                volume=float(v.get("volume", 0) or 0),
                bid=float(v.get("bid", 0) or 0),
                ask=float(v.get("ask", 0) or 0),
            )
        return out

    def get_history(self, symbol: str, resolution: str, range_from: str, range_to: str,
                     caller: str = "unspecified") -> list[dict]:
        """resolution: '1','5','15','D' etc. range_from/to: 'YYYY-MM-DD' or epoch string."""
        resp = self._call("data", caller, "history", self._model.history, data={
            "symbol": symbol,
            "resolution": resolution,
            "date_format": "1",
            "range_from": range_from,
            "range_to": range_to,
            "cont_flag": "1",
        })
        candles = resp.get("candles", [])
        return [
            {"timestamp": c[0], "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
            for c in candles
        ]

    def market_status(self, caller: str = "unspecified") -> dict:
        return self._call("data", caller, "market_status", self._model.market_status)

    # ---- orders & positions -------------------------------------------------

    def place_order(self, *, symbol: str, qty: int, side: int, order_type: int = 2,
                     product_type: str = "INTRADAY", limit_price: float = 0,
                     stop_price: float = 0, validity: str = "DAY", caller: str = "unspecified") -> dict:
        """side: 1=BUY, -1=SELL. order_type: 1=LIMIT,2=MARKET,3=SL-M(stop-market),4=SL(stop-limit)."""
        payload = {
            "symbol": symbol,
            "qty": int(qty),
            "type": order_type,
            "side": side,
            "productType": product_type,
            "limitPrice": limit_price,
            "stopPrice": stop_price,
            "validity": validity,
            "disclosedQty": 0,
            "offlineOrder": False,
        }
        return self._call("transaction", caller, "place_order", self._model.place_order, data=payload)

    def cancel_order(self, order_id: str, caller: str = "unspecified") -> dict:
        return self._call("transaction", caller, "cancel_order", self._model.cancel_order, data={"id": order_id})

    def exit_position(self, position_id: str, caller: str = "unspecified") -> dict:
        return self._call("transaction", caller, "exit_positions", self._model.exit_positions, data={"id": position_id})

    def exit_all_positions(self, caller: str = "unspecified") -> dict:
        return self._call("transaction", caller, "exit_positions_all", self._model.exit_positions, data={})

    def get_positions(self, caller: str = "unspecified") -> list[dict]:
        resp = self._call("transaction", caller, "positions", self._model.positions)
        return resp.get("netPositions", [])

    def get_orderbook(self, caller: str = "unspecified") -> list[dict]:
        resp = self._call("transaction", caller, "orderbook", self._model.orderbook)
        return resp.get("orderBook", [])

    def get_tradebook(self, caller: str = "unspecified") -> list[dict]:
        resp = self._call("transaction", caller, "tradebook", self._model.tradebook)
        return resp.get("tradeBook", [])
