import datetime as dt

from app.learning.scheduler import AutoLearningScheduler
from app.models import Trade, SystemEvent


def _today() -> str:
    return dt.date.today().isoformat()


def test_daily_trade_diagnosis_logs_a_summary_of_todays_real_trades(db_session):
    db_session.add(Trade(date=_today(), symbol="NSE:A-EQ", exit_reason="TARGET",
                          net_pnl=50.0, strategy_score=8, market_condition="BULLISH"))
    db_session.add(Trade(date=_today(), symbol="NSE:B-EQ", exit_reason="STOP_LOSS",
                          net_pnl=-20.0, strategy_score=7, market_condition="NEUTRAL"))
    db_session.commit()

    scheduler = AutoLearningScheduler()
    scheduler._run_daily_trade_diagnosis(db_session)

    event = (
        db_session.query(SystemEvent)
        .filter(SystemEvent.component == "AUTO_LEARNING")
        .order_by(SystemEvent.id.desc())
        .first()
    )
    assert event is not None
    assert "2 trades" in event.message
    assert "1 wins" in event.message
    assert "Rs.30.0" in event.message


def test_daily_trade_diagnosis_handles_no_trades_today_without_error(db_session):
    scheduler = AutoLearningScheduler()
    scheduler._run_daily_trade_diagnosis(db_session)  # must not raise

    event = (
        db_session.query(SystemEvent)
        .filter(SystemEvent.component == "AUTO_LEARNING")
        .order_by(SystemEvent.id.desc())
        .first()
    )
    assert event is not None
    assert "no trades closed today" in event.message.lower()


def test_daily_trade_diagnosis_ignores_trades_from_other_days(db_session):
    db_session.add(Trade(date="2000-01-01", symbol="NSE:OLD-EQ", exit_reason="TARGET",
                          net_pnl=999.0, strategy_score=9, market_condition="BULLISH"))
    db_session.commit()

    scheduler = AutoLearningScheduler()
    scheduler._run_daily_trade_diagnosis(db_session)

    event = (
        db_session.query(SystemEvent)
        .filter(SystemEvent.component == "AUTO_LEARNING")
        .order_by(SystemEvent.id.desc())
        .first()
    )
    assert "no trades closed today" in event.message.lower()
