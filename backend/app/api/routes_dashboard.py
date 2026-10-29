from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import UserSettings, Position, SystemEvent, BrokerConnection, Signal, AuditLog, EngineActivity
from app.journal.analytics import today_summary
from app.engine.risk_engine import RiskEngine
from app.engine.trading_engine import engine as trading_engine
from app.config import get_settings as get_app_settings

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

CRITICAL_COMPONENTS = ["FYERS_API", "LIVE_DATA", "STRATEGY", "RISK_ENGINE", "ORDER_MANAGER",
                        "POSITION_SYNC", "DATABASE", "ENGINE"]


def _latest_status(db: Session, component: str) -> dict:
    row = db.query(SystemEvent).filter_by(component=component).order_by(SystemEvent.id.desc()).first()
    if row is None:
        return {"component": component, "status": "UNKNOWN", "message": ""}
    return {"component": component, "status": row.status, "message": row.message}


def _market_status() -> str:
    app_settings = get_app_settings()
    now = dt.datetime.now().time()
    open_t = dt.datetime.strptime(app_settings.MARKET_OPEN_TIME, "%H:%M").time()
    close_t = dt.datetime.strptime(app_settings.MARKET_CLOSE_TIME, "%H:%M").time()
    return "OPEN" if open_t <= now <= close_t else "CLOSED"


@router.get("")
def get_dashboard(db: Session = Depends(get_db)):
    settings = db.query(UserSettings).first()
    today = dt.date.today().isoformat()

    if settings is None:
        return {"setup_required": True}

    # A UserSettings row always exists (created with safe defaults at startup),
    # so "has the user actually completed setup" is tracked via audit history
    # rather than row existence.
    setup_completed = db.query(AuditLog).filter(
        AuditLog.action.in_(["SETTINGS_SAVED", "AUTO_TRADING_STARTED"])
    ).first() is not None

    summary = today_summary(db, today, settings.trading_capital)

    open_positions = db.query(Position).filter(Position.status.in_(["OPEN", "CLOSING"])).all()
    current_trades = []
    for p in open_positions:
        signal = db.query(Signal).filter(Signal.id == p.signal_id).first() if p.signal_id else None
        unrealized = (p.current_price - p.entry_price) * p.quantity if p.direction == "BUY" else (p.entry_price - p.current_price) * p.quantity
        current_trades.append({
            "symbol": p.symbol, "direction": p.direction, "quantity": p.quantity,
            "entry_price": p.entry_price, "current_price": p.current_price,
            "unrealized_pnl": round(unrealized, 2), "stop_loss": p.stop_loss, "target": p.target,
            "trailing_active": p.trailing_active,
            "explanation": signal.reasons if signal else [],
            "risk": round(abs(p.entry_price - p.original_stop_loss) * p.quantity, 2),
            "reward": round(abs(p.target - p.entry_price) * p.quantity, 2),
        })

    risk_engine = RiskEngine(db)
    trading_gate = risk_engine.check_trading_allowed(settings, today)
    no_trade_reason = None if trading_gate.allowed else trading_gate.reason

    last_signal = db.query(Signal).order_by(Signal.id.desc()).first()
    last_scan = None
    if last_signal:
        last_scan = {
            "symbol": last_signal.symbol.replace("NSE:", "").replace("-EQ", ""),
            "direction": last_signal.direction,
            "score": last_signal.score,
            "max_score": last_signal.max_score,
            "passed": last_signal.passed,
            "rejected_reason": last_signal.rejected_reason,
            "checked_at": last_signal.created_at,
        }

    last_tick = db.query(EngineActivity).order_by(EngineActivity.id.desc()).first()
    latest_activity = None
    if last_tick:
        latest_activity = {
            "stage": last_tick.stage, "message": last_tick.message, "market_regime": last_tick.market_regime,
            "universe_size": last_tick.universe_size, "eligible_count": last_tick.eligible_count,
            "candidates": last_tick.candidates, "action": last_tick.action,
            "symbol_acted": last_tick.symbol_acted, "created_at": last_tick.created_at,
        }

    net_pnl_today = summary["net_pnl"]
    day_capital = risk_engine.day_start_capital(settings, today)
    daily_loss_limit_amount = day_capital * settings.max_daily_loss_pct / 100
    loss_used_pct = round(abs(min(net_pnl_today, 0)) / daily_loss_limit_amount * 100, 1) if daily_loss_limit_amount else 0.0

    if settings.kill_switch_active:
        risk_status = "EMERGENCY_STOP"
    elif net_pnl_today <= -daily_loss_limit_amount:
        risk_status = "STOPPED_DAILY_LOSS_LIMIT"
    elif loss_used_pct >= 70:
        risk_status = "CAUTION"
    else:
        risk_status = "SAFE"

    health = [_latest_status(db, c) for c in CRITICAL_COMPONENTS]

    broker_conn = db.query(BrokerConnection).filter_by(broker="fyers").first()
    broker_connected = bool(broker_conn and broker_conn.connected and broker_conn.token_date == today)

    return {
        "setup_required": not setup_completed,
        "capital": settings.trading_capital,
        "available_capital": summary["available_capital"],
        "todays_pnl": summary["net_pnl"],
        "market_status": _market_status(),
        "trading_mode": settings.trading_mode,
        "auto_trading_active": settings.auto_trading_enabled,
        "kill_switch_active": settings.kill_switch_active,
        "no_trade_reason": no_trade_reason,
        "last_scan": last_scan,
        "latest_activity": latest_activity,
        "risk_status": risk_status,
        "daily_loss_limit_amount": round(daily_loss_limit_amount, 2),
        "daily_loss_used_pct": loss_used_pct,
        "broker_connected": broker_connected,
        "current_trades": current_trades,
        "today": {
            "trades": summary["total_trades"], "wins": summary["winning_trades"],
            "losses": summary["losing_trades"], "net_pnl": summary["net_pnl"],
            "max_drawdown": summary["max_drawdown"], "win_rate": summary["win_rate"],
        },
        "system_health": health,
        "risk_profile": settings.risk_profile,
        "settings": {
            "max_risk_per_trade_pct": settings.max_risk_per_trade_pct,
            "max_daily_loss_pct": settings.max_daily_loss_pct,
            "max_trades_per_day": settings.max_trades_per_day,
            "max_open_positions": settings.max_open_positions,
            "min_risk_reward": settings.min_risk_reward,
            "max_consecutive_losses": settings.max_consecutive_losses,
        },
    }
