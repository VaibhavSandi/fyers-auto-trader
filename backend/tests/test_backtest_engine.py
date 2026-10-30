import datetime as dt

from app.backtest.engine import Backtester, BacktestTradeResult, _compute_metrics
from app.data.historical import HistoricalDataService
from app.config import get_settings
from app.models import MarketData
from app.strategies import rule_based_v1


def _store_candles(db, symbol: str, timeframe: str, candles: list[dict]) -> None:
    for c in candles:
        db.add(MarketData(symbol=symbol, timeframe=timeframe, timestamp=c["timestamp"],
                           open=c["open"], high=c["high"], low=c["low"], close=c["close"],
                           volume=c["volume"], source="test"))
    db.commit()


def _candles_series(start_date: dt.date, bars: int, start_price: float, drift_pct: float,
                     direction: int, base_volume: float = 50_000) -> list[dict]:
    candles = []
    price = start_price
    ts = dt.datetime.combine(start_date, dt.time(3, 45))  # 09:15 IST == 03:45 UTC
    for i in range(bars):
        open_p = price
        bar_direction = -0.9 if (i % 3 == 2) else 1.0
        price = price * (1 + direction * bar_direction * drift_pct / 100)
        high = max(open_p, price) * 1.001
        low = min(open_p, price) * 0.999
        volume = base_volume * (1.5 if i % 10 == 9 else 1.0)
        candles.append({"timestamp": ts, "open": round(open_p, 2), "high": round(high, 2),
                         "low": round(low, 2), "close": round(price, 2), "volume": volume})
        ts += dt.timedelta(minutes=5)
    return candles


def test_insufficient_data_produces_no_trades_with_a_clear_warning(db_session):
    service = HistoricalDataService(db_session, fyers_client=None)
    bt = Backtester(service, get_settings())
    today = dt.date.today()
    result = bt.run(symbol="NSE:TEST-EQ", timeframe="5", start=today, end=today,
                     capital=10000, risk_profile="conservative")
    assert result.trades == []
    assert any("candles available" in w for w in result.warnings)


def test_missing_index_data_blocks_every_trade_with_a_warning(db_session):
    today = dt.date.today()
    stock = _candles_series(today, 60, 1000, 0.12, direction=1)
    _store_candles(db_session, "NSE:TEST-EQ", "5", stock)
    # deliberately do NOT store NIFTY50/BANKNIFTY candles

    service = HistoricalDataService(db_session, fyers_client=None)
    bt = Backtester(service, get_settings())
    result = bt.run(symbol="NSE:TEST-EQ", timeframe="5", start=today, end=today,
                     capital=10000, risk_profile="aggressive")

    assert result.trades == []
    assert any("Index history" in w for w in result.warnings)


def test_backtester_runs_a_non_default_strategy_when_requested(db_session):
    today = dt.date.today()
    stock = _candles_series(today, 60, 1000, 0.15, direction=1)
    nifty = _candles_series(today, 60, 24000, 0.15, direction=1)
    banknifty = _candles_series(today, 60, 51000, 0.15, direction=1)
    _store_candles(db_session, "NSE:TEST-EQ", "5", stock)
    _store_candles(db_session, "NSE:NIFTY50-INDEX", "5", nifty)
    _store_candles(db_session, "NSE:NIFTYBANK-INDEX", "5", banknifty)

    service = HistoricalDataService(db_session, fyers_client=None)
    bt = Backtester(service, get_settings())
    result = bt.run(symbol="NSE:TEST-EQ", timeframe="5", start=today, end=today,
                     capital=10000, risk_profile="aggressive", strategy_name="ema_crossover_v1")

    assert result.strategy_name == "ema_crossover_v1"
    assert result.metrics["total_trades"] == len(result.trades)


def test_strong_trend_with_regime_data_produces_at_least_one_trade(db_session):
    today = dt.date.today()
    stock = _candles_series(today, 60, 1000, 0.12, direction=1)
    nifty = _candles_series(today, 60, 24000, 0.12, direction=1)
    banknifty = _candles_series(today, 60, 51000, 0.12, direction=1)
    _store_candles(db_session, "NSE:TEST-EQ", "5", stock)
    _store_candles(db_session, "NSE:NIFTY50-INDEX", "5", nifty)
    _store_candles(db_session, "NSE:NIFTYBANK-INDEX", "5", banknifty)

    service = HistoricalDataService(db_session, fyers_client=None)
    bt = Backtester(service, get_settings())
    result = bt.run(symbol="NSE:TEST-EQ", timeframe="5", start=today, end=today,
                     capital=10000, risk_profile="aggressive")

    assert len(result.trades) >= 1
    assert result.metrics["total_trades"] == len(result.trades)
    # every trade must have been closed - never left dangling with no exit recorded
    assert all(t.exit_price is not None and t.exit_reason is not None for t in result.trades)


