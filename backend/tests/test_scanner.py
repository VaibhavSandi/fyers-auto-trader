from app.engine import scanner
from tests.conftest import make_trending_candles


def test_liquid_trending_stock_is_eligible():
    candles = make_trending_candles(500, bars=40, drift_pct=0.1, base_volume=100_000, direction=1)
    result = scanner.evaluate_symbol("NSE:LIQUID-EQ", candles, {"bid": 499.9, "ask": 500.1})
    assert result.eligible is True
    assert result.reasons_excluded == []


def test_illiquid_stock_is_excluded_even_with_a_perfect_trend():
    candles = make_trending_candles(500, bars=40, drift_pct=0.3, base_volume=500, direction=1)
    result = scanner.evaluate_symbol("NSE:ILLIQUID-EQ", candles, None)
    assert result.eligible is False
    assert any("illiquid" in r.lower() or "low" in r.lower() for r in result.reasons_excluded)


def test_penny_stock_price_band_excluded():
    candles = make_trending_candles(5, bars=40, drift_pct=0.1, base_volume=200_000, direction=1)
    result = scanner.evaluate_symbol("NSE:PENNY-EQ", candles, None)
    assert result.eligible is False


def test_too_wide_spread_excluded():
    candles = make_trending_candles(500, bars=40, drift_pct=0.1, base_volume=100_000, direction=1)
    result = scanner.evaluate_symbol("NSE:WIDESPREAD-EQ", candles, {"bid": 495.0, "ask": 505.0})
    assert result.eligible is False
    assert any("spread" in r.lower() for r in result.reasons_excluded)


def test_insufficient_history_excluded():
    candles = make_trending_candles(500, bars=5, drift_pct=0.1, direction=1)
    result = scanner.evaluate_symbol("NSE:SHORTHIST-EQ", candles, None)
    assert result.eligible is False


def test_rank_candidates_orders_by_liquidity_and_relative_volume():
    strong = scanner.evaluate_symbol("NSE:A-EQ", make_trending_candles(500, 40, 0.1, 300_000, 1), None)
    weak = scanner.evaluate_symbol("NSE:B-EQ", make_trending_candles(500, 40, 0.1, 25_000, 1), None)
    ranked = scanner.rank_candidates([weak, strong])
    assert ranked[0].symbol == "NSE:A-EQ"
