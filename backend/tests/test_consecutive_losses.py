import datetime as dt

from app.engine.risk_engine import RiskEngine
from app.models import DailyStatistics, Trade


def _today():
    return dt.date.today().isoformat()


def _add_trade(db_session, net_pnl):
    db_session.add(Trade(date=_today(), symbol="NSE:X-EQ", direction="BUY", entry_price=100,
                          exit_price=100, quantity=1, net_pnl=net_pnl, gross_pnl=net_pnl, charges=0))
    db_session.commit()


def test_consecutive_losses_pause_trading(db_session, user_settings):
    # conservative profile: max_consecutive_losses = 2
    today = _today()
    db_session.add(DailyStatistics(date=today, starting_capital=user_settings.trading_capital))
    db_session.commit()

    _add_trade(db_session, -10)
    _add_trade(db_session, -10)

    engine = RiskEngine(db_session)
    decision = engine.check_trading_allowed(user_settings, today)
    assert decision.allowed is False
    assert "consecutive losses" in decision.reason.lower()


def test_a_win_resets_the_consecutive_loss_streak(db_session, user_settings):
    today = _today()
    db_session.add(DailyStatistics(date=today, starting_capital=user_settings.trading_capital))
    db_session.commit()

    _add_trade(db_session, -10)
    _add_trade(db_session, +10)

    engine = RiskEngine(db_session)
    assert engine.consecutive_losses(today) == 0


def test_position_size_never_increases_to_recover_a_loss(db_session, user_settings):
    """No martingale: the risk amount offered for the next trade must stay
    identical regardless of how many prior losses occurred, as long as the
    daily loss limit itself hasn't been breached."""
    today = _today()
    db_session.add(DailyStatistics(date=today, starting_capital=user_settings.trading_capital))
    db_session.commit()

    engine = RiskEngine(db_session)
    decision_before = engine.check_trading_allowed(user_settings, today)

    _add_trade(db_session, -10)

    decision_after = engine.check_trading_allowed(user_settings, today)
    assert decision_after.max_risk_amount == decision_before.max_risk_amount
