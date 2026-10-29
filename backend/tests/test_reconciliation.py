from app.engine.reconciliation import reconcile
from app.models import Position, RiskEvent, SystemEvent


class FakeBrokerClient:
    def __init__(self, positions):
        self._positions = positions

    def get_positions(self):
        return self._positions


def test_matching_state_is_healthy(db_session):
    db_session.add(Position(symbol="NSE:A-EQ", direction="BUY", quantity=10, entry_price=100,
                             stop_loss=95, original_stop_loss=95, target=110, status="OPEN", mode="live"))
    db_session.commit()
    client = FakeBrokerClient([{"symbol": "NSE:A-EQ", "qty": 10}])
    result = reconcile(db_session, client)
    assert result["healthy"] is True
    assert result["mismatches"] == []


def test_quantity_mismatch_is_corrected_to_broker_value(db_session):
    pos = Position(symbol="NSE:A-EQ", direction="BUY", quantity=10, entry_price=100,
                    stop_loss=95, original_stop_loss=95, target=110, status="OPEN", mode="live")
    db_session.add(pos)
    db_session.commit()
    client = FakeBrokerClient([{"symbol": "NSE:A-EQ", "qty": 7}])
    result = reconcile(db_session, client)
    db_session.refresh(pos)
    assert pos.quantity == 7
    assert len(result["mismatches"]) == 1


def test_locally_open_but_broker_flat_is_closed_locally(db_session):
    pos = Position(symbol="NSE:A-EQ", direction="BUY", quantity=10, entry_price=100,
                    stop_loss=95, original_stop_loss=95, target=110, status="OPEN", mode="live")
    db_session.add(pos)
    db_session.commit()
    client = FakeBrokerClient([])
    reconcile(db_session, client)
    db_session.refresh(pos)
    assert pos.status == "CLOSED"


def test_unknown_broker_position_marks_position_sync_down(db_session):
    client = FakeBrokerClient([{"symbol": "NSE:UNKNOWN-EQ", "qty": 5}])
    result = reconcile(db_session, client)
    assert result["healthy"] is False
    assert "NSE:UNKNOWN-EQ" in result["unknown_broker_positions"]

    health = db_session.query(SystemEvent).filter_by(component="POSITION_SYNC").order_by(SystemEvent.id.desc()).first()
    assert health.status == "DOWN"

    critical_events = db_session.query(RiskEvent).filter_by(event_type="RECONCILIATION_UNKNOWN_POSITION").all()
    assert len(critical_events) == 1
    assert critical_events[0].severity == "CRITICAL"
