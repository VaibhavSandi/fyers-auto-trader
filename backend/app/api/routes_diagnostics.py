"""
Diagnostics screen data: REST requests per minute/day per category, the
module responsible for each (caller tags), WebSocket connection status and
subscribed symbol count, price-cache freshness, and recent rate-limit
errors. This is the "show me the plumbing" view - the main dashboard stays
simple, this is what you check if something looks wrong.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SystemEvent
from app.fyers.rate_limiter import get_rate_limiter
from app.fyers.price_cache import get_price_cache
from app.engine.trading_engine import engine as trading_engine

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("")
def get_diagnostics(db: Session = Depends(get_db)):
    limiter_snapshot = get_rate_limiter().snapshot()
    cache_snapshot = get_price_cache().snapshot_ages()

    feed = trading_engine._live_feed
    websocket_info = {
        "started": bool(feed and feed.started),
        "connected": bool(feed and feed.connected),
        "status": feed.status() if feed else "DISCONNECTED",
        "subscribed_symbol_count": feed.subscribed_count() if feed else 0,
        "connected_seconds": feed.connected_seconds() if feed else None,
    }

    recent_rate_limit_events = (
        db.query(SystemEvent)
        .filter(SystemEvent.status == "RATE_LIMITED")
        .order_by(SystemEvent.id.desc())
        .limit(20)
        .all()
    )

    return {
        "rate_limits": limiter_snapshot,
        "price_cache": cache_snapshot,
        "websocket": websocket_info,
        "recent_rate_limit_events": [
            {"component": e.component, "message": e.message, "created_at": e.created_at}
            for e in recent_rate_limit_events
        ],
    }
