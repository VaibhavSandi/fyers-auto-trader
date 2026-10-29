"""
Market regime classifier.

Before looking at any individual stock, decide whether the broader market
is in a state worth trading at all. Uses NIFTY 50 and BANK NIFTY 5-minute
candles: trend (EMA9 vs EMA21), day change %, and volatility (ATR%).

Regimes: STRONG_BULLISH, BULLISH, NEUTRAL, BEARISH, STRONG_BEARISH,
HIGH_VOLATILITY_UNSAFE.

If classification is impossible (missing/insufficient data) we return
HIGH_VOLATILITY_UNSAFE - "when uncertain, do not trade" applies to the
market filter too.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.engine import indicators as ind

VOLATILITY_UNSAFE_ATR_PCT = 1.2  # ATR as % of price on 5-min bars; above this, conditions are too choppy
STRONG_MOVE_PCT = 0.8
MOVE_PCT = 0.3


@dataclass
class RegimeResult:
    regime: str
    nifty_change_pct: float | None
    banknifty_change_pct: float | None
    volatility_pct: float | None
    tradeable: bool
    reason: str


def _day_change_pct(candles: list[dict]) -> float | None:
    if not candles:
        return None
    first_open = candles[0]["open"]
    last_close = candles[-1]["close"]
    if not first_open:
        return None
    return (last_close - first_open) / first_open * 100


def _trend_label(candles: list[dict]) -> str:
    ema9 = ind.ema_latest(candles, 9)
    ema21 = ind.ema_latest(candles, 21)
    if ema9 is None or ema21 is None:
        return "unknown"
    return "up" if ema9 > ema21 else "down"


def classify_market_regime(nifty_candles: list[dict], banknifty_candles: list[dict]) -> RegimeResult:
    if len(nifty_candles) < 25 or len(banknifty_candles) < 25:
        return RegimeResult(
            regime="HIGH_VOLATILITY_UNSAFE",
            nifty_change_pct=None, banknifty_change_pct=None, volatility_pct=None,
            tradeable=False,
            reason="Not enough index data yet to classify the market safely.",
        )

    nifty_change = _day_change_pct(nifty_candles)
    bn_change = _day_change_pct(banknifty_candles)
    nifty_vol = ind.average_true_range_pct(nifty_candles)
    bn_vol = ind.average_true_range_pct(banknifty_candles)
    volatility_pct = max([v for v in (nifty_vol, bn_vol) if v is not None], default=None)

    if volatility_pct is None or nifty_change is None or bn_change is None:
        return RegimeResult(
            regime="HIGH_VOLATILITY_UNSAFE", nifty_change_pct=nifty_change,
            banknifty_change_pct=bn_change, volatility_pct=volatility_pct,
            tradeable=False, reason="Index data incomplete.",
        )

    if volatility_pct >= VOLATILITY_UNSAFE_ATR_PCT:
        return RegimeResult(
            regime="HIGH_VOLATILITY_UNSAFE", nifty_change_pct=nifty_change,
            banknifty_change_pct=bn_change, volatility_pct=volatility_pct,
            tradeable=False,
            reason=f"Market is too choppy right now (volatility {volatility_pct:.2f}% > {VOLATILITY_UNSAFE_ATR_PCT}% threshold).",
        )

    nifty_trend = _trend_label(nifty_candles)
    bn_trend = _trend_label(banknifty_candles)
    avg_change = (nifty_change + bn_change) / 2
    aligned_up = nifty_trend == "up" and bn_trend == "up"
    aligned_down = nifty_trend == "down" and bn_trend == "down"

    if aligned_up and avg_change >= STRONG_MOVE_PCT:
        regime = "STRONG_BULLISH"
    elif aligned_up and avg_change >= MOVE_PCT:
        regime = "BULLISH"
    elif aligned_down and avg_change <= -STRONG_MOVE_PCT:
        regime = "STRONG_BEARISH"
    elif aligned_down and avg_change <= -MOVE_PCT:
        regime = "BEARISH"
    else:
        regime = "NEUTRAL"

    tradeable = regime != "HIGH_VOLATILITY_UNSAFE"
    reason = f"NIFTY {nifty_change:+.2f}%, BANKNIFTY {bn_change:+.2f}%, volatility {volatility_pct:.2f}%."

    return RegimeResult(
        regime=regime, nifty_change_pct=nifty_change, banknifty_change_pct=bn_change,
        volatility_pct=volatility_pct, tradeable=tradeable, reason=reason,
    )
