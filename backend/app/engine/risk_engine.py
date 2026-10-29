"""
The Risk Engine - the single gatekeeper between a strategy signal and an
actual order. Nothing reaches the Order Manager without passing through
here. This module enforces every hard safety rule in the spec:

  - Daily capital protection (max daily loss -> stop new trades)
  - Consecutive loss protection (pause auto trading)
  - No martingale / no revenge trading (risk amount is fixed from the
    DAY'S STARTING capital, never recalculated upward intraday)
  - Max trades per day / max simultaneous positions
  - Entry cutoff / mandatory square-off time windows
  - System health gating (never trade if a critical component is down)
  - Duplicate-position protection (never pyramid into the same symbol)

If anything is uncertain, the engine's default is to block the trade.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import UserSettings, Position, Trade, RiskEvent, SystemEvent


MAX_ACCOUNT_DRAWDOWN_PCT = 10.0  # hard circuit breaker, independent of (and on top of) the daily loss limit


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""
    max_risk_amount: float = 0.0
    details: dict = field(default_factory=dict)


def _time_now() -> dt.time:
    return dt.datetime.now().time()


def _parse_time(value: str) -> dt.time:
    h, m = value.split(":")
    return dt.time(int(h), int(m))


def log_risk_event(db: Session, event_type: str, message: str, severity: str = "INFO", details: dict | None = None) -> None:
    db.add(RiskEvent(event_type=event_type, severity=severity, message=message, details=details or {}))
    db.commit()


class RiskEngine:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    # ---- global gating --------------------------------------------------

    def day_start_capital(self, user_settings: UserSettings, today: str) -> float:
        """The capital base used for ALL risk math today. Fixed at the start of
        the day so intraday gains/losses never cause position sizes to grow
        (which would be a disguised martingale)."""
        from app.models import DailyStatistics
        row = self.db.query(DailyStatistics).filter_by(date=today).first()
        if row and row.starting_capital:
            return row.starting_capital
        return user_settings.trading_capital

    def todays_closed_trades(self, today: str) -> list[Trade]:
        return self.db.query(Trade).filter(Trade.date == today).order_by(Trade.id.asc()).all()

    def todays_net_pnl(self, today: str) -> float:
        return sum(t.net_pnl or 0 for t in self.todays_closed_trades(today))

    def open_positions_count(self) -> int:
        return self.db.query(Position).filter(Position.status.in_(["OPEN", "CLOSING"])).count()

    def has_open_position(self, symbol: str) -> bool:
        return self.db.query(Position).filter(
            Position.symbol == symbol, Position.status.in_(["OPEN", "CLOSING"])
        ).first() is not None

    def consecutive_losses(self, today: str) -> int:
        trades = self.todays_closed_trades(today)
        streak = 0
        for t in reversed(trades):
            if (t.net_pnl or 0) < 0:
                streak += 1
            else:
                break
        return streak

    def current_drawdown_from_peak_pct(self, user_settings: UserSettings) -> float:
        """How far current equity sits below the account's ALL-TIME peak
        equity (not just today's) - the Phase 9 account-level circuit
        breaker, distinct from the daily loss limit. Walks every closed
        trade ever recorded, in order, tracking the running peak."""
        trades = self.db.query(Trade).order_by(Trade.id.asc()).all()
        equity = user_settings.trading_capital
        peak = equity
        for t in trades:
            equity += (t.net_pnl or 0)
            peak = max(peak, equity)
        if peak <= 0:
            return 0.0
        return round((peak - equity) / peak * 100, 2)

    # Statuses that must block new trades. FYERS_API/LIVE_DATA report the
    # richer CONNECTED/DEGRADED/RATE_LIMITED/STALE_DATA/DISCONNECTED
    # vocabulary; everything else still uses plain HEALTHY/DOWN. DEGRADED is
    # intentionally non-blocking (a soft warning, e.g. one open position's
    # price briefly unavailable) - new trades only stop for a genuinely
    # unusable connection: down, disconnected, rate-limited, or stale data.
    BLOCKING_STATUSES = {"DOWN", "DISCONNECTED", "RATE_LIMITED", "STALE_DATA"}

    def system_health_ok(self) -> tuple[bool, str]:
        """Checks the most recent status row per critical component."""
        critical_components = ["FYERS_API", "LIVE_DATA", "DATABASE", "RISK_ENGINE", "ORDER_MANAGER", "POSITION_SYNC"]
        for comp in critical_components:
            row = (
                self.db.query(SystemEvent)
                .filter(SystemEvent.component == comp)
                .order_by(SystemEvent.id.desc())
                .first()
            )
            if row is None:
                continue
            if row.status in self.BLOCKING_STATUSES:
                return False, f"{comp} is {row.status}: {row.message}"
        return True, "ok"

    def within_entry_window(self) -> tuple[bool, str]:
        now = _time_now()
        open_t = _parse_time(self.settings.MARKET_OPEN_TIME)
        entry_start_t = _parse_time(self.settings.ENTRY_START_TIME)
        cutoff_t = _parse_time(self.settings.ENTRY_CUTOFF_TIME)
        if now < open_t:
            return False, "Market has not opened yet"
        if now < entry_start_t:
            return False, (f"Waiting for the market to settle until {self.settings.ENTRY_START_TIME} before "
                            f"taking any trade - the opening minutes are typically too volatile/noisy to trust")
        if now >= cutoff_t:
            return False, f"Past entry cutoff time ({self.settings.ENTRY_CUTOFF_TIME}) - no new entries today"
        return True, "ok"

    def past_square_off_time(self) -> bool:
        return _time_now() >= _parse_time(self.settings.SQUARE_OFF_TIME)

    def check_trading_allowed(self, user_settings: UserSettings, today: str) -> RiskDecision:
        """The master pre-trade gate. Call before evaluating/placing ANY new entry."""
        if user_settings.kill_switch_active:
            return RiskDecision(False, "Emergency stop is active")

        if not user_settings.auto_trading_enabled:
            return RiskDecision(False, "Auto trading is not enabled")

        healthy, msg = self.system_health_ok()
        if not healthy:
            return RiskDecision(False, f"System health check failed: {msg}")

        drawdown_pct = self.current_drawdown_from_peak_pct(user_settings)
        if drawdown_pct >= MAX_ACCOUNT_DRAWDOWN_PCT:
            log_risk_event(
                self.db, "MAX_DRAWDOWN_BREACHED",
                f"Account drawdown {drawdown_pct:.1f}% from its all-time peak equity has reached the "
                f"{MAX_ACCOUNT_DRAWDOWN_PCT}% circuit breaker - trading stopped",
                severity="CRITICAL",
            )
            return RiskDecision(
                False, f"Maximum account drawdown ({MAX_ACCOUNT_DRAWDOWN_PCT}%) breached - trading stopped "
                       f"until manually reviewed and auto trading is re-enabled"
            )

        in_window, msg = self.within_entry_window()
        if not in_window:
            return RiskDecision(False, msg)

        if self.past_square_off_time():
            return RiskDecision(False, "Past mandatory square-off time")

        day_capital = self.day_start_capital(user_settings, today)
        net_pnl = self.todays_net_pnl(today)
        max_daily_loss_amount = day_capital * user_settings.max_daily_loss_pct / 100
        if net_pnl <= -max_daily_loss_amount:
            log_risk_event(
                self.db, "DAILY_LOSS_LIMIT",
                f"Daily loss limit reached: net P&L ₹{net_pnl:.2f} <= -₹{max_daily_loss_amount:.2f}",
                severity="CRITICAL",
            )
            return RiskDecision(False, "Daily loss limit reached - new trades stopped for today")

        streak = self.consecutive_losses(today)
        if streak >= user_settings.max_consecutive_losses:
            log_risk_event(
                self.db, "CONSECUTIVE_LOSSES",
                f"{streak} consecutive losses reached (limit {user_settings.max_consecutive_losses})",
                severity="WARNING",
            )
            return RiskDecision(False, f"{streak} consecutive losses - auto trading paused for today")

        trades_today = len(self.todays_closed_trades(today)) + self.open_positions_count()
        if trades_today >= user_settings.max_trades_per_day:
            return RiskDecision(False, f"Maximum trades for today reached ({user_settings.max_trades_per_day})")

        if self.open_positions_count() >= user_settings.max_open_positions:
            return RiskDecision(False, f"Maximum simultaneous positions reached ({user_settings.max_open_positions})")

        max_risk_amount = min(
            day_capital * user_settings.max_risk_per_trade_pct / 100,
            day_capital * self.settings.HARD_MAX_RISK_PER_TRADE_PCT / 100,
        )
        return RiskDecision(True, "ok", max_risk_amount=max_risk_amount, details={"day_start_capital": day_capital})

    # ---- per-signal validation -------------------------------------------

    def validate_setup(self, symbol: str, risk_reward: float, min_risk_reward: float) -> RiskDecision:
        if self.has_open_position(symbol):
            return RiskDecision(False, f"Already have an open position in {symbol} - no pyramiding")
        if risk_reward < min_risk_reward:
            return RiskDecision(False, f"Risk/reward {risk_reward:.2f}:1 below minimum {min_risk_reward}:1")
        return RiskDecision(True, "ok")

    def validate_order_hard_limits(self, *, risk_amount: float, day_start_capital: float) -> RiskDecision:
        """Final absolute-ceiling check right before an order is sent. This can
        never be bypassed by any profile or UI setting."""
        hard_cap = day_start_capital * self.settings.HARD_MAX_RISK_PER_TRADE_PCT / 100
        if risk_amount > hard_cap + 0.01:
            return RiskDecision(False, f"Computed risk ₹{risk_amount:.2f} exceeds hard ceiling ₹{hard_cap:.2f}")
        return RiskDecision(True, "ok")
