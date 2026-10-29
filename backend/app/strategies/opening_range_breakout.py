"""
Opening Range Breakout (ORB) - price-action/breakout family (Phase 3's
"Opening-range breakout" and "Breakout and retest" categories). Defines
the first OPENING_RANGE_BARS candles of the trading day as a range, then
looks for a volume-confirmed break beyond it. This is a third,
structurally different signal (no EMA/VWAP at all) from the other two
registered strategies - entry logic, not just risk constants, differs.

Produces the same TradeSetup shape app/engine/strategy.py does.

Note: candle "timestamp" values vary by caller - live trading_engine.py
passes raw FYERS epoch ints, the backtester passes datetime objects (read
back from the local store). _candle_date() below normalizes either.
"""
from __future__ import annotations

import datetime as dt

from app.engine import indicators as ind
from app.engine.strategy import TradeSetup

NAME = "opening_range_breakout_v1"
DESCRIPTION = "Price-action breakout: trades a volume-confirmed break of the first 15 minutes' high/low range."
FAMILY = "breakout"

OPENING_RANGE_BARS = 3  # 3 x 5-min bars = the first 15 minutes of the session
MIN_SIGNAL_SCORE = 6
MAX_SCORE = 10
MIN_BREAKOUT_MARGIN_PCT = 0.05  # price must clear the range by at least this % - not just touch it
ATR_STOP_MULTIPLE = 1.2
MAX_STOP_ATR_MULTIPLE = 2.5
MAX_REWARD_ATR_MULTIPLE = 4.0
MIN_RISK_REWARD_FLOOR = 1.3


def _candle_date(ts) -> dt.date:
    if isinstance(ts, dt.datetime):
        return ts.date()
    return dt.datetime.utcfromtimestamp(ts).date()


def _todays_opening_range(candles: list[dict]) -> tuple[float, float] | None:
    today = _candle_date(candles[-1]["timestamp"])
    todays_bars = [c for c in candles if _candle_date(c["timestamp"]) == today]
    if len(todays_bars) < OPENING_RANGE_BARS + 1:
        return None  # not past the opening range yet, or no data for today
    opening_bars = todays_bars[:OPENING_RANGE_BARS]
    return min(b["low"] for b in opening_bars), max(b["high"] for b in opening_bars)


