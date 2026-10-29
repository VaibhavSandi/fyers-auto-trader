from app.engine import strategy
from tests.conftest import make_trending_candles


def test_strong_uptrend_with_volume_spike_produces_buy_signal():
    candles = make_trending_candles(1000, bars=40, drift_pct=0.12, direction=1)
    setup = strategy.evaluate("NSE:TEST-EQ", candles, "STRONG_BULLISH", min_risk_reward=1.3)
    assert setup.direction == "BUY"
    assert setup.passed is True
    assert setup.score >= strategy.MIN_SIGNAL_SCORE
    assert setup.entry_price is not None
    assert setup.stop_loss < setup.entry_price
    assert setup.target > setup.entry_price


def test_strong_downtrend_produces_sell_signal():
    candles = make_trending_candles(1000, bars=40, drift_pct=0.12, direction=-1)
    setup = strategy.evaluate("NSE:TEST-EQ", candles, "STRONG_BEARISH", min_risk_reward=1.3)
    assert setup.direction == "SELL"
    assert setup.passed is True
    assert setup.stop_loss > setup.entry_price
    assert setup.target < setup.entry_price


def test_flat_sideways_market_does_not_trade():
    candles = make_trending_candles(1000, bars=40, drift_pct=0.0, direction=1)
    setup = strategy.evaluate("NSE:TEST-EQ", candles, "NEUTRAL", min_risk_reward=1.5)
    assert setup.direction in ("WAIT", "NO_TRADE")
    assert setup.passed is False


def test_high_volatility_unsafe_regime_blocks_every_symbol():
    candles = make_trending_candles(1000, bars=40, drift_pct=0.3, direction=1)
    setup = strategy.evaluate("NSE:TEST-EQ", candles, "HIGH_VOLATILITY_UNSAFE", min_risk_reward=1.3)
    assert setup.direction == "NO_TRADE"
    assert setup.passed is False
    assert "unsafe" in setup.rejected_reason.lower()


def test_insufficient_history_results_in_no_trade():
    candles = make_trending_candles(1000, bars=10, drift_pct=0.2, direction=1)
    setup = strategy.evaluate("NSE:TEST-EQ", candles, "BULLISH", min_risk_reward=1.3)
    assert setup.passed is False
    assert setup.direction == "NO_TRADE"


def test_single_indicator_alone_cannot_pass_the_minimum_score():
    # Momentum-only move (weak trend alignment, no real volume spike) should
    # not clear MIN_SIGNAL_SCORE, proving no single confirmation can trigger a trade.
    candles = make_trending_candles(1000, bars=40, drift_pct=0.01, base_volume=20_000, direction=1)
    setup = strategy.evaluate("NSE:TEST-EQ", candles, "NEUTRAL", min_risk_reward=1.5)
    assert setup.passed is False


def test_signal_score_never_exceeds_max_score():
    candles = make_trending_candles(1000, bars=40, drift_pct=0.2, direction=1)
    setup = strategy.evaluate("NSE:TEST-EQ", candles, "STRONG_BULLISH", min_risk_reward=1.3)
    assert setup.score <= strategy.MAX_SCORE


def test_risk_reward_floor_rejects_inadequate_reward():
    candles = make_trending_candles(1000, bars=40, drift_pct=0.12, direction=1)
    # Demand an unrealistically high min risk/reward - must reject even a good trend.
    setup = strategy.evaluate("NSE:TEST-EQ", candles, "STRONG_BULLISH", min_risk_reward=10.0)
    assert setup.passed is False
