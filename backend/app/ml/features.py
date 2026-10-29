"""
Feature engineering for the trade-outcome model - turns the same inputs
the rule-based strategies see (a candle window + market regime) into a
flat numeric feature vector. Deliberately reuses app/engine/indicators.py
rather than recomputing anything independently, so "what the model sees"
and "what the strategy sees" never silently drift apart.
"""
from __future__ import annotations

import datetime as dt

from app.engine import indicators as ind

REGIME_ORDER = ["STRONG_BEARISH", "BEARISH", "NEUTRAL", "BULLISH", "STRONG_BULLISH", "HIGH_VOLATILITY_UNSAFE"]

FEATURE_NAMES = [
    "rsi", "atr_pct", "relative_volume", "momentum_pct", "ema_spread_pct",
    "regime_score", "hour_of_day", "day_of_week", "strategy_score", "risk_reward",
]


def _as_datetime(ts) -> dt.datetime:
    if isinstance(ts, dt.datetime):
        return ts
    return dt.datetime.utcfromtimestamp(ts)


def extract_features(candles: list[dict], market_regime: str, strategy_score: int,
                      risk_reward: float) -> dict | None:
    """Returns None (never a guessed/default feature vector) if any
    underlying indicator can't be computed - an incomplete feature vector
    is excluded from training/inference rather than filled in."""
    if len(candles) < 25:
        return None

    rsi = ind.rsi(candles)
    atr_pct = ind.average_true_range_pct(candles)
    rel_vol = ind.relative_volume(candles)
    momentum = ind.momentum_pct(candles)
    ema9 = ind.ema_latest(candles, 9)
    ema21 = ind.ema_latest(candles, 21)
    if None in (rsi, atr_pct, rel_vol, momentum, ema9, ema21):
        return None

    last_close = candles[-1]["close"]
    ema_spread_pct = (ema9 - ema21) / last_close * 100 if last_close else 0.0

    ist = _as_datetime(candles[-1]["timestamp"]) + dt.timedelta(hours=5, minutes=30)
    regime_score = REGIME_ORDER.index(market_regime) if market_regime in REGIME_ORDER else 2

    return {
        "rsi": round(rsi, 2), "atr_pct": round(atr_pct, 3), "relative_volume": round(rel_vol, 3),
        "momentum_pct": round(momentum, 3), "ema_spread_pct": round(ema_spread_pct, 4),
        "regime_score": regime_score, "hour_of_day": ist.hour, "day_of_week": ist.weekday(),
        "strategy_score": strategy_score, "risk_reward": round(risk_reward, 2),
    }
