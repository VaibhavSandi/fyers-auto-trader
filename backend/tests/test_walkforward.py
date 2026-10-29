import datetime as dt

from app.backtest.engine import Backtester
from app.backtest.walkforward import run_walk_forward, _buy_and_hold_pnl
from app.data.historical import HistoricalDataService
from app.config import get_settings
from app.models import MarketData


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
    ts = dt.datetime.combine(start_date, dt.time(3, 45))
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


def _seed_multi_day(db, symbol: str, days: int, start_date: dt.date) -> None:
    for d in range(days):
        day = start_date + dt.timedelta(days=d)
        if day.weekday() >= 5:
            continue
        stock = _candles_series(day, 60, 1000, 0.12, direction=1)
        nifty = _candles_series(day, 60, 24000, 0.12, direction=1)
        banknifty = _candles_series(day, 60, 51000, 0.12, direction=1)
        _store_candles(db, symbol, "5", stock)
        _store_candles(db, "NSE:NIFTY50-INDEX", "5", nifty)
        _store_candles(db, "NSE:NIFTYBANK-INDEX", "5", banknifty)


def test_no_folds_fit_in_a_too_short_range_produces_a_clear_warning(db_session):
    service = HistoricalDataService(db_session, fyers_client=None)
    bt = Backtester(service, get_settings())
    start = dt.date(2026, 1, 5)  # Monday
    end = start + dt.timedelta(days=2)
    report = run_walk_forward(bt, symbol="NSE:TEST-EQ", timeframe="5", overall_start=start, overall_end=end,
                               train_days=3, test_days=2, embargo_days=1, capital=10000,
                               risk_profile="conservative", strategy_name="rule_based_v1")
    assert report.folds == []
    assert report.aggregate["fold_count"] == 0
    assert any("No complete fold" in w for w in report.warnings)


def test_folds_never_overlap_and_respect_the_embargo_gap(db_session):
    start = dt.date(2026, 1, 5)  # Monday
    _seed_multi_day(db_session, "NSE:TEST-EQ", days=20, start_date=start)

    service = HistoricalDataService(db_session, fyers_client=None)
    bt = Backtester(service, get_settings())
    end = start + dt.timedelta(days=19)
    report = run_walk_forward(bt, symbol="NSE:TEST-EQ", timeframe="5", overall_start=start, overall_end=end,
                               train_days=3, test_days=2, embargo_days=1, capital=10000,
                               risk_profile="aggressive", strategy_name="rule_based_v1")

    assert len(report.folds) >= 2
    for f in report.folds:
        train_end = dt.date.fromisoformat(f.train_end)
        test_start = dt.date.fromisoformat(f.test_start)
        assert (test_start - train_end).days == 2  # exactly a 1-day embargo between them

    for a, b in zip(report.folds, report.folds[1:]):
        prev_test_end = dt.date.fromisoformat(a.test_end)
        next_train_start = dt.date.fromisoformat(b.train_start)
        assert next_train_start > prev_test_end  # strictly no overlap/reuse of test data


def test_aggregate_combines_every_fold_trade_and_reports_stability(db_session):
    start = dt.date(2026, 1, 5)
    _seed_multi_day(db_session, "NSE:TEST-EQ", days=20, start_date=start)

    service = HistoricalDataService(db_session, fyers_client=None)
    bt = Backtester(service, get_settings())
    end = start + dt.timedelta(days=19)
    report = run_walk_forward(bt, symbol="NSE:TEST-EQ", timeframe="5", overall_start=start, overall_end=end,
                               train_days=3, test_days=2, embargo_days=1, capital=10000,
                               risk_profile="aggressive", strategy_name="rule_based_v1")

    total_trades_across_folds = sum(f.result.metrics["total_trades"] for f in report.folds)
    assert report.aggregate["overall_out_of_sample"]["total_trades"] == total_trades_across_folds
    assert report.aggregate["fold_count"] == len(report.folds)
    assert 0 <= report.aggregate["profitable_fold_pct"] <= 100
    assert "baseline_buy_and_hold_total_pnl" in report.aggregate


def test_buy_and_hold_baseline_matches_simple_arithmetic():
    candles = [
        {"close": 100, "timestamp": None}, {"close": 100, "timestamp": None},
        {"close": 110, "timestamp": None},
    ]
    pnl = _buy_and_hold_pnl(candles, capital=1000)
    # qty = floor(1000/100) = 10, pnl = (110-100)*10 = 100
    assert pnl == 100.0


def test_buy_and_hold_baseline_handles_insufficient_data():
    assert _buy_and_hold_pnl([{"close": 100, "timestamp": None}], capital=1000) is None
    assert _buy_and_hold_pnl([], capital=1000) is None
