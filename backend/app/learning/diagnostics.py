"""
Step 2 ("Diagnose") of the self-learning loop - surfaces recurring
conditions associated with winning vs losing trades. Purely descriptive:
this groups and counts, it does not conclude or decide anything. Treat
every bucket as a lead to investigate, never as proof - "do not treat
every loss as proof the strategy was wrong" applies here directly: a
single bad bucket on a small sample is noise until re-tested.
"""
from __future__ import annotations

from collections import defaultdict


def diagnose_trades(trades: list) -> dict:
    """trades: objects with .market_regime, .exit_reason, .net_pnl, .strategy_score
    (BacktestTrade or the live Trade model both satisfy this shape)."""
    by_regime = defaultdict(lambda: {"wins": 0, "losses": 0, "net_pnl": 0.0})
    by_exit_reason = defaultdict(lambda: {"wins": 0, "losses": 0, "net_pnl": 0.0})
    by_score_band = defaultdict(lambda: {"wins": 0, "losses": 0, "net_pnl": 0.0})

    for t in trades:
        net_pnl = t.net_pnl or 0.0
        is_win = net_pnl > 0
        score = t.strategy_score if getattr(t, "strategy_score", None) is not None else None
        score_band = f"{(score // 2) * 2}-{(score // 2) * 2 + 1}" if score is not None else "UNKNOWN"

        for bucket_map, key in (
            (by_regime, t.market_regime or "UNKNOWN"),
            (by_exit_reason, t.exit_reason or "UNKNOWN"),
            (by_score_band, score_band),
        ):
            bucket = bucket_map[key]
            bucket["net_pnl"] += net_pnl
            bucket["wins" if is_win else "losses"] += 1

    def _finalize(d: dict) -> dict:
        out = {}
        for k, v in d.items():
            total = v["wins"] + v["losses"]
            out[k] = {
                "wins": v["wins"], "losses": v["losses"], "total": total,
                "win_rate": round(v["wins"] / total * 100, 1) if total else 0.0,
                "net_pnl": round(v["net_pnl"], 2),
            }
        return out

    return {
        "by_market_regime": _finalize(by_regime),
        "by_exit_reason": _finalize(by_exit_reason),
        "by_strategy_score_band": _finalize(by_score_band),
        "total_trades_analyzed": len(trades),
    }
