import datetime as dt

from app.engine.risk_engine import RiskEngine
from app.models import DailyStatistics, Trade


def _today():
    return dt.date.today().isoformat()


def _add_trade(db_session, net_pnl, date=None):
    db_session.add(Trade(date=date or _today(), symbol="NSE:X-EQ", direction="BUY", entry_price=100,
                          exit_price=100, quantity=1, net_pnl=net_pnl, gross_pnl=net_pnl, charges=0))
    db_session.commit()


def test_daily_loss_limit_stops_new_trades(db_session, user_settings):
    today = _today()
    db_session.add(DailyStatistics(date=today, starting_capital=user_settings.trading_capital))
    db_session.commit()

    # Conservative profile: 1.5% of 10000 = 150
    _add_trade(db_session, -160)

    engine = RiskEngine(db_session)
    decision = engine.check_trading_allowed(user_settings, today)
    assert decision.allowed is False
    assert "daily loss" in decision.reason.lower()


def test_small_loss_within_limit_still_allows_trading(db_session, user_settings):
    today = _today()
    db_session.add(DailyStatistics(date=today, starting_capital=user_settings.trading_capital))
    db_session.commit()

    _add_trade(db_session, -50)  # well within the 150 limit

    engine = RiskEngine(db_session)
    decision = engine.check_trading_allowed(user_settings, today)
    assert decision.allowed is True


def test_risk_calculations_use_fixed_day_start_capital_not_live_equity(db_session, user_settings):
    """Prevents a hidden martingale: a big intraday win must not inflate the
    risk base used for the NEXT trade's position sizing."""
    today = _today()
    db_session.add(DailyStatistics(date=today, starting_capital=user_settings.trading_capital))
    db_session.commit()

    _add_trade(db_session, +500)  # a big win

    engine = RiskEngine(db_session)
    decision = engine.check_trading_allowed(user_settings, today)
    day_capital = decision.details["day_start_capital"]
    assert day_capital == user_settings.trading_capital  # unchanged by the win
