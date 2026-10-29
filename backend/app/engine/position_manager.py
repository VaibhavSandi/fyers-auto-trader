"""
Position Manager - monitors every open position on each engine tick and
decides whether it must be exited: stop-loss hit, target hit, trailing stop
hit, time-based exit, or setup invalidation. Also drives the trailing-stop
update and keeps the trade journal / daily statistics in sync the moment a
position closes.
"""
from __future__ import annotations

import logging
import datetime as dt

from sqlalchemy.orm import Session

from app.models import Position, Trade, DailyStatistics, Signal
from app.engine.order_manager import OrderManager
from app.engine.trailing_stop import update_trailing_stop

logger = logging.getLogger(__name__)


class PositionManager:
    def __init__(self, db: Session, order_manager: OrderManager):
        self.db = db
        self.order_manager = order_manager

    def get_open_positions(self) -> list[Position]:
        return self.db.query(Position).filter(Position.status == "OPEN").all()

    def update_price_and_check_exit(self, position: Position, current_price: float, atr_value: float | None,
                                     force_time_exit: bool = False) -> str | None:
        """Returns the exit reason if the position should be (and was) closed, else None."""
        position.current_price = current_price
        self.db.commit()

        if force_time_exit:
            self._exit(position, current_price, "EOD_SQUAREOFF")
            return "EOD_SQUAREOFF"

        trail = update_trailing_stop(
            direction=position.direction, entry_price=position.entry_price,
            original_stop_loss=position.original_stop_loss, current_stop_loss=position.stop_loss,
            current_price=current_price, atr_value=atr_value,
        )
        if trail.moved:
            position.stop_loss = trail.new_stop_loss
            position.trailing_active = True
            self.db.commit()
            logger.info("Trailing stop for %s moved to %.2f", position.symbol, trail.new_stop_loss)

        if position.direction == "BUY":
            if current_price <= position.stop_loss:
                reason = "TRAILING_STOP" if position.trailing_active and position.stop_loss > position.original_stop_loss else "STOP_LOSS"
                self._exit(position, current_price, reason)
                return reason
            if current_price >= position.target:
                self._exit(position, current_price, "TARGET")
                return "TARGET"
        else:
            if current_price >= position.stop_loss:
                reason = "TRAILING_STOP" if position.trailing_active and position.stop_loss < position.original_stop_loss else "STOP_LOSS"
                self._exit(position, current_price, reason)
                return reason
            if current_price <= position.target:
                self._exit(position, current_price, "TARGET")
                return "TARGET"

        return None

    def force_close_all(self, reason: str, price_lookup) -> list[Position]:
        """price_lookup: callable(symbol) -> float. Used by the kill switch /
        close-all-positions control and the mandatory EOD square-off."""
        closed = []
        for position in self.get_open_positions():
            price = price_lookup(position.symbol) or position.current_price or position.entry_price
            self._exit(position, price, reason)
            closed.append(position)
        return closed

    def _exit(self, position: Position, reference_price: float, reason: str) -> None:
        self.order_manager.place_exit(position=position, reference_price=reference_price, reason=reason)
        self.db.refresh(position)
        if position.status == "CLOSED":
            self._record_journal(position, reason)

    def _record_journal(self, position: Position, reason: str) -> None:
        signal = self.db.query(Signal).filter(Signal.id == position.signal_id).first() if position.signal_id else None
        today = position.closed_at.strftime("%Y-%m-%d") if position.closed_at else dt.date.today().isoformat()

        risk_amount = abs(position.entry_price - position.original_stop_loss) * position.quantity
        reward_amount = abs(position.target - position.entry_price) * position.quantity

        trade = Trade(
            position_id=position.id, date=today,
            time_entry=position.opened_at.strftime("%H:%M:%S") if position.opened_at else "",
            time_exit=position.closed_at.strftime("%H:%M:%S") if position.closed_at else "",
            symbol=position.symbol, direction=position.direction, entry_price=position.entry_price,
            exit_price=position.exit_price, quantity=position.quantity, stop_loss=position.original_stop_loss,
            target=position.target, exit_reason=reason, gross_pnl=position.gross_pnl, charges=position.charges,
            net_pnl=position.net_pnl, risk_amount=round(risk_amount, 2), reward_amount=round(reward_amount, 2),
            risk_reward=round(reward_amount / risk_amount, 2) if risk_amount else None,
            strategy_score=signal.score if signal else None,
            market_condition=signal.market_regime if signal else None,
            mode=position.mode,
            explanation=(signal.reasons if signal else []),
        )
        self.db.add(trade)
        self.db.commit()
        self._update_daily_statistics(today, trade)

    def _update_daily_statistics(self, today: str, trade: Trade) -> None:
        from app.engine.risk_engine import RiskEngine

        stats = self.db.query(DailyStatistics).filter_by(date=today).first()
        if stats is None:
            risk_engine = RiskEngine(self.db)
            from app.models import UserSettings
            user_settings = self.db.query(UserSettings).first()
            starting_capital = user_settings.trading_capital if user_settings else 0.0
            stats = DailyStatistics(date=today, starting_capital=starting_capital)
            self.db.add(stats)

        all_trades = self.db.query(Trade).filter(Trade.date == today).all()
        stats.total_trades = len(all_trades)
        stats.winning_trades = sum(1 for t in all_trades if (t.net_pnl or 0) > 0)
        stats.losing_trades = sum(1 for t in all_trades if (t.net_pnl or 0) <= 0)
        stats.gross_pnl = round(sum(t.gross_pnl or 0 for t in all_trades), 2)
        stats.charges = round(sum(t.charges or 0 for t in all_trades), 2)
        stats.net_pnl = round(sum(t.net_pnl or 0 for t in all_trades), 2)
        stats.win_rate = round(stats.winning_trades / stats.total_trades * 100, 1) if stats.total_trades else 0.0

        wins = [t.net_pnl for t in all_trades if (t.net_pnl or 0) > 0]
        losses = [t.net_pnl for t in all_trades if (t.net_pnl or 0) <= 0]
        stats.avg_win = round(sum(wins) / len(wins), 2) if wins else 0.0
        stats.avg_loss = round(sum(losses) / len(losses), 2) if losses else 0.0
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        stats.profit_factor = round(gross_profit / gross_loss, 2) if gross_loss else (gross_profit if gross_profit else 0.0)

        running = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in all_trades:
            running += (t.net_pnl or 0)
            peak = max(peak, running)
            max_dd = max(max_dd, peak - running)
        stats.max_drawdown = round(max_dd, 2)

        streak = 0
        max_streak = 0
        for t in all_trades:
            if (t.net_pnl or 0) < 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
        stats.max_consecutive_losses = max_streak

        self.db.commit()
