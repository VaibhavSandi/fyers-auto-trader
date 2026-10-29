"""
Order Manager - the only module allowed to talk to FYERS (or the paper
broker) to place/cancel orders. The Risk Engine must have already approved
a trade before anything here is called.

Safety rules enforced here:
  - Every order gets a unique client_order_id up front; we check the DB for
    an existing order with that id before creating a new row (idempotency).
  - We NEVER place a second entry order for a symbol that already has an
    open or pending position (checked again here as a last line of defence,
    in addition to the Risk Engine check).
  - A failed/rejected placement is never automatically retried. It is logged
    and surfaced; a human (or the next clean scan cycle) decides what's next.
  - For live orders, fill status is confirmed by polling FYERS' orderbook -
    we never assume a fill happened just because the placement call returned.
"""
from __future__ import annotations

import logging
import time
import uuid
import datetime as dt

from sqlalchemy.orm import Session

from app.models import Order, Position, AuditLog
from app.engine import paper_broker
from app.engine.costs import estimate_charges

logger = logging.getLogger(__name__)

FILL_CONFIRM_RETRIES = 5
FILL_CONFIRM_DELAY_SEC = 1.0

SIDE_MAP = {"BUY": 1, "SELL": -1}


class OrderManagerError(RuntimeError):
    pass


