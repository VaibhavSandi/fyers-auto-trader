import datetime as dt

from app.engine import indicators as ind

IST = dt.timedelta(hours=5, minutes=30)
EPOCH = dt.datetime(1970, 1, 1)


def _epoch(ist_dt: dt.datetime) -> int:
    """Converts a naive IST wall-clock datetime to a UTC epoch int, without
    relying on the test machine's own timezone (datetime.timestamp() on a
    naive datetime assumes local time, which would make this test flaky)."""
    utc_dt = ist_dt - IST
    return int((utc_dt - EPOCH).total_seconds())


def _bar(ist_dt: dt.datetime, close: float = 100.0) -> dict:
    return {"timestamp": _epoch(ist_dt), "open": close, "high": close, "low": close,
            "close": close, "volume": 1000}


def test_session_slice_returns_everything_when_candles_are_all_one_day():
    day1 = dt.datetime(2024, 1, 2, 9, 15)
    candles = [_bar(day1 + dt.timedelta(minutes=5 * i)) for i in range(10)]
    assert ind.session_slice(candles) == candles


def test_session_slice_drops_prior_day_bars_and_keeps_only_the_latest_session():
    day1 = dt.datetime(2024, 1, 2, 9, 15)
    day2 = dt.datetime(2024, 1, 3, 9, 15)
    prior_day = [_bar(day1 + dt.timedelta(minutes=5 * i)) for i in range(30)]
    today = [_bar(day2 + dt.timedelta(minutes=5 * i)) for i in range(7)]
    combined = prior_day + today

    result = ind.session_slice(combined)

    assert len(result) == 7
    assert result == today


def test_session_slice_handles_datetime_timestamps_not_just_epoch_ints():
    """HistoricalDataService.get_candles() returns real datetime objects
    (not epoch ints) for timestamp - session_slice must handle both, since
    the backtester's candle source and the live engine's don't agree on
    which one they hand over."""
    day1 = dt.datetime(2024, 1, 2, 3, 45)  # naive UTC, matches historical.py's storage convention
    day2 = dt.datetime(2024, 1, 3, 3, 45)
    prior_day = [{"timestamp": day1 + dt.timedelta(minutes=5 * i), "open": 1, "high": 1, "low": 1,
                  "close": 1, "volume": 1} for i in range(20)]
    today = [{"timestamp": day2 + dt.timedelta(minutes=5 * i), "open": 2, "high": 2, "low": 2,
              "close": 2, "volume": 1} for i in range(5)]

    result = ind.session_slice(prior_day + today)
    assert len(result) == 5
    assert all(c["close"] == 2 for c in result)


def test_session_slice_empty_input():
    assert ind.session_slice([]) == []


def test_vwap_on_session_slice_ignores_prior_day_prices():
    """Regression test for the exact bug this change fixes: strategy.py
    computes VWAP on ind.session_slice(candles), not the raw multi-day
    window - so a prior day's very different price level must not drag
    today's VWAP away from today's own prices."""
    day1 = dt.datetime(2024, 1, 2, 9, 15)
    day2 = dt.datetime(2024, 1, 3, 9, 15)
    prior_day = [_bar(day1 + dt.timedelta(minutes=5 * i), close=2000.0) for i in range(30)]
    today = [_bar(day2 + dt.timedelta(minutes=5 * i), close=1000.0) for i in range(10)]
    combined = prior_day + today

    session_vwap = ind.vwap(ind.session_slice(combined))
    whole_window_vwap = ind.vwap(combined)

    assert session_vwap == 1000.0  # today's bars are all flat at 1000
    assert whole_window_vwap != session_vwap  # proves the bug this test guards against is real
    assert whole_window_vwap > 1500.0  # dragged toward prior day's 2000
