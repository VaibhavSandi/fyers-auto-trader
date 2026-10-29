from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import UserSettings, BrokerConnection, AuditLog
from app.engine.recovery import run_recovery_check
from app.engine.trading_engine import engine as trading_engine

router = APIRouter(prefix="/api/trading", tags=["trading"])


@router.get("/recovery-check")
def recovery_check(db: Session = Depends(get_db)):
    settings = db.query(UserSettings).first()
    mode = settings.trading_mode if settings else "paper"
    trading_engine.load_client_from_db_if_needed(db)
    client = trading_engine._fyers_client if mode == "live" else None
    return run_recovery_check(db, mode, client)


@router.post("/start")
def start_auto_trading(db: Session = Depends(get_db)):
    settings = db.query(UserSettings).first()
    if settings is None:
        raise HTTPException(status_code=400, detail="Complete setup first")

    if settings.kill_switch_active:
        raise HTTPException(status_code=400, detail="Emergency stop is active - deactivate it first")

    if settings.trading_mode == "live":
        conn = db.query(BrokerConnection).filter_by(broker="fyers").first()
        token_ok = conn and conn.connected and conn.token_date == dt.date.today().isoformat()
        if not token_ok:
            raise HTTPException(status_code=400, detail="Connect your FYERS account first (live mode)")

    report = recovery_check(db)
    if not report["passed"]:
        raise HTTPException(status_code=400, detail={"message": "Recovery check failed - resolve issues before starting", "report": report})

    settings.auto_trading_enabled = True
    db.commit()
    db.add(AuditLog(actor="USER", action="AUTO_TRADING_STARTED", details={"mode": settings.trading_mode}))
    db.commit()
    trading_engine.start_background_loop()
    return {"auto_trading_enabled": True}


@router.post("/stop")
def stop_auto_trading(db: Session = Depends(get_db)):
    settings = db.query(UserSettings).first()
    if settings:
        settings.auto_trading_enabled = False
        db.commit()
    db.add(AuditLog(actor="USER", action="AUTO_TRADING_STOPPED", details={}))
    db.commit()
    return {"auto_trading_enabled": False}
