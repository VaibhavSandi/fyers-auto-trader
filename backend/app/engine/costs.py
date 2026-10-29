"""
Shared transaction-cost estimate - used by BOTH live/paper order execution
(order_manager.py) and the backtesting engine (app/backtest/engine.py), so
a backtest's reported P&L uses exactly the same cost assumptions real
trading does. Keeping this in one place is what makes the two comparable.
"""
from __future__ import annotations


def estimate_charges(entry: float, exit: float, qty: int) -> float:
    """Conservative flat-rate estimate: brokerage + STT + exchange + GST + stamp duty.
    Real charges vary by broker plan; this is intentionally a slightly
    pessimistic estimate so displayed net P&L is never overstated."""
    turnover = (entry + exit) * qty
    brokerage = min(40.0, turnover * 0.0003)  # 2 legs combined, flat-ish
    stt = turnover * 0.00025
    other = turnover * 0.0001
    return round(brokerage + stt + other, 2)
