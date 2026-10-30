"""
Application crash / restart recovery.

Whenever the backend process starts (whether after a normal restart,
a crash, or a Windows reboot), auto trading is FORCED OFF and a recovery
check must run and pass before the user can press "Start Auto Trading"
again. The check:

  1. Confirms DB connectivity.
  2. If a broker session exists, connects to FYERS and pulls positions/
     orders, then runs full reconciliation (broker state is authoritative).
  3. Recovers any open local positions found still open at the broker
     (keeps monitoring/protecting them) and flags local-only "phantom"
     positions the broker doesn't have.
  4. Verifies every open position still has a protective stop-loss.
  5. Verifies risk limits/settings are sane.
  6. Verifies current market status.

Nothing here resumes auto trading automatically - it only produces a report
and, if everything passed, clears the "recovery required" flag so the
Start button becomes usable again.
"""
from __future__ import annotations

import logging
import datetime as dt

from sqlalchemy.orm import Session

from app.models import UserSettings, Position, SystemEvent, RiskEvent
from app.config import get_settings

logger = logging.getLogger(__name__)


def force_safe_state_on_startup(db: Session) -> None:
    user_settings = db.query(UserSettings).first()
    if user_settings is None:
        user_settings = UserSettings()
        db.add(user_settings)
    user_settings.auto_trading_enabled = False
    db.commit()
    db.add(SystemEvent(component="ENGINE", status="DEGRADED",
                        message="Application (re)started - RECOVERY CHECK REQUIRED before auto trading can resume"))
    db.commit()

    from app.notifications.telegram import notify
    open_count = db.query(Position).filter(Position.status.in_(["OPEN", "CLOSING"])).count()
    notify("Backend (re)started - auto trading is OFF and a recovery check is required before it can resume."
           + (f" {open_count} position(s) were open at the time." if open_count else ""))


def run_recovery_check(db: Session, mode: str, fyers_client=None) -> dict:
    checks: dict[str, dict] = {}
    overall_ok = True

    try:
        db.query(UserSettings).first()
        checks["database"] = {"ok": True, "message": "Database reachable"}
    except Exception as exc:
        checks["database"] = {"ok": False, "message": str(exc)}
        overall_ok = False

    if mode == "live":
        if fyers_client is None:
            checks["broker_connection"] = {"ok": False, "message": "Not connected to FYERS"}
            overall_ok = False
        else:
            try:
                profile = fyers_client.get_profile()
                checks["broker_connection"] = {"ok": True, "message": f"Connected as {profile.get('name', 'FYERS user')}"}
            except Exception as exc:
                checks["broker_connection"] = {"ok": False, "message": f"FYERS connection failed: {exc}"}
                overall_ok = False

            if checks["broker_connection"]["ok"]:
                from app.engine.reconciliation import reconcile
                try:
                    recon = reconcile(db, fyers_client)
                    checks["reconciliation"] = {
                        "ok": recon["healthy"],
                        "message": "Matches broker" if recon["healthy"] else f"Unresolved: {recon['unknown_broker_positions']}",
                        "details": recon,
                    }
                    if not recon["healthy"]:
                        overall_ok = False
                except Exception as exc:
                    checks["reconciliation"] = {"ok": False, "message": str(exc)}
                    overall_ok = False
    else:
        checks["broker_connection"] = {"ok": True, "message": "Paper mode - no broker connection required"}

    open_positions = db.query(Position).filter(Position.status.in_(["OPEN", "CLOSING"])).all()
    missing_protection = [p.symbol for p in open_positions if not p.stop_loss]
    checks["open_position_protection"] = {
        "ok": len(missing_protection) == 0,
        "message": "All open positions have a stop-loss" if not missing_protection
                    else f"Missing stop-loss on: {missing_protection}",
        "open_positions": [p.symbol for p in open_positions],
    }
    if missing_protection:
        overall_ok = False

    if mode == "live":
        # The software-managed stop above is necessary but not sufficient -
        # it only protects a position while this process is running. A
        # missing broker-side backstop (order_manager.py's protective SL-M
        # order) means a crash/outage between now and the next restart
        # leaves the position genuinely unprotected, not just unmonitored.
        missing_broker_stop = [p.symbol for p in open_positions if not p.protective_stop_order_id]
        checks["broker_protective_stop"] = {
            "ok": len(missing_broker_stop) == 0,
            "message": "All open live positions have a broker-side backstop stop order" if not missing_broker_stop
                        else f"No broker-side backstop order on: {missing_broker_stop} - software-managed stop "
                             f"still applies, but these are unprotected if the backend goes down",
        }
        # Deliberately a WARNING, not a hard recovery-blocking failure: the
        # position IS still protected by the software-managed stop while
        # this process runs. Blocking Start entirely here would strand an
        # otherwise-fine open position with no way to resume monitoring it.
        if missing_broker_stop:
            db.add(RiskEvent(event_type="MISSING_BROKER_STOP", severity="WARNING",
                              message=f"Open live position(s) without a broker-side backstop: {missing_broker_stop}",
                              details={"symbols": missing_broker_stop}))

    user_settings = db.query(UserSettings).first()
    settings_sane = bool(user_settings and user_settings.trading_capital > 0 and user_settings.max_daily_loss_pct > 0)
    checks["risk_settings"] = {"ok": settings_sane, "message": "Risk settings look valid" if settings_sane else "Risk settings missing/invalid"}
    if not settings_sane:
        overall_ok = False

    app_settings = get_settings()
    now = dt.datetime.now().time()
    open_t = dt.datetime.strptime(app_settings.MARKET_OPEN_TIME, "%H:%M").time()
    close_t = dt.datetime.strptime(app_settings.MARKET_CLOSE_TIME, "%H:%M").time()
    market_open = open_t <= now <= close_t
    checks["market_status"] = {"ok": True, "message": "Market open" if market_open else "Market closed",
                                "market_open": market_open}

    db.add(SystemEvent(component="ENGINE", status="HEALTHY" if overall_ok else "DEGRADED",
                        message="Recovery check passed" if overall_ok else "Recovery check found issues",
                        details=checks))
    db.add(RiskEvent(event_type="RECOVERY_CHECK", severity="INFO" if overall_ok else "WARNING",
                      message="Recovery check completed", details={"passed": overall_ok}))
    db.commit()

    return {"passed": overall_ok, "checks": checks, "open_positions_recovered": len(open_positions)}