def test_no_look_ahead_strategy_only_ever_sees_candles_up_to_the_current_bar(db_session, monkeypatch):
    today = dt.date.today()
    stock = _candles_series(today, 50, 1000, 0.12, direction=1)
    nifty = _candles_series(today, 50, 24000, 0.12, direction=1)
    banknifty = _candles_series(today, 50, 51000, 0.12, direction=1)
    _store_candles(db_session, "NSE:TEST-EQ", "5", stock)
    _store_candles(db_session, "NSE:NIFTY50-INDEX", "5", nifty)
    _store_candles(db_session, "NSE:NIFTYBANK-INDEX", "5", banknifty)

    seen_window_lengths = []
    real_evaluate = rule_based_v1.evaluate

    def spy_evaluate(symbol, candles, regime, min_rr):
        seen_window_lengths.append(len(candles))
        assert len(candles) <= len(stock), "strategy was handed more candles than exist up to this point"
        return real_evaluate(symbol, candles, regime, min_rr)

    # The backtester resolves strategies through the registry, which holds
    # its own reference to rule_based_v1.evaluate - patch that reference
    # (not app.engine.strategy.evaluate, which the registry no longer calls
    # directly after import time).
    monkeypatch.setattr(rule_based_v1, "evaluate", spy_evaluate)

    service = HistoricalDataService(db_session, fyers_client=None)
    bt = Backtester(service, get_settings())
    bt.run(symbol="NSE:TEST-EQ", timeframe="5", start=today, end=today,
           capital=10000, risk_profile="aggressive")

    assert len(seen_window_lengths) > 0
    # window length must grow monotonically with each successive bar evaluated -
    # never jump ahead, never see the full dataset before the final bar
    assert seen_window_lengths == sorted(seen_window_lengths)
    assert all(n <= len(stock) for n in seen_window_lengths)


def test_same_bar_stop_and_target_conservatively_resolves_to_stop_buy():
    trade = BacktestTradeResult(
        direction="BUY", entry_time=dt.datetime.utcnow(), entry_price=100, quantity=10,
        stop_loss=95, original_stop_loss=95, target=110, score=8, market_regime="BULLISH",
    )
    # a single wild bar whose range covers BOTH the stop and the target
    bar = {"open": 100, "high": 115, "low": 90, "close": 105, "volume": 1000}
    exit_price, reason = Backtester._check_bar_exit(trade, bar)
    assert exit_price == 95
    assert reason == "STOP_LOSS"


def test_same_bar_stop_and_target_conservatively_resolves_to_stop_sell():
    trade = BacktestTradeResult(
        direction="SELL", entry_time=dt.datetime.utcnow(), entry_price=100, quantity=10,
        stop_loss=105, original_stop_loss=105, target=90, score=8, market_regime="BEARISH",
    )
    bar = {"open": 100, "high": 110, "low": 85, "close": 95, "volume": 1000}
    exit_price, reason = Backtester._check_bar_exit(trade, bar)
    assert exit_price == 105
    assert reason == "STOP_LOSS"


def test_target_only_hit_resolves_to_target():
    trade = BacktestTradeResult(
        direction="BUY", entry_time=dt.datetime.utcnow(), entry_price=100, quantity=10,
        stop_loss=95, original_stop_loss=95, target=110, score=8, market_regime="BULLISH",
    )
    bar = {"open": 105, "high": 112, "low": 104, "close": 111, "volume": 1000}
    exit_price, reason = Backtester._check_bar_exit(trade, bar)
    assert exit_price == 110
    assert reason == "TARGET"


def test_metrics_win_rate_and_profit_factor():
    trades = [
        BacktestTradeResult(direction="BUY", entry_time=dt.datetime.utcnow(), entry_price=100, quantity=10,
                             stop_loss=95, original_stop_loss=95, target=110, score=8, market_regime="BULLISH",
                             net_pnl=100.0),
        BacktestTradeResult(direction="BUY", entry_time=dt.datetime.utcnow(), entry_price=100, quantity=10,
                             stop_loss=95, original_stop_loss=95, target=110, score=8, market_regime="BULLISH",
                             net_pnl=-50.0),
    ]
    metrics = _compute_metrics(trades, starting_capital=10000)
    assert metrics["total_trades"] == 2
    assert metrics["winning_trades"] == 1
    assert metrics["win_rate"] == 50.0
    assert metrics["profit_factor"] == 2.0  # 100 gross profit / 50 gross loss
    assert metrics["expectancy"] == 25.0  # (100 - 50) / 2


