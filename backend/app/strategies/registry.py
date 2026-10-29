"""
The strategy registry - every pluggable strategy the backtester, live
engine, and (later) the self-learning loop can select between. A strategy
is just a module exposing NAME, DESCRIPTION, FAMILY, and an
evaluate(symbol, candles, market_regime, min_risk_reward) -> TradeSetup
function with the exact same TradeSetup shape app/engine/strategy.py uses -
that's the entire contract.

Registering a new strategy later is: write the module, add one line here.
"""
from __future__ import annotations

from app.strategies import rule_based_v1, ema_crossover, opening_range_breakout

STRATEGIES = {
    rule_based_v1.NAME: rule_based_v1,
    ema_crossover.NAME: ema_crossover,
    opening_range_breakout.NAME: opening_range_breakout,
}

DEFAULT_STRATEGY = rule_based_v1.NAME  # what live trading uses unless told otherwise - unchanged behavior


def get_strategy(name: str):
    if name not in STRATEGIES:
        raise KeyError(f"Unknown strategy '{name}'. Registered: {sorted(STRATEGIES.keys())}")
    return STRATEGIES[name]


def list_strategies() -> list[dict]:
    return [
        {"name": mod.NAME, "description": mod.DESCRIPTION, "family": mod.FAMILY}
        for mod in STRATEGIES.values()
    ]
