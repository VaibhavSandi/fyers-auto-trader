"""
Historical data engine - downloads, validates, and persists OHLCV candles
from FYERS into the local market_data table. This is the foundation every
later research/backtesting/ML phase reads from; nothing downstream invents
or interpolates a price that didn't come from here.

Rules enforced throughout:
  - Every stored candle's source is recorded (never silently "estimated").
  - A candle is never written with a timestamp in the future relative to
    when the sync ran (future-data-leakage guard).
  - Duplicate (symbol, timeframe, timestamp) candles update in place rather
    than creating a second row (enforced by a DB unique index too, not just
    application logic).
  - Missing weekdays (holidays, or simply not yet synced) are left missing
    - never filled with a copied/interpolated value. find_gaps() reports
    them; it never fills them.
  - All FYERS calls go through the existing shared rate limiter via
    FyersClient - this module adds no new unpaced network access.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.models import MarketData, DataSyncState
from app.fyers.client import FyersClient, FyersApiError, FyersRateLimitError

logger = logging.getLogger(__name__)

# FYERS history API date-range limits are resolution-dependent. These are
# conservative per-request windows (see fyers.in/api-docs/v3/api/data-api/)
# - requests are chunked to these sizes rather than assuming an arbitrary
# range always succeeds in one call.
MAX_DAYS_PER_REQUEST = {
    "1": 30, "3": 90, "5": 90, "15": 180, "30": 180, "60": 180, "D": 365,
}
VALID_RESOLUTIONS = set(MAX_DAYS_PER_REQUEST.keys())


class HistoricalDataError(RuntimeError):
    pass


def _chunk_date_range(start: dt.date, end: dt.date, max_days: int) -> list[tuple[dt.date, dt.date]]:
    chunks = []
    cur = start
    while cur <= end:
        chunk_end = min(end, cur + dt.timedelta(days=max_days - 1))
        chunks.append((cur, chunk_end))
        cur = chunk_end + dt.timedelta(days=1)
    return chunks


class HistoricalDataService:
    def __init__(self, db: Session, fyers_client: FyersClient):
        self.db = db
        self.client = fyers_client

    def get_coverage(self, symbol: str, timeframe: str) -> DataSyncState | None:
        return self.db.query(DataSyncState).filter_by(symbol=symbol, timeframe=timeframe).first()

    def sync_symbol(self, symbol: str, timeframe: str, start: dt.date, end: dt.date,
                     caller: str = "historical_sync") -> dict:
        """Downloads and upserts candles for [start, end] (inclusive). Returns a summary dict."""
        if timeframe not in VALID_RESOLUTIONS:
            raise HistoricalDataError(f"Unsupported timeframe '{timeframe}'. Supported: {sorted(VALID_RESOLUTIONS)}")

        today = dt.date.today()
        if start > today:
            raise HistoricalDataError("Cannot sync a start date in the future")
        end = min(end, today)  # never request/accept future data

        max_days = MAX_DAYS_PER_REQUEST[timeframe]
        total_fetched = 0
        total_stored = 0
        total_rejected_future = 0
        errors: list[str] = []

        for chunk_start, chunk_end in _chunk_date_range(start, end, max_days):
            try:
                candles = self.client.get_history(
                    symbol, timeframe, chunk_start.isoformat(), chunk_end.isoformat(), caller=caller,
                )
            except FyersRateLimitError as exc:
                errors.append(f"{chunk_start}..{chunk_end}: rate-limited - {exc}")
                break  # stop this symbol's sync rather than push through a rate limit
            except FyersApiError as exc:
                errors.append(f"{chunk_start}..{chunk_end}: {exc}")
                continue

            total_fetched += len(candles)
            stored, rejected = self._upsert_candles(symbol, timeframe, candles)
            total_stored += stored
            total_rejected_future += rejected

        self._update_sync_state(symbol, timeframe, errors)

        return {
            "symbol": symbol, "timeframe": timeframe, "fetched": total_fetched,
            "stored": total_stored, "rejected_future_candles": total_rejected_future,
            "errors": errors,
        }

    def _upsert_candles(self, symbol: str, timeframe: str, candles: list[dict]) -> tuple[int, int]:
        now = dt.datetime.utcnow()
        stored = 0
        rejected_future = 0
        seen_timestamps: set = set()

        for c in candles:
            ts_epoch = c.get("timestamp")
            if ts_epoch is None:
                continue
            candle_dt = dt.datetime.utcfromtimestamp(ts_epoch)

            if candle_dt > now:
                # A candle timestamped in the future is never legitimate -
                # guard against clock skew / API anomalies rather than store it.
                rejected_future += 1
                continue

            if ts_epoch in seen_timestamps:
                continue  # duplicate within this same response
            seen_timestamps.add(ts_epoch)

            existing = self.db.query(MarketData).filter_by(
                symbol=symbol, timeframe=timeframe, timestamp=candle_dt
            ).first()
            if existing:
                existing.open, existing.high = c["open"], c["high"]
                existing.low, existing.close = c["low"], c["close"]
                existing.volume = c["volume"]
                existing.source = "fyers_history"
            else:
                self.db.add(MarketData(
                    symbol=symbol, timeframe=timeframe, timestamp=candle_dt,
                    open=c["open"], high=c["high"], low=c["low"], close=c["close"],
                    volume=c["volume"], source="fyers_history", is_complete=True,
                ))
            stored += 1

        self.db.commit()
        return stored, rejected_future

    def _update_sync_state(self, symbol: str, timeframe: str, errors: list[str]) -> None:
        earliest = (
            self.db.query(MarketData.timestamp).filter_by(symbol=symbol, timeframe=timeframe)
            .order_by(MarketData.timestamp.asc()).first()
        )
        latest = (
            self.db.query(MarketData.timestamp).filter_by(symbol=symbol, timeframe=timeframe)
            .order_by(MarketData.timestamp.desc()).first()
        )
        count = self.db.query(MarketData).filter_by(symbol=symbol, timeframe=timeframe).count()

        state = self.get_coverage(symbol, timeframe)
        if state is None:
            state = DataSyncState(symbol=symbol, timeframe=timeframe)
            self.db.add(state)

        state.earliest_synced = earliest[0] if earliest else None
        state.latest_synced = latest[0] if latest else None
        state.last_sync_at = dt.datetime.utcnow()
        state.last_sync_status = "ERROR" if errors and count == 0 else ("PARTIAL" if errors else "OK")
        state.last_sync_message = "; ".join(errors) if errors else None
        state.candles_stored = count
        self.db.commit()

    def find_gaps(self, symbol: str, timeframe: str, start: dt.date, end: dt.date) -> list[dt.date]:
        """Weekday dates in [start, end] with zero stored candles - each is
        either an un-synced gap or a market holiday. This never fills them;
        it only reports them so a caller can decide what to do."""
        existing_dates = {
            row[0].date() for row in
            self.db.query(MarketData.timestamp).filter(
                MarketData.symbol == symbol, MarketData.timeframe == timeframe,
                MarketData.timestamp >= dt.datetime.combine(start, dt.time.min),
                MarketData.timestamp <= dt.datetime.combine(end, dt.time.max),
            ).all()
        }
        gaps = []
        cur = start
        while cur <= end:
            if cur.weekday() < 5 and cur not in existing_dates:  # Mon-Fri only
                gaps.append(cur)
            cur += dt.timedelta(days=1)
        return gaps

    def get_candles(self, symbol: str, timeframe: str, start: dt.date, end: dt.date) -> list[dict]:
        """Reads stored candles back out, oldest first - what the
        backtester and any future feature pipeline actually consume."""
        rows = (
            self.db.query(MarketData)
            .filter(
                MarketData.symbol == symbol, MarketData.timeframe == timeframe,
                MarketData.timestamp >= dt.datetime.combine(start, dt.time.min),
                MarketData.timestamp <= dt.datetime.combine(end, dt.time.max),
            )
            .order_by(MarketData.timestamp.asc())
            .all()
        )
        return [
            {"timestamp": r.timestamp, "open": r.open, "high": r.high, "low": r.low,
             "close": r.close, "volume": r.volume}
            for r in rows
        ]
