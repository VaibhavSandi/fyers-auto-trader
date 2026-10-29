"""Trade journal query helpers."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Trade


def list_trades(db: Session, limit: int = 200, date: str | None = None) -> list[Trade]:
    q = db.query(Trade).order_by(Trade.id.desc())
    if date:
        q = q.filter(Trade.date == date)
    return q.limit(limit).all()


def trade_to_dict(t: Trade) -> dict:
    return {
        "id": t.id, "date": t.date, "time_entry": t.time_entry, "time_exit": t.time_exit,
        "symbol": t.symbol, "direction": t.direction, "entry_price": t.entry_price,
        "exit_price": t.exit_price, "quantity": t.quantity, "stop_loss": t.stop_loss,
        "target": t.target, "exit_reason": t.exit_reason, "gross_pnl": t.gross_pnl,
        "charges": t.charges, "net_pnl": t.net_pnl, "risk_amount": t.risk_amount,
        "reward_amount": t.reward_amount, "risk_reward": t.risk_reward,
        "strategy_score": t.strategy_score, "market_condition": t.market_condition,
        "mode": t.mode, "explanation": t.explanation,
    }
