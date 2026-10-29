import datetime as dt

import pytest

from app.strategies import ema_crossover, opening_range_breakout
from app.strategies.registry import STRATEGIES, get_strategy, list_strategies, DEFAULT_STRATEGY


def _trending_candles(bars: int, start_price: float, drift_pct: float, direction: int,
                       base_volume: float = 50_000, start_date: dt.date | None = None) -> list[dict]:
    """Same pullback-noise pattern proven in test_strategy.py, with the
    volume spike on the FINAL bar - needed here because these tests call
    evaluate() once on the whole series (the final bar is 'now')."""
    start_date = start_date or dt.date.today()
    candles = []
    price = start_price
    ts = dt.datetime.combine(start_date, dt.time(3, 45))  # 09:15 IST
    for i in range(bars):
        open_p = price
        bar_direction = -0.9 if (i % 3 == 2) else 1.0
        price = price * (1 + direction * bar_direction * drift_pct / 100)
        high = max(open_p, price) * 1.001
        low = min(open_p, price) * 0.999
        volume = base_volume * (1.5 if i == bars - 1 else 1.0)
        candles.append({"timestamp": ts, "open": round(open_p, 2), "high": round(high, 2),
                         "low": round(low, 2), "close": round(price, 2), "volume": volume})
        ts += dt.timedelta(minutes=5)
    return candles


def test_registry_lists_three_distinct_strategies():
    names = {s["name"] for s in list_strategies()}
    assert names == {"rule_based_v1", "ema_crossover_v1", "opening_range_breakout_v1"}


def test_get_unknown_strategy_raises():
    with pytest.raises(KeyError):
        get_strategy("does_not_exist")


def test_default_strategy_is_rule_based_v1():
    assert DEFAULT_STRATEGY == "rule_based_v1"


def test_ema_crossover_fires_on_a_clean_uptrend():
    candles = _trending_candles(45, 1000, 0.15, direction=1)
    setup = ema_crossover.evaluate("NSE:TEST-EQ", candles, "STRONG_BULLISH", 1.3)
    assert setup.direction == "BUY"
    assert setup.passed is True
    assert setup.stop_loss < setup.entry_price < setup.target


def test_ema_crossover_rejects_flat_market():
    candles = _trending_candles(45, 1000, 0.0, direction=1)
    setup = ema_crossover.evaluate("NSE:TEST-EQ", candles, "NEUTRAL", 1.5)
    assert setup.passed is False


def test_ema_crossover_fires_on_a_downtrend_as_a_sell():
    candles = _trending_candles(45, 1000, 0.15, direction=-1)
    setup = ema_crossover.evaluate("NSE:TEST-EQ", candles, "STRONG_BEARISH", 1.3)
    assert setup.direction == "SELL"
    assert setup.passed is True
    assert setup.stop_loss > setup.entry_price > setup.target


def test_opening_range_breakout_waits_until_the_range_is_formed():
    yesterday = dt.date.today() - dt.timedelta(days=1)
    # enough total history to clear the >=25 candle floor, but only 2 bars
    # for "today" - not enough to complete the opening range yet
    history = _trending_candles(30, 1000, 0.05, direction=1, start_date=yesterday)
    today_so_far = _trending_candles(2, history[-1]["close"], 0.05, direction=1)
    candles = history + today_so_far

    setup = opening_range_breakout.evaluate("NSE:TEST-EQ", candles, "BULLISH", 1.3)
    assert setup.passed is False
    assert setup.direction == "NO_TRADE"
    assert "opening range" in setup.rejected_reason.lower()


def test_opening_range_breakout_fires_on_a_volume_confirmed_break():
    today = dt.date.today()
    base = dt.datetime.combine(today, dt.time(3, 45))
    candles = []
    for i, close in enumerate([1000.0, 1000.3, 999.8]):  # tight opening range
        candles.append({"timestamp": base + dt.timedelta(minutes=5 * i), "open": close - 0.2,
                         "high": close + 0.3, "low": close - 0.3, "close": close, "volume": 20_000})
    for i in range(3, 27):  # quiet consolidation to build indicator history
        close = 1000 + (i % 2) * 0.2
        candles.append({"timestamp": base + dt.timedelta(minutes=5 * i), "open": close - 0.1,
                         "high": close + 0.2, "low": close - 0.2, "close": close, "volume": 18_000})
    breakout_close = 1008.0  # clears the 1000.3 opening-range high decisively
    candles.append({"timestamp": base + dt.timedelta(minutes=5 * 27), "open": 1001.0, "high": 1008.5,
                     "low": 1000.5, "close": breakout_close, "volume": 60_000})

    setup = opening_range_breakout.evaluate("NSE:TEST-EQ", candles, "STRONG_BULLISH", 1.3)
    assert setup.direction == "BUY"
    assert setup.passed is True
    assert setup.entry_price == breakout_close


def test_opening_range_breakout_rejects_a_weak_touch_without_volume():
    today = dt.date.today()
    base = dt.datetime.combine(today, dt.time(3, 45))
    candles = []
    for i, close in enumerate([1000.0, 1000.3, 999.8]):
        candles.append({"timestamp": base + dt.timedelta(minutes=5 * i), "open": close - 0.2,
                         "high": close + 0.3, "low": close - 0.3, "close": close, "volume": 20_000})
    for i in range(3, 28):  # price barely creeps past the range, no volume surge
        close = 1000.3 + (i - 2) * 0.01
        candles.append({"timestamp": base + dt.timedelta(minutes=5 * i), "open": close - 0.05,
                         "high": close + 0.05, "low": close - 0.05, "close": close, "volume": 18_000})

    setup = opening_range_breakout.evaluate("NSE:TEST-EQ", candles, "STRONG_BULLISH", 1.3)
    assert setup.passed is False


def test_all_registered_strategies_return_a_valid_tradesetup_shape():
    candles = _trending_candles(45, 1000, 0.15, direction=1)
    for name, module in STRATEGIES.items():
        setup = module.evaluate("NSE:TEST-EQ", candles, "STRONG_BULLISH", 1.3)
        assert setup.direction in ("BUY", "SELL", "WAIT", "NO_TRADE")
        assert isinstance(setup.score, int)
        assert 0 <= setup.score <= setup.max_score


def test_rule_based_and_ema_crossover_are_independently_scored():
    """The point of Phase 4: two strategies looking at identical data can
    legitimately disagree - they are not just renamed copies of each other."""
    from app.strategies import rule_based_v1
    candles = _trending_candles(45, 1000, 0.05, direction=1)  # a weak, marginal trend
    rb = rule_based_v1.evaluate("NSE:TEST-EQ", candles, "BULLISH", 1.5)
    ema = ema_crossover.evaluate("NSE:TEST-EQ", candles, "BULLISH", 1.5)
    # components considered are different (VWAP/momentum vs acceleration/volume),
    # so at minimum their score breakdowns must differ for the same input
    assert rb.components != ema.components
