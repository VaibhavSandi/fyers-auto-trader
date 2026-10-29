from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog, UserSettings
from app.engine import kill_switch
from app.engine.order_manager import OrderManager
from app.engine.position_manager import PositionManager
from app.engine.trading_engine import engine as trading_engine

router = APIRouter(prefix="/api/emergency", tags=["emergency"])


@router.post("/kill-switch/activate")
def activate(db: Session = Depends(get_db)):
    settings = db.query(UserSettings).first()
    mode = settings.trading_mode if settings else "paper"
    client = trading_engine._fyers_client if mode == "live" else None
    result = kill_switch.activate_kill_switch(db, client)
    db.add(AuditLog(actor="USER", action="KILL_SWITCH_ACTIVATED", details=result))
    db.commit()
    return result


@router.post("/kill-switch/deactivate")
def deactivate(db: Session = Depends(get_db)):
    result = kill_switch.deactivate_kill_switch(db)
    db.add(AuditLog(actor="USER", action="KILL_SWITCH_DEACTIVATED", details=result))
    db.commit()
    return result


@router.post("/close-all-positions")
def close_all(db: Session = Depends(get_db)):
    settings = db.query(UserSettings).first()
    mode = settings.trading_mode if settings else "paper"
    client = trading_engine._fyers_client if mode == "live" else None
    order_manager = OrderManager(db, mode=mode, fyers_client=client)
    position_manager = PositionManager(db, order_manager)

    def price_lookup(symbol: str) -> float | None:
        return trading_engine._get_ltp(symbol) if mode == "live" else None

    closed = position_manager.force_close_all("MANUAL", price_lookup)
    db.add(AuditLog(actor="USER", action="CLOSE_ALL_POSITIONS", details={"closed": [p.symbol for p in closed]}))
    db.commit()
    return {"closed_positions": [p.symbol for p in closed]}
