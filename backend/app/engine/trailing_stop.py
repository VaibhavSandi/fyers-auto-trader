"""
Automatic trailing stop.

Rules (all enforced in code, never violated):
  - The stop can only move in the favourable direction. It is never loosened.
  - It never increases the position's original risk - the first move is to
    breakeven, never beyond giving back more than was originally risked.
  - It accounts for volatility (ATR) so it doesn't get hit by normal noise.
  - It only starts trailing once the trade has moved far enough in profit
    (>= 1R) to avoid premature stop-outs on a trade that hasn't proven itself.
"""
from __future__ import annotations

from dataclasses import dataclass

TRAIL_ACTIVATION_R = 1.0     # start trailing once profit >= 1x the original risk
TRAIL_ATR_MULTIPLE = 1.2


@dataclass
class TrailResult:
    new_stop_loss: float
    trailing_active: bool
    moved: bool


def update_trailing_stop(*, direction: str, entry_price: float, original_stop_loss: float,
                          current_stop_loss: float, current_price: float,
                          atr_value: float | None) -> TrailResult:
    risk = abs(entry_price - original_stop_loss)
    if risk <= 0:
        return TrailResult(current_stop_loss, False, False)

    atr_value = atr_value or risk  # fall back to original risk distance if ATR unavailable

    if direction == "BUY":
        favorable_move = current_price - entry_price
        if favorable_move < risk * TRAIL_ACTIVATION_R:
            return TrailResult(current_stop_loss, False, False)
        breakeven = entry_price
        atr_trail = current_price - atr_value * TRAIL_ATR_MULTIPLE
        candidate = max(breakeven, atr_trail)
        new_stop = max(current_stop_loss, candidate)
    else:  # SELL
        favorable_move = entry_price - current_price
        if favorable_move < risk * TRAIL_ACTIVATION_R:
            return TrailResult(current_stop_loss, False, False)
        breakeven = entry_price
        atr_trail = current_price + atr_value * TRAIL_ATR_MULTIPLE
        candidate = min(breakeven, atr_trail)
        new_stop = min(current_stop_loss, candidate)

    moved = round(new_stop, 2) != round(current_stop_loss, 2)
    return TrailResult(round(new_stop, 2), True, moved)