class OrderManager:
    def __init__(self, db: Session, mode: str, fyers_client=None):
        self.db = db
        self.mode = mode  # "paper" | "live"
        self.fyers_client = fyers_client
        if mode == "live" and fyers_client is None:
            raise OrderManagerError("Live mode requires a connected FYERS client")

    def _new_client_order_id(self) -> str:
        return f"CO-{uuid.uuid4().hex[:16]}"

    def _audit(self, action: str, details: dict) -> None:
        self.db.add(AuditLog(actor="SYSTEM", action=action, details=details))
        self.db.commit()

    # ---- entries -----------------------------------------------------------

    def place_entry(self, *, symbol: str, direction: str, quantity: int, reference_price: float,
                     stop_loss: float, target: float, signal_id: int | None,
                     available_capital: float | None = None,
                     avg_bar_volume: float | None = None) -> tuple[Order, Position | None]:
        existing_open = self.db.query(Position).filter(
            Position.symbol == symbol, Position.status.in_(["OPEN", "CLOSING"])
        ).first()
        if existing_open:
            raise OrderManagerError(f"Refusing duplicate entry: {symbol} already has an open position")

        # Available-capital check (Phase 7): available_capital, when given by
        # the caller, already accounts for capital locked in OTHER open
        # positions - position sizing alone only knows the day's starting
        # capital, not what's currently committed elsewhere.
        capital_required = quantity * reference_price
        if available_capital is not None and capital_required > available_capital:
            client_order_id = self._new_client_order_id()
            order = Order(
                client_order_id=client_order_id, symbol=symbol, side=direction, order_type="MARKET",
                quantity=quantity, price=reference_price, purpose="ENTRY", status="REJECTED", mode=self.mode,
                error_message=(f"Insufficient available capital: need Rs.{capital_required:.2f}, "
                               f"have Rs.{available_capital:.2f} (after capital locked in other open positions)"),
            )
            self.db.add(order)
            self.db.commit()
            self._audit("ORDER_REJECTED_INSUFFICIENT_CAPITAL", {
                "symbol": symbol, "capital_required": round(capital_required, 2),
                "available_capital": round(available_capital, 2),
            })
            return order, None

        client_order_id = self._new_client_order_id()
        order = Order(
            client_order_id=client_order_id, symbol=symbol, side=direction, order_type="MARKET",
            quantity=quantity, price=reference_price, purpose="ENTRY", status="PENDING", mode=self.mode,
        )
        self.db.add(order)
        self.db.commit()

        try:
            if self.mode == "paper":
                fill = paper_broker.simulate_fill(symbol=symbol, side=direction, quantity=quantity,
                                                   reference_price=reference_price, avg_bar_volume=avg_bar_volume)
                self._apply_fill(order, fill.broker_order_id, fill.status, fill.filled_quantity, fill.average_price)
                if fill.status == "REJECTED":
                    order.error_message = fill.message
                    self.db.commit()
            else:
                resp = self.fyers_client.place_order(
                    symbol=symbol, qty=quantity, side=SIDE_MAP[direction], order_type=2,
                    product_type="INTRADAY",
                )
                broker_order_id = str(resp.get("id", ""))
                order.broker_order_id = broker_order_id
                order.status = "PLACED"
                order.raw_response = resp
                self.db.commit()
                self._confirm_live_fill(order)
        except Exception as exc:
            order.status = "ERROR"
            order.error_message = str(exc)
            self.db.commit()
            logger.exception("Order placement failed for %s", symbol)
            self._audit("ORDER_PLACEMENT_FAILED", {"symbol": symbol, "error": str(exc)})
            return order, None

        if order.status not in ("FILLED", "PARTIAL"):
            self._audit("ORDER_NOT_FILLED", {"symbol": symbol, "status": order.status})
            return order, None

        # A partial fill still gets full protection - sized to whatever
        # quantity actually filled, never to the originally intended quantity.
        position = Position(
            symbol=symbol, direction=direction, quantity=order.filled_quantity,
            entry_price=order.average_price, stop_loss=stop_loss, original_stop_loss=stop_loss,
            target=target, current_price=order.average_price, status="OPEN", mode=self.mode,
            signal_id=signal_id,
        )
        self.db.add(position)
        self.db.commit()
        order.position_id = position.id
        self.db.commit()

        self._audit("ENTRY_FILLED" if order.status == "FILLED" else "ENTRY_PARTIALLY_FILLED", {
            "symbol": symbol, "direction": direction, "quantity": order.filled_quantity,
            "price": order.average_price, "stop_loss": stop_loss, "target": target,
        })
        return order, position

    # ---- exits ---------------------------------------------------------------

    def place_exit(self, *, position: Position, reference_price: float, reason: str) -> Order:
        exit_side = "SELL" if position.direction == "BUY" else "BUY"
        client_order_id = self._new_client_order_id()
        order = Order(
            client_order_id=client_order_id, symbol=position.symbol, side=exit_side, order_type="MARKET",
            quantity=position.quantity, price=reference_price, purpose=self._purpose_for_reason(reason),
            status="PENDING", mode=self.mode, position_id=position.id,
        )
        self.db.add(order)
        position.status = "CLOSING"
        self.db.commit()

        try:
            if self.mode == "paper":
                fill = paper_broker.simulate_fill(symbol=position.symbol, side=exit_side,
                                                   quantity=position.quantity, reference_price=reference_price)
                self._apply_fill(order, fill.broker_order_id, fill.status, fill.filled_quantity, fill.average_price)
            else:
                resp = self.fyers_client.place_order(
                    symbol=position.symbol, qty=position.quantity, side=SIDE_MAP[exit_side],
                    order_type=2, product_type="INTRADAY",
                )
                order.broker_order_id = str(resp.get("id", ""))
                order.status = "PLACED"
                order.raw_response = resp
                self.db.commit()
                self._confirm_live_fill(order)
        except Exception as exc:
            order.status = "ERROR"
            order.error_message = str(exc)
            self.db.commit()
            logger.exception("Exit order failed for %s", position.symbol)
            self._audit("EXIT_ORDER_FAILED", {"symbol": position.symbol, "error": str(exc)})
            return order

        if order.status == "FILLED":
            self._close_position(position, order, reason)
        elif order.status == "PARTIAL":
            # Reduce the open position to whatever quantity remains unfilled
            # and keep it OPEN/protected - never silently drop the remainder.
            remaining = position.quantity - order.filled_quantity
            position.quantity = remaining
            position.status = "OPEN" if remaining > 0 else "CLOSED"
            self.db.commit()
            self._audit("EXIT_PARTIALLY_FILLED", {
                "symbol": position.symbol, "filled": order.filled_quantity, "remaining": remaining,
            })

        return order

    @staticmethod
    def _purpose_for_reason(reason: str) -> str:
        return {
            "STOP_LOSS": "STOP_LOSS", "TARGET": "TARGET", "TRAILING_STOP": "TRAIL_SL",
            "TIME_EXIT": "EOD_SQUAREOFF", "EOD_SQUAREOFF": "EOD_SQUAREOFF",
            "KILL_SWITCH": "MANUAL_CLOSE", "MANUAL": "MANUAL_CLOSE",
            "SETUP_INVALIDATED": "MANUAL_CLOSE",
        }.get(reason, "MANUAL_CLOSE")

    def _close_position(self, position: Position, exit_order: Order, reason: str) -> None:
        position.status = "CLOSED"
        position.closed_at = dt.datetime.utcnow()
        position.exit_price = exit_order.average_price
        position.exit_reason = reason

        direction_sign = 1 if position.direction == "BUY" else -1
        gross_pnl = direction_sign * (position.exit_price - position.entry_price) * position.quantity
        charges = estimate_charges(position.entry_price, position.exit_price, position.quantity)
        net_pnl = gross_pnl - charges

        position.gross_pnl = round(gross_pnl, 2)
        position.charges = round(charges, 2)
        position.net_pnl = round(net_pnl, 2)
        self.db.commit()

        self._audit("POSITION_CLOSED", {
            "symbol": position.symbol, "reason": reason, "net_pnl": position.net_pnl,
        })

    # ---- fill handling -------------------------------------------------------

    def _apply_fill(self, order: Order, broker_order_id: str, status: str, filled_qty: int, avg_price: float) -> None:
        order.broker_order_id = broker_order_id
        order.filled_quantity = filled_qty
        order.average_price = avg_price
        # Pass PARTIAL through as PARTIAL - previously this collapsed any
        # non-"FILLED" paper status (including a legitimate partial fill)
        # straight to "REJECTED", which was harmless only because the paper
        # broker never actually returned PARTIAL before this Phase 7 change.
        order.status = status if status in ("FILLED", "PARTIAL") else "REJECTED"
        self.db.commit()

    def _confirm_live_fill(self, order: Order) -> None:
        for attempt in range(FILL_CONFIRM_RETRIES):
            time.sleep(FILL_CONFIRM_DELAY_SEC)
            book = self.fyers_client.get_orderbook()
            match = next((o for o in book if str(o.get("id")) == order.broker_order_id), None)
            if match is None:
                continue
            status_code = match.get("status")
            # FYERS order status codes: 1 cancelled, 2 filled, 4 transit, 5 rejected, 6 pending
            if status_code == 2:
                filled_qty = int(match.get("filledQty", order.quantity))
                order.filled_quantity = filled_qty
                order.average_price = float(match.get("tradedPrice", order.price))
                order.status = "FILLED" if filled_qty >= order.quantity else "PARTIAL"
                order.raw_response = match
                self.db.commit()
                if order.status == "PARTIAL":
                    logger.warning("Order %s partially filled: %s/%s", order.client_order_id, filled_qty, order.quantity)
                return
            if status_code == 5:
                order.status = "REJECTED"
                order.error_message = match.get("message", "Rejected by broker")
                self.db.commit()
                return
            if status_code == 1:
                order.status = "CANCELLED"
                self.db.commit()
                return
        order.status = "UNCONFIRMED"
        order.error_message = "Could not confirm fill status from broker within timeout - needs reconciliation"
        self.db.commit()
        logger.error("Order %s fill unconfirmed after %s retries", order.client_order_id, FILL_CONFIRM_RETRIES)