def _score_direction(symbol: str, candles: list[dict], direction: str, market_regime: str,
                      min_risk_reward: float, range_low: float, range_high: float) -> TradeSetup:
    reasons: list[str] = []
    components: dict = {}
    score = 0

    last = candles[-1]
    entry = last["close"]
    atr_val = ind.atr(candles)
    rel_vol = ind.relative_volume(candles)
    if atr_val is None or rel_vol is None:
        return TradeSetup(symbol, "NO_TRADE", 0, MAX_SCORE, False, [], {},
                           rejected_reason="Insufficient indicator data")

    bullish_bias = direction == "BUY"
    range_width = max(range_high - range_low, 0.01)

    # 1) Confirmed breakout beyond the opening range (+3) - a touch doesn't count
    if bullish_bias:
        margin_pct = (entry - range_high) / range_high * 100
        breakout_ok = margin_pct >= MIN_BREAKOUT_MARGIN_PCT
    else:
        margin_pct = (range_low - entry) / range_low * 100
        breakout_ok = margin_pct >= MIN_BREAKOUT_MARGIN_PCT
    if breakout_ok:
        score += 3
        reasons.append("Price broke the opening range with a clear margin" if bullish_bias
                        else "Price broke below the opening range with a clear margin")
    components["breakout"] = 3 if breakout_ok else 0

    # 2) Volume surge on the breakout (+3) - breakouts without volume are unreliable
    volume_ok = rel_vol >= 1.5
    if volume_ok:
        score += 3
        reasons.append("Strong volume surge confirms the breakout")
    components["volume"] = 3 if volume_ok else 0

    # 3) Market regime alignment (+2)
    market_bullish = market_regime in ("BULLISH", "STRONG_BULLISH")
    market_bearish = market_regime in ("BEARISH", "STRONG_BEARISH")
    regime_ok = (bullish_bias and market_bullish) or (not bullish_bias and market_bearish)
    if regime_ok:
        score += 2
        reasons.append(f"Market regime ({market_regime}) supports this direction")
    components["regime"] = 2 if regime_ok else 0

    # Entry/stop/target - stop anchored to the OPPOSITE side of the opening
    # range (the structural invalidation level for a breakout trade),
    # bounded by ATR so a very wide range can't create an oversized stop.
    atr_stop_dist = atr_val * ATR_STOP_MULTIPLE
    max_stop_dist = atr_val * MAX_STOP_ATR_MULTIPLE

    if bullish_bias:
        structure_dist = max(entry - range_low, 0.01)
        stop_dist = min(max(atr_stop_dist, min(structure_dist, range_width)), max_stop_dist)
        stop_loss = round(entry - stop_dist, 2)
    else:
        structure_dist = max(range_high - entry, 0.01)
        stop_dist = min(max(atr_stop_dist, min(structure_dist, range_width)), max_stop_dist)
        stop_loss = round(entry + stop_dist, 2)

    risk_per_share = round(abs(entry - stop_loss), 2)
    max_reward_dist = atr_val * MAX_REWARD_ATR_MULTIPLE
    reward_dist = min(risk_per_share * min_risk_reward, max_reward_dist)
    target = round(entry + reward_dist, 2) if bullish_bias else round(entry - reward_dist, 2)

    reward_per_share = round(abs(target - entry), 2)
    risk_reward = round(reward_per_share / risk_per_share, 2) if risk_per_share > 0 else 0

    rr_ok = risk_reward >= max(min_risk_reward, MIN_RISK_REWARD_FLOOR)
    if rr_ok:
        score += 2
        reasons.append(f"Risk/reward acceptable ({risk_reward:.2f}:1)")
    components["risk_reward"] = 2 if rr_ok else 0

    passed = score >= MIN_SIGNAL_SCORE and rr_ok

    rejected_reason = None
    if not passed:
        bits = []
        if score < MIN_SIGNAL_SCORE:
            bits.append(f"signal score {score}/{MAX_SCORE} below minimum {MIN_SIGNAL_SCORE}")
        if not rr_ok:
            bits.append(f"risk/reward {risk_reward:.2f}:1 below minimum {min_risk_reward}:1")
        rejected_reason = "; ".join(bits)

    return TradeSetup(
        symbol=symbol, direction=direction if passed else "WAIT", score=score, max_score=MAX_SCORE,
        passed=passed, reasons=reasons, components=components,
        entry_price=entry if passed else None,
        stop_loss=stop_loss if passed else None,
        target=target if passed else None,
        risk_per_share=risk_per_share if passed else None,
        reward_per_share=reward_per_share if passed else None,
        risk_reward=risk_reward if passed else None,
        rejected_reason=rejected_reason,
    )


def evaluate(symbol: str, candles: list[dict], market_regime: str, min_risk_reward: float) -> TradeSetup:
    if market_regime == "HIGH_VOLATILITY_UNSAFE":
        return TradeSetup(symbol, "NO_TRADE", 0, MAX_SCORE, False, [], {},
                           rejected_reason="Market regime unsafe - no trade today for this stock")
    if len(candles) < 25:
        return TradeSetup(symbol, "NO_TRADE", 0, MAX_SCORE, False, [], {},
                           rejected_reason="Not enough intraday data")

    opening_range = _todays_opening_range(candles)
    if opening_range is None:
        return TradeSetup(symbol, "NO_TRADE", 0, MAX_SCORE, False, [], {},
                           rejected_reason="Still inside the opening range - no breakout to evaluate yet")
    range_low, range_high = opening_range

    buy_setup = _score_direction(symbol, candles, "BUY", market_regime, min_risk_reward, range_low, range_high)
    sell_setup = _score_direction(symbol, candles, "SELL", market_regime, min_risk_reward, range_low, range_high)

    if buy_setup.passed and sell_setup.passed:
        return buy_setup if buy_setup.score >= sell_setup.score else sell_setup
    if buy_setup.passed:
        return buy_setup
    if sell_setup.passed:
        return sell_setup

    better = buy_setup if buy_setup.score >= sell_setup.score else sell_setup
    better.direction = "WAIT"
    return better
