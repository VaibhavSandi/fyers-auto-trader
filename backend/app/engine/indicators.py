"""
Pure, dependency-free technical indicator calculations.

Every function takes a list of candle dicts:
    {"timestamp": int, "open": float, "high": float, "low": float,
     "close": float, "volume": float}
ordered oldest -> newest, and returns either a single float (latest value)
or a list aligned 1:1 with the input.
"""
from __future__ import annotations

import datetime as dt
import math

IST_OFFSET = dt.timedelta(hours=5, minutes=30)


def closes(candles: list[dict]) -> list[float]:
    return [c["close"] for c in candles]


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def ema_latest(candles: list[dict], period: int) -> float | None:
    vals = closes(candles)
    if len(vals) < period:
        return None
    return ema(vals, period)[-1]


def vwap(candles: list[dict]) -> float | None:
    """Session VWAP over the supplied candles (caller passes today's candles only)."""
    if not candles:
        return None
    cum_pv = 0.0
    cum_vol = 0.0
    for c in candles:
        typical = (c["high"] + c["low"] + c["close"]) / 3
        cum_pv += typical * c["volume"]
        cum_vol += c["volume"]
    if cum_vol == 0:
        return None
    return cum_pv / cum_vol


def rsi(candles: list[dict], period: int = 14) -> float | None:
    vals = closes(candles)
    if len(vals) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(vals)):
        change = vals[i] - vals[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(candles: list[dict], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    relevant = true_ranges[-period:]
    return sum(relevant) / len(relevant) if relevant else None


def relative_volume(candles: list[dict], lookback: int = 20) -> float | None:
    """Latest bar volume vs the average of the preceding `lookback` bars."""
    if len(candles) < lookback + 1:
        return None
    history = [c["volume"] for c in candles[-(lookback + 1):-1]]
    avg = sum(history) / len(history) if history else 0
    if avg == 0:
        return None
    return candles[-1]["volume"] / avg


def momentum_pct(candles: list[dict], lookback: int = 5) -> float | None:
    if len(candles) < lookback + 1:
        return None
    start = candles[-lookback - 1]["close"]
    end = candles[-1]["close"]
    if start == 0:
        return None
    return (end - start) / start * 100


def average_true_range_pct(candles: list[dict], period: int = 14) -> float | None:
    """ATR expressed as a % of the latest close - used for the volatility filter."""
    a = atr(candles, period)
    if a is None or not candles:
        return None
    last_close = candles[-1]["close"]
    if last_close == 0:
        return None
    return a / last_close * 100


def is_finite(*values) -> bool:
    return all(v is not None and not math.isnan(v) for v in values if isinstance(v, float))


def _ist_date(candle: dict) -> dt.date:
    ts = candle["timestamp"]
    as_dt = ts if isinstance(ts, dt.datetime) else dt.datetime.utcfromtimestamp(ts)
    return (as_dt + IST_OFFSET).date()


def session_slice(candles: list[dict]) -> list[dict]:
    """Given a candle list that may span multiple days (e.g. a live/backtest
    warm-up window carrying prior-day bars so EMA/RSI/ATR have enough
    history right at market open), return only the bars belonging to the
    MOST RECENT IST calendar day present - i.e. the current trading
    session. Use this before any session-relative calculation (VWAP,
    day-change%) that must reset at each day's open; rolling multi-bar
    indicators (EMA/RSI/ATR/relative volume/momentum) should keep using the
    full, unsliced list - they legitimately benefit from cross-day context."""
    if not candles:
        return []
    last_date = _ist_date(candles[-1])
    start = len(candles) - 1
    while start > 0 and _ist_date(candles[start - 1]) == last_date:
        start -= 1
    return candles[start:]
