"""
Historical data sync endpoints - Phase 2 of the AI engine roadmap. Kicks
off downloading/storing candles from FYERS into the local market_data
table, and reports current coverage. Runs as a background task since a
full-universe sync (paced by the shared rate limiter) can take a while.
"""
from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, session_scope
from app.models import DataSyncState
from app.engine import universe
from app.engine.trading_engine import engine as trading_engine
from app.data.historical import HistoricalDataService, HistoricalDataError, VALID_RESOLUTIONS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/data", tags=["historical-data"])


class SyncRequest(BaseModel):
    symbols: list[str] | None = None  # defaults to the trading universe + indices
    timeframe: str = "5"
    days: int = 60


def _run_sync(symbols: list[str], timeframe: str, days: int) -> None:
    client = trading_engine._fyers_client
    if client is None:
        logger.error("Historical sync aborted - no FYERS client connected")
        return

    end = dt.date.today()
    start = end - dt.timedelta(days=days)

    with session_scope() as db:
        service = HistoricalDataService(db, client)
        for symbol in symbols:
            try:
                result = service.sync_symbol(symbol, timeframe, start, end, caller="historical_sync.api")
                logger.info("Synced %s %s: stored=%d fetched=%d errors=%s",
                            symbol, timeframe, result["stored"], result["fetched"], result["errors"])
            except HistoricalDataError as exc:
                logger.error("Sync failed for %s: %s", symbol, exc)


@router.post("/sync")
def start_sync(payload: SyncRequest, background_tasks: BackgroundTasks):
    if payload.timeframe not in VALID_RESOLUTIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported timeframe. Use one of {sorted(VALID_RESOLUTIONS)}")
    if trading_engine._fyers_client is None:
        raise HTTPException(status_code=400, detail="Connect FYERS first - historical sync needs a live connection")

    symbols = payload.symbols or (universe.get_universe_symbols() + list(universe.INDEX_SYMBOLS.values()))
    background_tasks.add_task(_run_sync, symbols, payload.timeframe, payload.days)
    return {"started": True, "symbols": len(symbols), "timeframe": payload.timeframe, "days": payload.days}


@router.get("/status")
def sync_status(db: Session = Depends(get_db)):
    rows = db.query(DataSyncState).order_by(DataSyncState.symbol.asc()).all()
    return [{
        "symbol": r.symbol, "timeframe": r.timeframe,
        "earliest_synced": r.earliest_synced, "latest_synced": r.latest_synced,
        "candles_stored": r.candles_stored, "last_sync_at": r.last_sync_at,
        "last_sync_status": r.last_sync_status, "last_sync_message": r.last_sync_message,
    } for r in rows]


@router.get("/gaps")
def data_gaps(symbol: str, timeframe: str = "5", days: int = 60, db: Session = Depends(get_db)):
    client = trading_engine._fyers_client
    service = HistoricalDataService(db, client)
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    gaps = service.find_gaps(symbol, timeframe, start, end)
    return {"symbol": symbol, "timeframe": timeframe, "missing_weekdays": [g.isoformat() for g in gaps]}
