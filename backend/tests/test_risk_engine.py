import datetime as dt

from app.engine.risk_engine import RiskEngine, MAX_ACCOUNT_DRAWDOWN_PCT
from app.models import DailyStatistics, Position, Trade


def _today():
    return dt.date.today().isoformat()


def _add_closed_trade(db_session, net_pnl, date=None):
    db_session.add(Trade(date=date or _today(), symbol="NSE:X-EQ", direction="BUY", entry_price=100,
                          exit_price=100, quantity=1, net_pnl=net_pnl, gross_pnl=net_pnl, charges=0))
    db_session.commit()


def test_trading_allowed_when_everything_is_fine(db_session, user_settings):
    engine = RiskEngine(db_session)
    decision = engine.check_trading_allowed(user_settings, _today())
    assert decision.allowed is True
    assert decision.max_risk_amount > 0


def test_blocked_when_kill_switch_active(db_session, user_settings):
    user_settings.kill_switch_active = True
    db_session.commit()
    engine = RiskEngine(db_session)
    decision = engine.check_trading_allowed(user_settings, _today())
    assert decision.allowed is False
    assert "emergency" in decision.reason.lower()


def test_blocked_when_auto_trading_disabled(db_session, user_settings):
    user_settings.auto_trading_enabled = False
    db_session.commit()
    engine = RiskEngine(db_session)
    decision = engine.check_trading_allowed(user_settings, _today())
    assert decision.allowed is False


def test_max_risk_amount_never_exceeds_hard_ceiling(db_session, user_settings):
    user_settings.max_risk_per_trade_pct = 50  # an absurd override attempt
    db_session.commit()
    engine = RiskEngine(db_session)
    decision = engine.check_trading_allowed(user_settings, _today())
    from app.config import get_settings
    hard_cap = user_settings.trading_capital * get_settings().HARD_MAX_RISK_PER_TRADE_PCT / 100
    assert decision.max_risk_amount <= hard_cap + 0.01


def test_duplicate_position_in_same_symbol_is_blocked(db_session, user_settings):
    db_session.add(Position(symbol="NSE:RELIANCE-EQ", direction="BUY", quantity=5, entry_price=100,
                             stop_loss=95, original_stop_loss=95, target=110, status="OPEN", mode="paper"))
    db_session.commit()
    engine = RiskEngine(db_session)
    assert engine.has_open_position("NSE:RELIANCE-EQ") is True
    decision = engine.validate_setup("NSE:RELIANCE-EQ", risk_reward=2.0, min_risk_reward=1.5)
    assert decision.allowed is False


def test_max_open_positions_limit_enforced(db_session, user_settings):
    user_settings.max_open_positions = 1
    db_session.commit()
    db_session.add(Position(symbol="NSE:A-EQ", direction="BUY", quantity=5, entry_price=100,
                             stop_loss=95, original_stop_loss=95, target=110, status="OPEN", mode="paper"))
    db_session.commit()
    engine = RiskEngine(db_session)
    decision = engine.check_trading_allowed(user_settings, _today())
    assert decision.allowed is False
    assert "position" in decision.reason.lower()


def test_no_drawdown_with_no_trades_yet(db_session, user_settings):
    engine = RiskEngine(db_session)
    assert engine.current_drawdown_from_peak_pct(user_settings) == 0.0


def test_drawdown_computed_from_all_time_peak_not_just_today(db_session, user_settings):
    # capital 10000 -> a win takes equity/peak to 11000, then losses bring
    # equity down to 10500: drawdown is relative to the 11000 peak, not the
    # original 10000 starting capital
    _add_closed_trade(db_session, 1000)
    _add_closed_trade(db_session, -500)
    engine = RiskEngine(db_session)
    dd = engine.current_drawdown_from_peak_pct(user_settings)
    assert dd == round(500 / 11000 * 100, 2)


def test_max_drawdown_circuit_breaker_stops_trading(db_session, user_settings):
    # conservative profile, capital 10000 - a big enough loss alone crosses
    # the account-level 10% circuit breaker (independent of the daily loss limit)
    _add_closed_trade(db_session, -(10000 * MAX_ACCOUNT_DRAWDOWN_PCT / 100 + 50))
    engine = RiskEngine(db_session)
    decision = engine.check_trading_allowed(user_settings, _today())
    assert decision.allowed is False
    assert "drawdown" in decision.reason.lower()


def test_small_drawdown_does_not_trip_the_circuit_breaker(db_session, user_settings):
    _add_closed_trade(db_session, -50)  # well under the 10% circuit breaker
    engine = RiskEngine(db_session)
    decision = engine.check_trading_allowed(user_settings, _today())
    assert decision.allowed is True


def test_drawdown_breach_logs_a_critical_risk_event(db_session, user_settings):
    from app.models import RiskEvent
    _add_closed_trade(db_session, -(10000 * MAX_ACCOUNT_DRAWDOWN_PCT / 100 + 50))
    engine = RiskEngine(db_session)
    engine.check_trading_allowed(user_settings, _today())
    event = db_session.query(RiskEvent).filter_by(event_type="MAX_DRAWDOWN_BREACHED").first()
    assert event is not None
    assert event.severity == "CRITICAL"
