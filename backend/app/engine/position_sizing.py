"""
Risk-based position sizing.

    Maximum Trade Risk (₹) ÷ Risk Per Share (₹) = Maximum Quantity (by risk)

That quantity is then additionally capped by available capital (with a
slippage/safety buffer) and a hard per-trade capital allocation ceiling so a
single trade can never tie up an unreasonable share of the account.
"""
from __future__ import annotations

from dataclasses import dataclass

MAX_CAPITAL_ALLOCATION_PCT = 80.0   # never commit more than 80% of available capital to one trade
SLIPPAGE_BUFFER_PCT = 0.5           # assume fills can be ~0.5% worse than the quoted entry


@dataclass
class SizingResult:
    quantity: int
    reason: str | None
    max_risk_amount: float
    capital_required: float
    sizing_limited_by: str | None  # "risk" | "capital" | None


def calculate_position_size(*, available_capital: float, max_risk_amount: float,
                             entry_price: float, risk_per_share: float) -> SizingResult:
    if risk_per_share <= 0 or entry_price <= 0:
        return SizingResult(0, "Invalid price/risk inputs", max_risk_amount, 0.0, None)

    qty_by_risk = int(max_risk_amount // risk_per_share)

    buffered_price = entry_price * (1 + SLIPPAGE_BUFFER_PCT / 100)
    allocatable_capital = available_capital * (MAX_CAPITAL_ALLOCATION_PCT / 100)
    qty_by_capital = int(allocatable_capital // buffered_price)

    if qty_by_risk <= 0:
        return SizingResult(0, "Risk per share too large for the allowed risk amount", max_risk_amount, 0.0, "risk")
    if qty_by_capital <= 0:
        return SizingResult(0, "Not enough available capital for even 1 share", max_risk_amount, 0.0, "capital")

    qty = min(qty_by_risk, qty_by_capital)
    limited_by = "risk" if qty_by_risk <= qty_by_capital else "capital"
    capital_required = round(qty * buffered_price, 2)

    return SizingResult(quantity=qty, reason=None, max_risk_amount=max_risk_amount,
                         capital_required=capital_required, sizing_limited_by=limited_by)
