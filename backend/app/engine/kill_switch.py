"""
Emergency Stop / Kill Switch.

This is intentionally the simplest, most direct module in the codebase - it
must work even if something else in the engine is misbehaving. Activating
it does the following, in order, and nothing else:

  1. Flip kill_switch_active + auto_trading_enabled off in the DB (so the
     trading engine loop's very first check on its next tick sees it).
  2. Cancel any pending/placed-but-not-filled orders.
  3. Report open positions back to the caller - the UI then shows explicit
     "Close All Positions" as a SEPARATE action the user must press. The
     kill switch itself does not forcibly close positions, since that is a
     bigger, separate decision this module keeps distinct on purpose.

"Close All Positions" is implemented as its own function here, callable
independently of the kill switch, as required by the spec.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import UserSettings, Order, Position, RiskEvent

logger = logging.getLogger(__name__)


def activate_kill_switch(db: Session, fyers_client=None) -> dict:
    user_settings = db.query(UserSettings).first()
    if user_settings:
        user_settings.kill_switch_active = True
        user_settings.auto_trading_enabled = False
        db.commit()

    cancelled, cancel_errors = _cancel_pending_orders(db, fyers_client)

    open_positions = db.query(Position).filter(Position.status.in_(["OPEN", "CLOSING"])).all()

    db.add(RiskEvent(
        event_type="KILL_SWITCH", severity="CRITICAL",
        message="Emergency stop activated by user",
        details={"cancelled_orders": cancelled, "cancel_errors": cancel_errors,
                 "open_positions": [p.symbol for p in open_positions]},
    ))
    db.commit()
    logger.critical("KILL SWITCH ACTIVATED - auto trading disabled")

    from app.notifications.telegram import notify
    positions_msg = ", ".join(p.symbol for p in open_positions) if open_positions else "none"
    notify(f"[CRITICAL] Emergency stop activated. Open positions (not auto-closed): {positions_msg}")

    return {
        "kill_switch_active": True,
        "auto_trading_enabled": False,
        "cancelled_orders": cancelled,
        "cancel_errors": cancel_errors,
        "open_positions": [
            {"symbol": p.symbol, "direction": p.direction, "quantity": p.quantity,
             "entry_price": p.entry_price, "current_price": p.current_price}
            for p in open_positions
        ],
    }


def deactivate_kill_switch(db: Session) -> dict:
    """Requires an explicit user action; auto_trading_enabled stays OFF even
    after this - the user must separately press Start Auto Trading again,
    and recovery/validation (recovery.py) must pass first."""
    user_settings = db.query(UserSettings).first()
    if user_settings:
        user_settings.kill_switch_active = False
        db.commit()
    db.add(RiskEvent(event_type="KILL_SWITCH", severity="INFO", message="Emergency stop deactivated by user"))
    db.commit()
    return {"kill_switch_active": False}


def _cancel_pending_orders(db: Session, fyers_client) -> tuple[list[str], list[str]]:
    cancelled: list[str] = []
    errors: list[str] = []
    pending_orders = db.query(Order).filter(Order.status.in_(["PENDING", "PLACED"])).all()
    for order in pending_orders:
        try:
            if order.mode == "live" and fyers_client is not None and order.broker_order_id:
                fyers_client.cancel_order(order.broker_order_id)
            order.status = "CANCELLED"
            cancelled.append(order.client_order_id)
        except Exception as exc:  # never let one failed cancel stop the rest
            logger.error("Failed to cancel order %s: %s", order.client_order_id, exc)
            errors.append(f"{order.client_order_id}: {exc}")
    db.commit()
    return cancelled, errors
