from app.engine import strategy
from app.engine import indicators as ind
from tests.conftest import make_trending_candles


def test_stop_loss_is_below_entry_for_buy_and_above_for_sell():
    buy_candles = make_trending_candles(1000, 40, 0.12, direction=1)
    sell_candles = make_trending_candles(1000, 40, 0.12, direction=-1)

    buy_setup = strategy._score_direction("X", buy_candles, "BUY", "STRONG_BULLISH", 1.3)
    sell_setup = strategy._score_direction("X", sell_candles, "SELL", "STRONG_BEARISH", 1.3)

    assert buy_setup.stop_loss < buy_setup.entry_price
    assert sell_setup.stop_loss > sell_setup.entry_price


def test_stop_distance_never_exceeds_max_atr_multiple():
    candles = make_trending_candles(1000, 40, 0.12, direction=1)
    setup = strategy._score_direction("X", candles, "BUY", "STRONG_BULLISH", 1.3)
    atr_val = ind.atr(candles)
    risk_distance = setup.entry_price - setup.stop_loss
    assert risk_distance <= atr_val * strategy.MAX_STOP_ATR_MULTIPLE + 0.01


def test_target_reward_never_exceeds_max_reward_atr_multiple():
    candles = make_trending_candles(1000, 40, 0.12, direction=1)
    setup = strategy._score_direction("X", candles, "BUY", "STRONG_BULLISH", 1.3)
    atr_val = ind.atr(candles)
    reward_distance = setup.target - setup.entry_price
    assert reward_distance <= atr_val * strategy.MAX_REWARD_ATR_MULTIPLE + 0.01


def test_computed_risk_reward_matches_distances():
    candles = make_trending_candles(1000, 40, 0.12, direction=1)
    setup = strategy._score_direction("X", candles, "BUY", "STRONG_BULLISH", 1.3)
    expected_rr = round((setup.target - setup.entry_price) / (setup.entry_price - setup.stop_loss), 2)
    assert setup.risk_reward == expected_rr
