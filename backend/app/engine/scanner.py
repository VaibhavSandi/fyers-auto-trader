"""
The stock scanner: shrinks the curated universe down to today's actually
tradeable, liquid, suitably-volatile candidates - BEFORE any strategy
scoring happens. A stock that fails here never reaches the strategy engine,
no matter how good a technical pattern it shows ("do not trade illiquid
stocks simply because they generate a technical signal").
"""
from __future__ import annotations

from dataclasses import dataclass

from app.engine import indicators as ind

MIN_PRICE = 40.0
MAX_PRICE = 10000.0
MIN_AVG_BAR_VOLUME = 20_000       # average 5-min bar volume
MIN_RELATIVE_VOLUME = 1.1         # today's latest bar vs its own recent average
MIN_ATR_PCT = 0.08                # too flat -> no real opportunity
MAX_ATR_PCT = 1.5                 # too wild -> unpredictable / unsafe for small capital
MAX_SPREAD_PCT = 0.15             # bid/ask spread as % of price


@dataclass
class ScanResult:
    symbol: str
    eligible: bool
    reasons_excluded: list[str]
    liquidity_score: float
    volatility_pct: float | None
    relative_volume: float | None
    trend: str  # "up" | "down" | "sideways" | "unknown"


def evaluate_symbol(symbol: str, candles: list[dict], quote: dict | None) -> ScanResult:
    reasons: list[str] = []

    if len(candles) < 25:
        return ScanResult(symbol, False, ["Not enough intraday price history yet"], 0.0, None, None, "unknown")

    last_close = candles[-1]["close"]
    if last_close < MIN_PRICE or last_close > MAX_PRICE:
        reasons.append(f"Price ₹{last_close:.2f} outside tradeable band")

    avg_vol = sum(c["volume"] for c in candles[-20:]) / min(20, len(candles))
    if avg_vol < MIN_AVG_BAR_VOLUME:
        reasons.append("Average trading volume too low (illiquid)")

    rel_vol = ind.relative_volume(candles)
    if rel_vol is not None and rel_vol < MIN_RELATIVE_VOLUME:
        reasons.append("No unusual trading interest today (low relative volume)")

    atr_pct = ind.average_true_range_pct(candles)
    if atr_pct is None:
        reasons.append("Could not compute volatility")
    elif atr_pct < MIN_ATR_PCT:
        reasons.append("Price barely moving (too flat to trade safely)")
    elif atr_pct > MAX_ATR_PCT:
        reasons.append("Price swinging too wildly (too risky for position sizing)")

    if quote and quote.get("bid") and quote.get("ask") and quote["bid"] > 0:
        spread_pct = (quote["ask"] - quote["bid"]) / quote["bid"] * 100
        if spread_pct > MAX_SPREAD_PCT:
            reasons.append("Bid/ask spread too wide")

    ema9 = ind.ema_latest(candles, 9)
    ema21 = ind.ema_latest(candles, 21)
    if ema9 is not None and ema21 is not None:
        if ema9 > ema21 * 1.0005:
            trend = "up"
        elif ema9 < ema21 * 0.9995:
            trend = "down"
        else:
            trend = "sideways"
    else:
        trend = "unknown"

    liquidity_score = (avg_vol / MIN_AVG_BAR_VOLUME) if avg_vol else 0.0

    return ScanResult(
        symbol=symbol,
        eligible=len(reasons) == 0,
        reasons_excluded=reasons,
        liquidity_score=round(liquidity_score, 2),
        volatility_pct=round(atr_pct, 3) if atr_pct is not None else None,
        relative_volume=round(rel_vol, 2) if rel_vol is not None else None,
        trend=trend,
    )


def rank_candidates(results: list[ScanResult]) -> list[ScanResult]:
    eligible = [r for r in results if r.eligible]
    eligible.sort(
        key=lambda r: ((r.relative_volume or 0) * (r.liquidity_score or 0)),
        reverse=True,
    )
    return eligible
