"""
The automated intraday strategy - the single place that decides BUY / SELL /
WAIT / NO_TRADE for a candidate stock, and (if it decides to trade) the
entry, stop-loss, target and risk/reward for that trade.

No single indicator can trigger a trade. Every candidate is scored out of
10 across seven independent confirmations; only candidates that clear
MIN_SIGNAL_SCORE AND meet the minimum risk/reward are ever passed to the
risk engine. Everything here is deterministic and explainable: the
`reasons` list returned alongside every signal is exactly what the UI shows
the user under "Why did the application buy/sell X?".

            Score weights (max 10):
              Trend alignment with market regime     +2
              VWAP confirmation                      +2
              EMA9/EMA21 confirmation                +1
              Volume confirmation (relative volume)  +2
              Momentum confirmation                  +1
              Market regime confirmation              +1
              Risk/reward adequate                    +1
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.engine import indicators as ind

MIN_SIGNAL_SCORE = 7      # out of 10 - a trade needs at least 7/10 confirmations
MAX_SCORE = 10
ATR_STOP_MULTIPLE = 1.5
MAX_STOP_ATR_MULTIPLE = 2.5
# Must stay comfortably above MAX_STOP_ATR_MULTIPLE * (highest profile min R:R, 1.5)
# so a widened, structure-based stop can never mechanically force risk/reward
# below the minimum threshold (that would reject otherwise-good trend trades).
MAX_REWARD_ATR_MULTIPLE = 4.0
STRUCTURE_LOOKBACK = 10
MIN_RISK_REWARD_FLOOR = 1.3  # absolute floor regardless of risk profile


@dataclass
class TradeSetup:
    symbol: str
    direction: str  # BUY | SELL | WAIT | NO_TRADE
    score: int
    max_score: int
    passed: bool
    reasons: list[str]
    components: dict
    entry_price: float | None = None
    stop_loss: float | None = None
    target: float | None = None
    risk_per_share: float | None = None
    reward_per_share: float | None = None
    risk_reward: float | None = None
    rejected_reason: str | None = None


def _structure_stop(candles: list[dict], direction: str) -> float:
    window = candles[-STRUCTURE_LOOKBACK:]
    if direction == "BUY":
        return min(c["low"] for c in window)
    return max(c["high"] for c in window)


def _score_direction(symbol: str, candles: list[dict], direction: str, market_regime: str,
                      min_risk_reward: float) -> TradeSetup:
    reasons: list[str] = []
    components: dict = {}
    score = 0

    last = candles[-1]
    entry = last["close"]
    ema9 = ind.ema_latest(candles, 9)
    ema21 = ind.ema_latest(candles, 21)
    # VWAP is session-relative (resets each trading day) even when `candles`
    # itself carries prior-day bars for warm-up - only today's bars count.
    vwap = ind.vwap(ind.session_slice(candles))
    rsi_val = ind.rsi(candles)
    atr_val = ind.atr(candles)
    rel_vol = ind.relative_volume(candles)
    momentum = ind.momentum_pct(candles)

    if None in (ema9, ema21, vwap, rsi_val, atr_val, rel_vol, momentum):
        return TradeSetup(symbol, "NO_TRADE", 0, MAX_SCORE, False, [], {},
                           rejected_reason="Insufficient indicator data")

    bullish_bias = direction == "BUY"

    # 1) Trend alignment with market regime (+2)
    market_bullish = market_regime in ("BULLISH", "STRONG_BULLISH")
    market_bearish = market_regime in ("BEARISH", "STRONG_BEARISH")
    trend_ok = (bullish_bias and ema9 > ema21 and market_bullish) or \
               (not bullish_bias and ema9 < ema21 and market_bearish)
    if trend_ok:
        score += 2
        reasons.append("Stock trend matches the broader market trend")
    components["trend"] = 2 if trend_ok else 0

    # 2) VWAP confirmation (+2)
    vwap_ok = (bullish_bias and entry > vwap) or (not bullish_bias and entry < vwap)
    if vwap_ok:
        score += 2
        reasons.append("Price above VWAP" if bullish_bias else "Price below VWAP")
    components["vwap"] = 2 if vwap_ok else 0

    # 3) EMA confirmation (+1)
    ema_ok = (bullish_bias and ema9 > ema21) or (not bullish_bias and ema9 < ema21)
    if ema_ok:
        score += 1
        reasons.append("Short-term average above long-term average" if bullish_bias
                        else "Short-term average below long-term average")
    components["ema"] = 1 if ema_ok else 0

    # 4) Volume confirmation (+2)
    volume_ok = rel_vol >= 1.3
    if volume_ok:
        score += 2
        reasons.append("High trading volume compared to usual")
    components["volume"] = 2 if volume_ok else 0

    # 5) Momentum confirmation (+1)
    momentum_ok = (bullish_bias and momentum > 0.15) or (not bullish_bias and momentum < -0.15)
    if momentum_ok:
        score += 1
        reasons.append("Positive short-term momentum" if bullish_bias else "Negative short-term momentum")
    components["momentum"] = 1 if momentum_ok else 0

    # RSI sanity guard (not independently scored, but can veto - avoids chasing an extended move)
    rsi_sane = (bullish_bias and rsi_val < 75) or (not bullish_bias and rsi_val > 25)

    # 6) Market regime confirmation (+1) - separate from #1, rewards a clear (not neutral) regime
    regime_clear = market_regime not in ("NEUTRAL", "HIGH_VOLATILITY_UNSAFE")
    if regime_clear:
        score += 1
        reasons.append(f"Overall market condition is {market_regime.replace('_', ' ').title()}")
    components["market_regime"] = 1 if regime_clear else 0

    # Compute entry/stop/target to score risk-reward (#7)
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
    desired_reward_dist = risk_per_share * min_risk_reward
    reward_dist = min(desired_reward_dist, max_reward_dist)

    if bullish_bias:
        target = round(entry + reward_dist, 2)
    else:
        target = round(entry - reward_dist, 2)

    reward_per_share = round(abs(target - entry), 2)
    risk_reward = round(reward_per_share / risk_per_share, 2) if risk_per_share > 0 else 0

    rr_ok = risk_reward >= max(min_risk_reward, MIN_RISK_REWARD_FLOOR)
    if rr_ok:
        score += 1
        reasons.append(f"Risk/reward acceptable ({risk_reward:.2f}:1)")
    components["risk_reward"] = 1 if rr_ok else 0

    passed = score >= MIN_SIGNAL_SCORE and rr_ok and rsi_sane

    rejected_reason = None
    if not passed:
        bits = []
        if score < MIN_SIGNAL_SCORE:
            bits.append(f"signal score {score}/{MAX_SCORE} below minimum {MIN_SIGNAL_SCORE}")
        if not rr_ok:
            bits.append(f"risk/reward {risk_reward:.2f}:1 below minimum {min_risk_reward}:1")
        if not rsi_sane:
            bits.append("price already over-extended (RSI filter)")
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
    """Evaluate both BUY and SELL hypotheses and return the better one (if any passes)."""
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
