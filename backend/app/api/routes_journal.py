from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.journal import journal, analytics
from app.models import Signal, RiskEvent, SystemEvent, EngineActivity

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("/trades")
def get_trades(limit: int = 200, date: str | None = None, db: Session = Depends(get_db)):
    trades = journal.list_trades(db, limit=limit, date=date)
    return [journal.trade_to_dict(t) for t in trades]


@router.get("/analytics")
def get_analytics(db: Session = Depends(get_db)):
    return analytics.overall_summary(db)


@router.get("/signals")
def get_signals(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(Signal).order_by(Signal.id.desc()).limit(limit).all()
    return [{
        "id": r.id, "symbol": r.symbol, "direction": r.direction, "score": r.score,
        "max_score": r.max_score, "passed": r.passed, "reasons": r.reasons,
        "components": r.components, "market_regime": r.market_regime,
        "entry_price": r.entry_price, "stop_loss": r.stop_loss, "target": r.target,
        "risk_reward": r.risk_reward, "rejected_reason": r.rejected_reason,
        "created_at": r.created_at,
    } for r in rows]


@router.get("/risk-events")
def get_risk_events(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(RiskEvent).order_by(RiskEvent.id.desc()).limit(limit).all()
    return [{"id": r.id, "event_type": r.event_type, "severity": r.severity, "message": r.message,
             "details": r.details, "created_at": r.created_at} for r in rows]


@router.get("/system-events")
def get_system_events(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(SystemEvent).order_by(SystemEvent.id.desc()).limit(limit).all()
    return [{"id": r.id, "component": r.component, "status": r.status, "message": r.message,
             "created_at": r.created_at} for r in rows]


@router.get("/engine-activity")
def get_engine_activity(limit: int = 50, db: Session = Depends(get_db)):
    """The live, tick-by-tick feed of exactly what the trading engine did:
    market regime, how many stocks were scanned/eligible/scored, every
    candidate's score and rejection reason, and the final action taken."""
    rows = db.query(EngineActivity).order_by(EngineActivity.id.desc()).limit(limit).all()
    return [{
        "id": r.id, "mode": r.mode, "stage": r.stage, "message": r.message,
        "market_regime": r.market_regime, "universe_size": r.universe_size,
        "eligible_count": r.eligible_count, "candidates": r.candidates,
        "action": r.action, "symbol_acted": r.symbol_acted, "created_at": r.created_at,
    } for r in rows]
