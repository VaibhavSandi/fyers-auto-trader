"""
Performance dashboard calculations. Risk and drawdown are always returned
alongside P&L - never show profit in isolation.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Trade, DailyStatistics


def today_summary(db: Session, today: str, starting_capital: float) -> dict:
    stats = db.query(DailyStatistics).filter_by(date=today).first()
    if stats is None:
        return {
            "date": today, "starting_capital": starting_capital, "total_trades": 0,
            "winning_trades": 0, "losing_trades": 0, "net_pnl": 0.0, "gross_pnl": 0.0,
            "charges": 0.0, "max_drawdown": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0, "max_consecutive_losses": 0,
            "available_capital": starting_capital,
        }
    return {
        "date": stats.date, "starting_capital": stats.starting_capital, "total_trades": stats.total_trades,
        "winning_trades": stats.winning_trades, "losing_trades": stats.losing_trades,
        "net_pnl": stats.net_pnl, "gross_pnl": stats.gross_pnl, "charges": stats.charges,
        "max_drawdown": stats.max_drawdown, "win_rate": stats.win_rate, "profit_factor": stats.profit_factor,
        "avg_win": stats.avg_win, "avg_loss": stats.avg_loss,
        "max_consecutive_losses": stats.max_consecutive_losses,
        "available_capital": round(stats.starting_capital + stats.net_pnl, 2),
    }


def overall_summary(db: Session) -> dict:
    all_stats = db.query(DailyStatistics).order_by(DailyStatistics.date.asc()).all()
    all_trades = db.query(Trade).all()

    total_trades = len(all_trades)
    wins = [t.net_pnl for t in all_trades if (t.net_pnl or 0) > 0]
    losses = [t.net_pnl for t in all_trades if (t.net_pnl or 0) <= 0]
    net_pnl = round(sum(t.net_pnl or 0 for t in all_trades), 2)

    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in all_trades:
        running += (t.net_pnl or 0)
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0

    return {
        "trading_days": len(all_stats),
        "total_trades": total_trades,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(len(wins) / total_trades * 100, 1) if total_trades else 0.0,
        "net_pnl": net_pnl,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "max_drawdown": round(max_dd, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else (gross_profit if gross_profit else 0.0),
        "daily_pnl_series": [{"date": s.date, "net_pnl": s.net_pnl} for s in all_stats],
    }