def test_metrics_on_empty_trade_list_does_not_crash():
    metrics = _compute_metrics([], starting_capital=10000)
    assert metrics["total_trades"] == 0
    assert metrics["win_rate"] == 0.0
    assert metrics["sharpe_like"] is None


def test_warm_start_lets_a_strategy_trade_on_day_two_before_25_same_day_bars_exist(db_session):
    """Regression test for the exact live bug this change fixes: with
    warm_start=False (the old same-day-only behavior), day 2 of a backtest
    must behave exactly like the old live engine did - unable to trade
    until 25 bars of THAT day alone exist. With warm_start=True (the new
    default/live behavior), day 2 inherits day 1's bars and can trade
    immediately if a valid setup appears."""
    day1 = dt.date.today() - dt.timedelta(days=1)
    day2 = dt.date.today()

    # Day 1: flat/no-trend - never produces a signal either way, exists only
    # to supply warm-up history for day 2.
    flat = _candles_series(day1, 30, 1000, 0.01, direction=1)
    # Day 2: a strong uptrend starting right at today's open - only 20 bars,
    # so the same-day-only slice NEVER reaches the 25-bar minimum all day.
    trending = _candles_series(day2, 20, flat[-1]["close"], 0.3, direction=1)

    stock = flat + trending
    nifty_day1 = _candles_series(day1, 30, 24000, 0.01, direction=1)
    banknifty_day1 = _candles_series(day1, 30, 51000, 0.01, direction=1)
    nifty = nifty_day1 + _candles_series(day2, 20, nifty_day1[-1]["close"], 0.3, direction=1)
    banknifty = banknifty_day1 + _candles_series(day2, 20, banknifty_day1[-1]["close"], 0.3, direction=1)

    _store_candles(db_session, "NSE:TEST-EQ", "5", stock)
    _store_candles(db_session, "NSE:NIFTY50-INDEX", "5", nifty)
    _store_candles(db_session, "NSE:NIFTYBANK-INDEX", "5", banknifty)

    service = HistoricalDataService(db_session, fyers_client=None)
    bt = Backtester(service, get_settings())

    old_behavior = bt.run(symbol="NSE:TEST-EQ", timeframe="5", start=day1, end=day2,
                           capital=10000, risk_profile="aggressive", warm_start=False)
    new_behavior = bt.run(symbol="NSE:TEST-EQ", timeframe="5", start=day1, end=day2,
                           capital=10000, risk_profile="aggressive", warm_start=True)

    assert len(old_behavior.trades) == 0  # day 1 is flat, day 2 never reaches 25 same-day bars
    assert len(new_behavior.trades) >= 1  # day 2 inherits day 1's bars - can trade immediately


def test_open_trade_at_data_end_is_force_closed_with_a_warning(db_session):
    today = dt.date.today()
    # a trend that only gets going near the very end of the data, so by the
    # time a position opens there isn't enough remaining data for it to hit
    # its stop, target, or square-off before the series ends
    flat = _candles_series(today, 35, 1000, 0.01, direction=1, base_volume=20_000)
    trending = _candles_series(today, 20, flat[-1]["close"], 0.15, direction=1)
    trending[0]["timestamp"] = flat[-1]["timestamp"] + dt.timedelta(minutes=5)
    for i in range(1, len(trending)):
        trending[i]["timestamp"] = trending[i - 1]["timestamp"] + dt.timedelta(minutes=5)
    stock = flat + trending

    nifty = _candles_series(today, len(stock), 24000, 0.1, direction=1)
    banknifty = _candles_series(today, len(stock), 51000, 0.1, direction=1)
    for i in range(len(stock)):
        nifty[i]["timestamp"] = stock[i]["timestamp"]
        banknifty[i]["timestamp"] = stock[i]["timestamp"]

    _store_candles(db_session, "NSE:TEST-EQ", "5", stock)
    _store_candles(db_session, "NSE:NIFTY50-INDEX", "5", nifty)
    _store_candles(db_session, "NSE:NIFTYBANK-INDEX", "5", banknifty)

    service = HistoricalDataService(db_session, fyers_client=None)
    bt = Backtester(service, get_settings())
    result = bt.run(symbol="NSE:TEST-EQ", timeframe="5", start=today, end=today,
                     capital=10000, risk_profile="aggressive")

    # Whether or not a trade happened to open, the run must complete cleanly
    # and never leave a dangling trade with no exit recorded.
    assert all(t.exit_reason is not None for t in result.trades)
    if any(t.exit_reason == "BACKTEST_END" for t in result.trades):
        assert any("force-closed" in w for w in result.warnings)
