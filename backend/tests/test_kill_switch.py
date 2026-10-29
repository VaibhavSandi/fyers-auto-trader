"""
Dedicated tests for the Emergency Stop / Kill Switch - the single most
important safety control in the application.
"""
from app.engine import kill_switch
from app.engine.order_manager import OrderManager
from app.engine.position_manager import PositionManager
from app.models import UserSettings, Order, Position, RiskEvent


def test_activate_disables_auto_trading_and_sets_flag(db_session, user_settings):
    result = kill_switch.activate_kill_switch(db_session)
    db_session.refresh(user_settings)
    assert user_settings.kill_switch_active is True
    assert user_settings.auto_trading_enabled is False
    assert result["kill_switch_active"] is True


def test_activate_cancels_pending_orders(db_session, user_settings):
    db_session.add(Order(client_order_id="CO-1", symbol="NSE:A-EQ", side="BUY", quantity=5,
                          price=100, purpose="ENTRY", status="PENDING", mode="paper"))
    db_session.add(Order(client_order_id="CO-2", symbol="NSE:B-EQ", side="BUY", quantity=5,
                          price=100, purpose="ENTRY", status="PLACED", mode="paper"))
    db_session.commit()

    result = kill_switch.activate_kill_switch(db_session)
    assert set(result["cancelled_orders"]) == {"CO-1", "CO-2"}

    orders = db_session.query(Order).all()
    assert all(o.status == "CANCELLED" for o in orders)


def test_activate_reports_open_positions_but_does_not_close_them(db_session, user_settings):
    db_session.add(Position(symbol="NSE:A-EQ", direction="BUY", quantity=10, entry_price=100,
                             stop_loss=95, original_stop_loss=95, target=110, status="OPEN", mode="paper"))
    db_session.commit()

    result = kill_switch.activate_kill_switch(db_session)
    assert len(result["open_positions"]) == 1
    assert result["open_positions"][0]["symbol"] == "NSE:A-EQ"

    # Kill switch alone must NOT close the position - that is a separate action
    position = db_session.query(Position).filter_by(symbol="NSE:A-EQ").first()
    assert position.status == "OPEN"


def test_activate_logs_a_critical_risk_event(db_session, user_settings):
    kill_switch.activate_kill_switch(db_session)
    event = db_session.query(RiskEvent).filter_by(event_type="KILL_SWITCH").order_by(RiskEvent.id.desc()).first()
    assert event.severity == "CRITICAL"


def test_deactivate_clears_flag_but_leaves_auto_trading_off(db_session, user_settings):
    kill_switch.activate_kill_switch(db_session)
    kill_switch.deactivate_kill_switch(db_session)
    db_session.refresh(user_settings)
    assert user_settings.kill_switch_active is False
    assert user_settings.auto_trading_enabled is False  # user must explicitly press Start again


def test_kill_switch_followed_by_explicit_close_all_positions(db_session, user_settings):
    db_session.add(Position(symbol="NSE:A-EQ", direction="BUY", quantity=10, entry_price=100,
                             stop_loss=95, original_stop_loss=95, target=110, current_price=102,
                             status="OPEN", mode="paper"))
    db_session.commit()

    kill_switch.activate_kill_switch(db_session)

    om = OrderManager(db_session, mode="paper")
    pm = PositionManager(db_session, om)
    closed = pm.force_close_all("KILL_SWITCH", price_lookup=lambda s: 102)

    assert len(closed) == 1
    position = db_session.query(Position).filter_by(symbol="NSE:A-EQ").first()
    assert position.status == "CLOSED"
    assert position.exit_reason == "KILL_SWITCH"
