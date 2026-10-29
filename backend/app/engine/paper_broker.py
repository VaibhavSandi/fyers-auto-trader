"""
Paper trading execution simulator.

Paper mode uses the SAME scanner, strategy and risk engine as live mode -
only this module (the execution layer) differs. Orders "fill" immediately
at the current market price (from the same live FYERS quote/feed used for
real trading) with a small simulated slippage, so paper P&L stays realistic
rather than optimistic.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

SIMULATED_SLIPPAGE_PCT = 0.03  # 3 bps, applied against the trader on both entry and exit


@dataclass
class PaperFill:
    broker_order_id: str
    filled_quantity: int
    average_price: float
    status: str  # "FILLED" | "REJECTED"
    message: str = ""


def simulate_fill(*, symbol: str, side: str, quantity: int, reference_price: float) -> PaperFill:
    if reference_price <= 0 or quantity <= 0:
        return PaperFill("", 0, 0.0, "REJECTED", "Invalid price or quantity")

    slip = reference_price * (SIMULATED_SLIPPAGE_PCT / 100)
    fill_price = reference_price + slip if side == "BUY" else reference_price - slip

    return PaperFill(
        broker_order_id=f"PAPER-{uuid.uuid4().hex[:12]}",
        filled_quantity=quantity,
        average_price=round(fill_price, 2),
        status="FILLED",
        message="Simulated fill",
    )
