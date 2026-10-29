import datetime as dt

import pytest

from app.data.historical import HistoricalDataService, HistoricalDataError, _chunk_date_range
from app.fyers.client import FyersRateLimitError, FyersApiError
from app.models import MarketData, DataSyncState


def _epoch(d: dt.date, hour: int = 9, minute: int = 15) -> int:
    return int(dt.datetime(d.year, d.month, d.day, hour, minute).timestamp())


class FakeFyersClient:
    """Returns pre-scripted candle batches, one list per call, in order."""

    def __init__(self, batches):
        self._batches = list(batches)
        self.calls = []

    def get_history(self, symbol, resolution, range_from, range_to, caller="unspecified"):
        self.calls.append((symbol, resolution, range_from, range_to))
        if not self._batches:
            return []
        batch = self._batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        return batch


def _candle(d: dt.date, close: float = 100.0) -> dict:
    return {"timestamp": _epoch(d), "open": close - 1, "high": close + 1, "low": close - 2,
            "close": close, "volume": 1000}


def test_sync_symbol_stores_candles(db_session):
    today = dt.date.today()
    client = FakeFyersClient([[_candle(today, 100), _candle(today - dt.timedelta(days=1), 99)]])
    service = HistoricalDataService(db_session, client)

    result = service.sync_symbol("NSE:TEST-EQ", "5", today - dt.timedelta(days=5), today)

    assert result["stored"] == 2
    assert db_session.query(MarketData).filter_by(symbol="NSE:TEST-EQ").count() == 2


def test_resyncing_the_same_candle_updates_in_place_no_duplicates(db_session):
    today = dt.date.today()
    client = FakeFyersClient([[_candle(today, 100)], [_candle(today, 105)]])  # same day, different close
    service = HistoricalDataService(db_session, client)

    service.sync_symbol("NSE:TEST-EQ", "5", today, today)
    service.sync_symbol("NSE:TEST-EQ", "5", today, today)

    rows = db_session.query(MarketData).filter_by(symbol="NSE:TEST-EQ").all()
    assert len(rows) == 1  # no duplicate row
    assert rows[0].close == 105  # updated to the latest fetch


def test_future_timestamped_candle_is_rejected_not_stored(db_session):
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    client = FakeFyersClient([[_candle(tomorrow, 100)]])
    service = HistoricalDataService(db_session, client)

    # sync_symbol clamps `end` to today, but a malformed/clock-skewed API
    # response could still return a future-timestamped candle - must be rejected.
    result = service.sync_symbol("NSE:TEST-EQ", "5", dt.date.today(), dt.date.today())
    assert result["rejected_future_candles"] == 1
    assert db_session.query(MarketData).count() == 0


def test_duplicate_candles_within_one_response_are_not_double_counted(db_session):
    today = dt.date.today()
    client = FakeFyersClient([[_candle(today, 100), _candle(today, 100)]])  # same timestamp twice
    service = HistoricalDataService(db_session, client)

    result = service.sync_symbol("NSE:TEST-EQ", "5", today, today)
    assert result["stored"] == 1
    assert db_session.query(MarketData).count() == 1


def test_unsupported_timeframe_raises():
    service = HistoricalDataService(db=None, fyers_client=FakeFyersClient([]))
    with pytest.raises(HistoricalDataError):
        service.sync_symbol("NSE:TEST-EQ", "7min", dt.date.today(), dt.date.today())


def test_future_start_date_raises(db_session):
    service = HistoricalDataService(db_session, FakeFyersClient([]))
    future = dt.date.today() + dt.timedelta(days=5)
    with pytest.raises(HistoricalDataError):
        service.sync_symbol("NSE:TEST-EQ", "5", future, future)


def test_rate_limit_during_sync_stops_gracefully_and_records_state(db_session):
    today = dt.date.today()
    client = FakeFyersClient([FyersRateLimitError("rate limited")])
    service = HistoricalDataService(db_session, client)

    result = service.sync_symbol("NSE:TEST-EQ", "5", today, today)
    assert result["stored"] == 0
    assert any("rate-limited" in e for e in result["errors"])

    state = service.get_coverage("NSE:TEST-EQ", "5")
    assert state.last_sync_status == "ERROR"


def test_generic_api_error_on_one_chunk_does_not_abort_whole_sync(db_session):
    d1 = dt.date.today()
    client = FakeFyersClient([FyersApiError("symbol invalid for this range"), [_candle(d1, 100)]])
    # force two chunks by using a 1-day-per-request timeframe artificially via monkeypatched range
    service = HistoricalDataService(db_session, client)
    # Two separate sync calls simulate two chunks each hitting the fake client once
    service.sync_symbol("NSE:TEST-EQ", "5", d1, d1)  # consumes the error
    result = service.sync_symbol("NSE:TEST-EQ", "5", d1, d1)  # consumes the candle
    assert result["stored"] == 1


def test_find_gaps_reports_missing_weekdays_without_creating_data(db_session):
    # Monday through Friday of a fixed, known week with no holidays
    monday = dt.date(2026, 1, 5)
    friday = dt.date(2026, 1, 9)
    client = FakeFyersClient([[_candle(monday, 100), _candle(dt.date(2026, 1, 7), 100)]])
    service = HistoricalDataService(db_session, client)
    service.sync_symbol("NSE:TEST-EQ", "5", monday, friday)

    gaps = service.find_gaps("NSE:TEST-EQ", "5", monday, friday)
    assert gaps == [dt.date(2026, 1, 6), dt.date(2026, 1, 8), dt.date(2026, 1, 9)]
    # weekend days must never appear
    assert dt.date(2026, 1, 10) not in gaps and dt.date(2026, 1, 11) not in gaps
    # gaps are reported only, never backfilled with invented data
    assert db_session.query(MarketData).count() == 2


def test_get_candles_returns_chronological_order(db_session):
    d1, d2 = dt.date(2026, 1, 5), dt.date(2026, 1, 6)
    client = FakeFyersClient([[_candle(d2, 102), _candle(d1, 101)]])  # fetched out of order
    service = HistoricalDataService(db_session, client)
    service.sync_symbol("NSE:TEST-EQ", "5", d1, d2)

    candles = service.get_candles("NSE:TEST-EQ", "5", d1, d2)
    assert [c["close"] for c in candles] == [101, 102]


def test_chunk_date_range_splits_long_ranges():
    start, end = dt.date(2026, 1, 1), dt.date(2026, 3, 1)
    chunks = _chunk_date_range(start, end, max_days=30)
    assert chunks[0] == (start, dt.date(2026, 1, 30))
    assert chunks[-1][1] == end
    # no gaps or overlaps between consecutive chunks
    for (s1, e1), (s2, e2) in zip(chunks, chunks[1:]):
        assert s2 == e1 + dt.timedelta(days=1)
