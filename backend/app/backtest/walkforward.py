"""
Walk-forward validation (Phase 5) - runs the backtester across successive,
NON-OVERLAPPING test windows, each preceded by an embargo gap after its
training window, so no fold's result can leak across a boundary into the
next. Also computes a trivial buy-and-hold baseline per fold, because a
strategy's performance only means something next to a baseline - Phase 5's
explicit "test against simple baselines" requirement.

For the current rule-based strategies (fixed rules, no fitted parameters)
the "train" window isn't used to fit anything yet - it exists so this
harness is ready for an ML model without changing its interface. In the
meantime this still answers a real question the single-run backtester
can't: is the edge STABLE across independent time periods, or did one
lucky window carry the whole result? That's what profitable_fold_pct and
net_pnl_stdev below are for.
"""
from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field

from app.backtest.engine import Backtester, BacktestResult, _compute_metrics


@dataclass
class WalkForwardFold:
    fold_index: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    result: BacktestResult
    baseline_net_pnl: float | None


@dataclass
class WalkForwardReport:
    symbol: str
    strategy_name: str
    folds: list[WalkForwardFold]
    aggregate: dict
    warnings: list[str] = field(default_factory=list)


def _buy_and_hold_pnl(candles: list[dict], capital: float) -> float | None:
    if len(candles) < 2:
        return None
    entry, exit_price = candles[0]["close"], candles[-1]["close"]
    if entry <= 0:
        return None
    qty = int(capital // entry)
    if qty <= 0:
        return None
    return round((exit_price - entry) * qty, 2)


def run_walk_forward(backtester: Backtester, *, symbol: str, timeframe: str,
                      overall_start: dt.date, overall_end: dt.date,
                      train_days: int, test_days: int, embargo_days: int,
                      capital: float, risk_profile: str, strategy_name: str) -> WalkForwardReport:
    folds: list[WalkForwardFold] = []
    warnings: list[str] = []

    cursor = overall_start
    fold_index = 0
    while True:
        train_start = cursor
        train_end = train_start + dt.timedelta(days=train_days - 1)
        test_start = train_end + dt.timedelta(days=embargo_days + 1)
        test_end = test_start + dt.timedelta(days=test_days - 1)
        if test_end > overall_end:
            break

        result = backtester.run(
            symbol=symbol, timeframe=timeframe, start=test_start, end=test_end,
            capital=capital, risk_profile=risk_profile, strategy_name=strategy_name,
        )

        test_candles = backtester.data.get_candles(symbol, timeframe, test_start, test_end)
        baseline_pnl = _buy_and_hold_pnl(test_candles, capital)

        folds.append(WalkForwardFold(
            fold_index=fold_index, train_start=train_start.isoformat(), train_end=train_end.isoformat(),
            test_start=test_start.isoformat(), test_end=test_end.isoformat(), result=result,
            baseline_net_pnl=baseline_pnl,
        ))
        warnings.extend(f"Fold {fold_index}: {w}" for w in result.warnings)

        fold_index += 1
        # Advance strictly past this fold's test window - a test period is
        # used exactly once, never reused as a later fold's training data.
        cursor = test_end + dt.timedelta(days=1)

    if not folds:
        warnings.append(
            f"No complete fold fits in [{overall_start}, {overall_end}] with train={train_days}d, "
            f"embargo={embargo_days}d, test={test_days}d - widen the range or shrink the window sizes."
        )

    aggregate = _aggregate_folds(folds, capital)
    return WalkForwardReport(symbol=symbol, strategy_name=strategy_name, folds=folds,
                              aggregate=aggregate, warnings=warnings)


def _aggregate_folds(folds: list[WalkForwardFold], starting_capital: float) -> dict:
    if not folds:
        return {"fold_count": 0}

    all_trades = [t for f in folds for t in f.result.trades]
    overall = _compute_metrics(all_trades, starting_capital)

    per_fold_net_pnl = [f.result.metrics["net_pnl"] for f in folds]
    profitable_folds = sum(1 for p in per_fold_net_pnl if p > 0)
    baseline_total = sum(f.baseline_net_pnl for f in folds if f.baseline_net_pnl is not None)

    return {
        "fold_count": len(folds),
        "profitable_folds": profitable_folds,
        "profitable_fold_pct": round(profitable_folds / len(folds) * 100, 1),
        "overall_out_of_sample": overall,
        "per_fold_net_pnl": per_fold_net_pnl,
        "net_pnl_stdev": round(statistics.pstdev(per_fold_net_pnl), 2) if len(per_fold_net_pnl) >= 2 else None,
        "baseline_buy_and_hold_total_pnl": round(baseline_total, 2),
        "beat_baseline": round(overall["net_pnl"] - baseline_total, 2),
    }
