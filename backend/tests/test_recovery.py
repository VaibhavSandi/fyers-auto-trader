from app.engine.recovery import force_safe_state_on_startup, run_recovery_check
from app.models import UserSettings, Position, SystemEvent


def test_startup_always_forces_auto_trading_off(db_session, user_settings):
    assert user_settings.auto_trading_enabled is True
    force_safe_state_on_startup(db_session)
    db_session.refresh(user_settings)
    assert user_settings.auto_trading_enabled is False


def test_startup_logs_recovery_required_event(db_session, user_settings):
    force_safe_state_on_startup(db_session)
    event = db_session.query(SystemEvent).filter_by(component="ENGINE").order_by(SystemEvent.id.desc()).first()
    assert "RECOVERY CHECK REQUIRED" in event.message


def test_paper_mode_recovery_passes_without_broker(db_session, user_settings):
    report = run_recovery_check(db_session, mode="paper", fyers_client=None)
    assert report["passed"] is True


def test_live_mode_recovery_fails_without_broker_connection(db_session, user_settings):
    report = run_recovery_check(db_session, mode="live", fyers_client=None)
    assert report["passed"] is False
    assert report["checks"]["broker_connection"]["ok"] is False


def test_open_position_without_stop_loss_fails_recovery(db_session, user_settings):
    db_session.add(Position(symbol="NSE:A-EQ", direction="BUY", quantity=10, entry_price=100,
                             stop_loss=None, original_stop_loss=None, target=110, status="OPEN", mode="paper"))
    db_session.commit()
    report = run_recovery_check(db_session, mode="paper", fyers_client=None)
    assert report["passed"] is False
    assert report["checks"]["open_position_protection"]["ok"] is False


def test_recovery_with_protected_open_position_passes(db_session, user_settings):
    db_session.add(Position(symbol="NSE:A-EQ", direction="BUY", quantity=10, entry_price=100,
                             stop_loss=95, original_stop_loss=95, target=110, status="OPEN", mode="paper"))
    db_session.commit()
    report = run_recovery_check(db_session, mode="paper", fyers_client=None)
    assert report["passed"] is True
    assert report["open_positions_recovered"] == 1
