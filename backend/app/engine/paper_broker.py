"""
Paper trading execution simulator (Phase 7).

Paper mode uses the SAME scanner, strategy and risk engine as live mode -
only this module (the execution layer) differs. Fills are modeled more
realistically than "always 100% instantly at the reference price":

  - Slippage, as before - applied against the trader on both entry and exit.
  - PARTIAL fills: when the requested quantity is large relative to the
    symbol's own recent average bar volume, only a fraction fills -
    mirroring how a real market order can walk through a thin order book
    rather than being fully absorbed at one price.
  - REJECTION: an order sized far beyond what recent volume could
    plausibly absorb is rejected outright, the way a broker's risk-
    management system would reject an order it judges unfillable.

Available-virtual-capital enforcement lives in order_manager.py (it needs
visibility into OTHER open positions' locked capital, which this module
deliberately has no access to).

Still NOT simulated: limit orders (nothing in the strategy layer currently
places one - adding the mechanics here without any caller that uses them
would be dead code) and option lot-size restrictions (the app only trades
cash equity).
"""
from __future__ import annotations

import random
import uuid
from dataclasses import dataclass

SIMULATED_SLIPPAGE_PCT = 0.03  # 3 bps, applied against the trader on both entry and exit

# Liquidity-realism thresholds, expressed as "requested quantity / recent
# average bar volume". Below PARTIAL_FILL_THRESHOLD, a market order fills
# instantly and completely. Between the two thresholds, the fill tapers
# off the more of the available volume the order represents. Beyond
# REJECT_THRESHOLD, the order is rejected outright.
PARTIAL_FILL_THRESHOLD = 0.08   # requested qty is >8% of the recent avg bar volume
REJECT_THRESHOLD = 0.35         # requested qty is >35% of the recent avg bar volume


@dataclass
class PaperFill:
    broker_order_id: str
    filled_quantity: int
    average_price: float
    status: str  # "FILLED" | "PARTIAL" | "REJECTED"
    message: str = ""


def simulate_fill(*, symbol: str, side: str, quantity: int, reference_price: float,
                   avg_bar_volume: float | None = None, seed: int | None = None) -> PaperFill:
    if reference_price <= 0 or quantity <= 0:
        return PaperFill("", 0, 0.0, "REJECTED", "Invalid price or quantity")

    filled_qty = quantity
    message = "Simulated fill"

    if avg_bar_volume and avg_bar_volume > 0:
        participation = quantity / avg_bar_volume

        if participation > REJECT_THRESHOLD:
            return PaperFill(
                "", 0, 0.0, "REJECTED",
                f"Order size ({quantity}) is {participation:.0%} of recent average volume "
                f"({avg_bar_volume:.0f}) - too large to fill realistically; a broker's risk "
                f"system would reject this",
            )

        if participation > PARTIAL_FILL_THRESHOLD:
            # Deterministic taper from ~95% fill down to ~40% as
            # participation climbs from the partial to the reject
            # threshold, with a small random jitter for realism.
            rng = random.Random(seed)
            span = REJECT_THRESHOLD - PARTIAL_FILL_THRESHOLD
            progress = (participation - PARTIAL_FILL_THRESHOLD) / span
            base_ratio = 0.95 - progress * 0.55
            fill_ratio = max(0.1, min(1.0, base_ratio + rng.uniform(-0.05, 0.05)))
            filled_qty = max(1, int(quantity * fill_ratio))
            if filled_qty < quantity:
                message = f"Partial fill: {filled_qty}/{quantity} ({participation:.0%} of recent average volume)"

    slip = reference_price * (SIMULATED_SLIPPAGE_PCT / 100)
    fill_price = reference_price + slip if side == "BUY" else reference_price - slip

    return PaperFill(
        broker_order_id=f"PAPER-{uuid.uuid4().hex[:12]}",
        filled_quantity=filled_qty,
        average_price=round(fill_price, 2),
        status="FILLED" if filled_qty == quantity else "PARTIAL",
        message=message,
    )
