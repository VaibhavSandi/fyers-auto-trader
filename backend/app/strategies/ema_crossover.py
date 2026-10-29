"""
EMA Crossover - pure trend-following strategy (Phase 3's "Trend following"
family: EMA/SMA crossovers). Deliberately simpler and differently-weighted
than rule_based_v1: no VWAP component, and it rewards a WIDENING EMA
spread (the trend itself accelerating) rather than momentum/RSI. This is
what makes it a genuinely separate, comparable strategy rather than a
renamed copy of the original.

Produces the same TradeSetup shape app/engine/strategy.py does, so it slots
into the backtester, position sizing, and order flow completely unchanged.
"""
from __future__ import annotations

from app.engine import indicators as ind
from app.engine.strategy import TradeSetup, _structure_stop

NAME = "ema_crossover_v1"
DESCRIPTION = "Trend-following: EMA9/EMA21 crossover, trend acceleration, and volume - no VWAP/momentum component."
FAMILY = "trend-following"

MIN_SIGNAL_SCORE = 6
MAX_SCORE = 10
ATR_STOP_MULTIPLE = 1.8
MAX_STOP_ATR_MULTIPLE = 3.0
MAX_REWARD_ATR_MULTIPLE = 5.0  # kept >> MAX_STOP_ATR_MULTIPLE * highest profile min R:R, same reasoning as strategy.py
MIN_RISK_REWARD_FLOOR = 1.3


def _score_direction(symbol: str, candles: list[dict], direction: str, market_regime: str,
                      min_risk_reward: float) -> TradeSetup:
    reasons: list[str] = []
    components: dict = {}
    score = 0

    last = candles[-1]
    entry = last["close"]
    ema9_series = ind.ema([c["close"] for c in candles], 9)
    ema21_series = ind.ema([c["close"] for c in candles], 21)
    atr_val = ind.atr(candles)
    rel_vol = ind.relative_volume(candles)

    if len(ema9_series) < 4 or len(ema21_series) < 4 or atr_val is None or rel_vol is None:
        return TradeSetup(symbol, "NO_TRADE", 0, MAX_SCORE, False, [], {},
                           rejected_reason="Insufficient indicator data")

    ema9, ema21 = ema9_series[-1], ema21_series[-1]
    bullish_bias = direction == "BUY"

    # 1) EMA crossover state (+3) - the core signal for this family.
    # A plain > / < comparison is vulnerable to float-noise in the EMA
    # recursion registering a "crossover" on a dead-flat market (two EMAs
    # that are mathematically equal can differ by ~1e-13 in float64) - a
    # small relative threshold filters that out, same approach scanner.py
    # uses for its own EMA-based trend classification.
    crossed_up = ema9 > ema21 * 1.0003
    crossed_down = ema9 < ema21 * 0.9997
    cross_ok = (bullish_bias and crossed_up) or (not bullish_bias and crossed_down)
    if cross_ok:
        score += 3
        reasons.append("Fast EMA crossed above slow EMA" if bullish_bias else "Fast EMA crossed below slow EMA")
    components["crossover"] = 3 if cross_ok else 0

    # 2) Trend acceleration - EMA spread widening over the last 3 bars (+2)
    spread_now = (ema9 - ema21) / entry
    spread_prev = (ema9_series[-4] - ema21_series[-4]) / candles[-4]["close"]
    widening = (bullish_bias and spread_now > spread_prev) or (not bullish_bias and spread_now < spread_prev)
    if widening:
        score += 2
        reasons.append("Trend accelerating (EMA spread widening)")
    components["acceleration"] = 2 if widening else 0

    # 3) Volume confirmation (+2)
    volume_ok = rel_vol >= 1.2
    if volume_ok:
        score += 2
        reasons.append("Above-average trading volume")
    components["volume"] = 2 if volume_ok else 0

    # 4) Market regime alignment (+2)
    market_bullish = market_regime in ("BULLISH", "STRONG_BULLISH")
    market_bearish = market_regime in ("BEARISH", "STRONG_BEARISH")
    regime_ok = (bullish_bias and market_bullish) or (not bullish_bias and market_bearish)
    if regime_ok:
        score += 2
        reasons.append(f"Market regime ({market_regime}) supports this direction")
    components["regime"] = 2 if regime_ok else 0

    # Entry/stop/target - same ATR+structure methodology as rule_based_v1,
    # own constants so this family's risk profile is independently tunable.
    structure_stop = _structure_stop(candles, direction)
    atr_stop_dist = atr_val * ATR_STOP_MULTIPLE
    max_stop_dist = atr_val * MAX_STOP_ATR_MULTIPLE

    if bullish_bias:
        structure_dist = max(entry - structure_stop, 0.01)
        stop_dist = min(max(atr_stop_dist, structure_dist), max_stop_dist)
        stop_loss = round(entry - stop_dist, 2)
    else:
        structure_dist = max(structure_stop - entry, 0.01)
        stop_dist = min(max(atr_stop_dist, structure_dist), max_stop_dist)
        stop_loss = round(entry + stop_dist, 2)

    risk_per_share = round(abs(entry - stop_loss), 2)
    max_reward_dist = atr_val * MAX_REWARD_ATR_MULTIPLE
    reward_dist = min(risk_per_share * min_risk_reward, max_reward_dist)
    target = round(entry + reward_dist, 2) if bullish_bias else round(entry - reward_dist, 2)

    reward_per_share = round(abs(target - entry), 2)
    risk_reward = round(reward_per_share / risk_per_share, 2) if risk_per_share > 0 else 0

    rr_ok = risk_reward >= max(min_risk_reward, MIN_RISK_REWARD_FLOOR)
    if rr_ok:
        score += 1
        reasons.append(f"Risk/reward acceptable ({risk_reward:.2f}:1)")
    components["risk_reward"] = 1 if rr_ok else 0

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

    buy_setup = _score_direction(symbol, candles, "BUY", market_regime, min_risk_reward)
    sell_setup = _score_direction(symbol, candles, "SELL", market_regime, min_risk_reward)

    if buy_setup.passed and sell_setup.passed:
        return buy_setup if buy_setup.score >= sell_setup.score else sell_setup
    if buy_setup.passed:
        return buy_setup
    if sell_setup.passed:
        return sell_setup

    better = buy_setup if buy_setup.score >= sell_setup.score else sell_setup
    better.direction = "WAIT"
    return better
