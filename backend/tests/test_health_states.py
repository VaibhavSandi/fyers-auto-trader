from app.engine.risk_engine import RiskEngine
from app.models import SystemEvent


def _set_health(db_session, component, status, message=""):
    db_session.add(SystemEvent(component=component, status=status, message=message))
    db_session.commit()


def test_connected_status_does_not_block_trading(db_session, user_settings):
    _set_health(db_session, "LIVE_DATA", "CONNECTED")
    engine = RiskEngine(db_session)
    ok, _ = engine.system_health_ok()
    assert ok is True


def test_stale_data_blocks_new_trades(db_session, user_settings):
    _set_health(db_session, "LIVE_DATA", "STALE_DATA", "No ticks received recently")
    engine = RiskEngine(db_session)
    ok, reason = engine.system_health_ok()
    assert ok is False
    assert "LIVE_DATA" in reason


def test_disconnected_blocks_new_trades(db_session, user_settings):
    _set_health(db_session, "FYERS_API", "DISCONNECTED", "Not connected to FYERS")
    engine = RiskEngine(db_session)
    ok, reason = engine.system_health_ok()
    assert ok is False
    assert "FYERS_API" in reason


def test_rate_limited_blocks_new_trades(db_session, user_settings):
    _set_health(db_session, "FYERS_API", "RATE_LIMITED", "Backing off after a rate-limit response")
    engine = RiskEngine(db_session)
    ok, reason = engine.system_health_ok()
    assert ok is False
    assert "RATE_LIMITED" in reason


def test_degraded_does_not_block_trading():
    """DEGRADED is a soft warning (e.g. one open position's price briefly
    unavailable), not a reason to stop looking for new trades entirely."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        _set_health(db, "LIVE_DATA", "DEGRADED", "No recent price for one open position")
        engine = RiskEngine(db)
        ok, _ = engine.system_health_ok()
        assert ok is True
    finally:
        db.close()


def test_a_healed_status_unblocks_trading_on_the_next_check(db_session, user_settings):
    engine = RiskEngine(db_session)
    _set_health(db_session, "LIVE_DATA", "DISCONNECTED", "socket down")
    assert engine.system_health_ok()[0] is False

    _set_health(db_session, "LIVE_DATA", "CONNECTED", "reconnected")
    assert engine.system_health_ok()[0] is True


def test_check_trading_allowed_surfaces_the_blocking_reason(db_session, user_settings):
    _set_health(db_session, "LIVE_DATA", "STALE_DATA", "feed stale")
    engine = RiskEngine(db_session)
    import datetime as dt
    decision = engine.check_trading_allowed(user_settings, dt.date.today().isoformat())
    assert decision.allowed is False
    assert "STALE_DATA" in decision.reason
