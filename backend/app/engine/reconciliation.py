"""
Broker Reconciliation.

Regularly compares the local application state (positions/orders tables)
against FYERS' own position/order books. FYERS' state is always treated as
authoritative - if there is a mismatch, the local DB is corrected to match
the broker, every correction is logged as a RiskEvent, and if the mismatch
is one we cannot safely auto-resolve (e.g. a position at the broker that
the app has no record of at all - so we don't know its intended stop/target)
the POSITION_SYNC system health is marked DOWN, which makes the Risk Engine
stop all new trades until a human reviews it.

Only used in live mode - paper mode has no external broker state to
reconcile against.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import Position, Order, RiskEvent, SystemEvent

logger = logging.getLogger(__name__)


def _log_health(db: Session, status: str, message: str, details: dict | None = None) -> None:
    db.add(SystemEvent(component="POSITION_SYNC", status=status, message=message, details=details or {}))
    db.commit()


def reconcile(db: Session, fyers_client) -> dict:
    broker_positions = {p.get("symbol"): p for p in fyers_client.get_positions() if p.get("qty")}
    local_positions = {p.symbol: p for p in db.query(Position).filter(Position.status.in_(["OPEN", "CLOSING"])).all()}

    mismatches: list[str] = []
    unknown_broker_positions: list[str] = []

    for symbol, local in local_positions.items():
        broker = broker_positions.get(symbol)
        if broker is None:
            mismatches.append(f"{symbol}: app thinks OPEN but broker shows no position (likely already closed at broker)")
            local.status = "CLOSED"
            local.exit_reason = local.exit_reason or "RECONCILIATION_BROKER_FLAT"
            db.add(RiskEvent(event_type="RECONCILIATION_MISMATCH", severity="WARNING",
                              message=f"Closed local position for {symbol} - broker shows flat", details={}))
            continue

        broker_qty = abs(int(broker.get("qty", 0)))
        if broker_qty != local.quantity:
            mismatches.append(f"{symbol}: local qty {local.quantity} != broker qty {broker_qty}")
            local.quantity = broker_qty
            db.add(RiskEvent(event_type="RECONCILIATION_MISMATCH", severity="WARNING",
                              message=f"Corrected local quantity for {symbol} to match broker ({broker_qty})",
                              details={"broker_position": broker}))

    for symbol, broker in broker_positions.items():
        if symbol not in local_positions:
            unknown_broker_positions.append(symbol)
            db.add(RiskEvent(event_type="RECONCILIATION_UNKNOWN_POSITION", severity="CRITICAL",
                              message=f"Broker shows an open position in {symbol} unknown to this app",
                              details={"broker_position": broker}))

    db.commit()

    if unknown_broker_positions:
        _log_health(db, "DOWN", f"Unknown broker position(s) detected: {unknown_broker_positions}. "
                                 "New trades stopped until reviewed.", {"symbols": unknown_broker_positions})
    elif mismatches:
        _log_health(db, "DEGRADED", f"Reconciled {len(mismatches)} mismatch(es)", {"mismatches": mismatches})
    else:
        _log_health(db, "HEALTHY", "Local state matches broker")

    return {
        "mismatches": mismatches,
        "unknown_broker_positions": unknown_broker_positions,
        "healthy": not unknown_broker_positions,
    }
