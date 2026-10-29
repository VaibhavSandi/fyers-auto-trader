from app.engine.order_manager import OrderManager
from app.engine.position_manager import PositionManager
from app.engine.risk_engine import RiskEngine
from app.models import Position


def test_time_based_exit_forces_a_close_regardless_of_price(db_session, user_settings):
    db_session.add(Position(symbol="NSE:A-EQ", direction="BUY", quantity=10, entry_price=100,
                             stop_loss=95, original_stop_loss=95, target=110, current_price=103,
                             status="OPEN", mode="paper"))
    db_session.commit()

    om = OrderManager(db_session, mode="paper")
    pm = PositionManager(db_session, om)
    position = db_session.query(Position).filter_by(symbol="NSE:A-EQ").first()

    reason = pm.update_price_and_check_exit(position, current_price=103, atr_value=1.0, force_time_exit=True)

    assert reason == "EOD_SQUAREOFF"
    db_session.refresh(position)
    assert position.status == "CLOSED"
    assert position.exit_reason == "EOD_SQUAREOFF"


def test_square_off_time_detection(db_session, monkeypatch):
    import app.config as config_module
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("SQUARE_OFF_TIME", "00:00")
    config_module.get_settings.cache_clear()

    engine = RiskEngine(db_session)
    assert engine.past_square_off_time() is True

    monkeypatch.setenv("SQUARE_OFF_TIME", "23:59")
    config_module.get_settings.cache_clear()


def test_no_new_entries_allowed_past_entry_cutoff(db_session, user_settings, monkeypatch):
    import app.config as config_module
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("ENTRY_CUTOFF_TIME", "00:00")
    config_module.get_settings.cache_clear()

    engine = RiskEngine(db_session)
    decision = engine.check_trading_allowed(user_settings, "2024-01-01")
    assert decision.allowed is False
    assert "cutoff" in decision.reason.lower()

    monkeypatch.setenv("ENTRY_CUTOFF_TIME", "23:58")
    config_module.get_settings.cache_clear()


def test_no_new_entries_during_the_opening_volatility_window(db_session, user_settings, monkeypatch):
    """No entries before ENTRY_START_TIME (default 09:30) - the opening
    minutes are too volatile/noisy to trust (standard intraday practice)."""
    import app.config as config_module
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("ENTRY_START_TIME", "23:59")  # "now" is always before this -> always blocked
    config_module.get_settings.cache_clear()

    engine = RiskEngine(db_session)
    decision = engine.check_trading_allowed(user_settings, "2024-01-01")
    assert decision.allowed is False
    assert "settle" in decision.reason.lower()

    monkeypatch.setenv("ENTRY_START_TIME", "00:00")
    config_module.get_settings.cache_clear()


def test_entries_allowed_once_past_the_opening_window(db_session, user_settings, monkeypatch):
    import app.config as config_module
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("ENTRY_START_TIME", "00:00")  # "now" is always past this -> never blocked by it
    config_module.get_settings.cache_clear()

    engine = RiskEngine(db_session)
    decision = engine.check_trading_allowed(user_settings, "2024-01-01")
    assert decision.allowed is True

    monkeypatch.setenv("ENTRY_START_TIME", "00:00")
    config_module.get_settings.cache_clear()
