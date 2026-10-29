"""
Thin wrapper registering the original, already-live rule-based strategy
(app/engine/strategy.py - untouched, still what live trading uses by
default) as the first entry in the pluggable strategy family. Nothing
about the original strategy changes; this just gives it a name other
strategies can be compared against.
"""
from __future__ import annotations

from app.engine.strategy import evaluate, TradeSetup, MIN_SIGNAL_SCORE  # noqa: F401

NAME = "rule_based_v1"
DESCRIPTION = (
    "The original strategy: multi-confirmation scoring (trend, VWAP, EMA, volume, "
    "momentum, market regime, risk/reward) out of 10, minimum 7 to trade."
)
FAMILY = "multi-confirmation"
