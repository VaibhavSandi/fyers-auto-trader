import pytest

from app.engine.order_manager import OrderManager, OrderManagerError
from app.models import Position, Order


class FakeFyersClient:
    """Minimal stand-in for FyersClient used to drive order-manager behaviour
    deterministically in tests, without any network access."""

    def __init__(self, orderbook_sequence):
        self._next_id = 1
        self._orderbook_sequence = list(orderbook_sequence)  # list of orderbook snapshots to return in sequence
        self.placed_orders = []
        self.cancelled = []

    def place_order(self, **kwargs):
        order_id = str(self._next_id)
        self._next_id += 1
        self.placed_orders.append({"id": order_id, **kwargs})
        return {"s": "ok", "id": order_id}

    def get_orderbook(self):
        if self._orderbook_sequence:
            return self._orderbook_sequence.pop(0)
        return []

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        return {"s": "ok"}


def test_paper_entry_fills_immediately(db_session):
    om = OrderManager(db_session, mode="paper")
    order, position = om.place_entry(
        symbol="NSE:TEST-EQ", direction="BUY", quantity=10, reference_price=100,
        stop_loss=95, target=115, signal_id=None,
    )
    assert order.status == "FILLED"
    assert position is not None
    assert position.quantity == 10
    assert position.status == "OPEN"


def test_duplicate_entry_for_same_symbol_is_refused(db_session):
    om = OrderManager(db_session, mode="paper")
    om.place_entry(symbol="NSE:DUP-EQ", direction="BUY", quantity=10, reference_price=100,
                    stop_loss=95, target=115, signal_id=None)
    with pytest.raises(OrderManagerError):
        om.place_entry(symbol="NSE:DUP-EQ", direction="BUY", quantity=5, reference_price=101,
                        stop_loss=96, target=110, signal_id=None)


def test_live_order_rejection_does_not_create_a_position(db_session):
    fake = FakeFyersClient(orderbook_sequence=[
        [{"id": "1", "status": 5, "message": "insufficient margin"}],
    ])
    om = OrderManager(db_session, mode="live", fyers_client=fake)
    order, position = om.place_entry(symbol="NSE:REJ-EQ", direction="BUY", quantity=10,
                                       reference_price=100, stop_loss=95, target=115, signal_id=None)
    assert order.status == "REJECTED"
    assert position is None


def test_live_partial_fill_creates_position_sized_to_filled_quantity(db_session):
    fake = FakeFyersClient(orderbook_sequence=[
        [{"id": "1", "status": 2, "filledQty": 6, "tradedPrice": 100.5}],
    ])
    om = OrderManager(db_session, mode="live", fyers_client=fake)
    order, position = om.place_entry(symbol="NSE:PARTIAL-EQ", direction="BUY", quantity=10,
                                      reference_price=100, stop_loss=95, target=115, signal_id=None)
    assert order.status == "PARTIAL"
    assert position is not None
    assert position.quantity == 6


def test_unconfirmed_fill_never_assumes_success(db_session, monkeypatch):
    import app.engine.order_manager as om_module
    monkeypatch.setattr(om_module, "FILL_CONFIRM_DELAY_SEC", 0.01)
    fake = FakeFyersClient(orderbook_sequence=[])  # broker never returns the order in the book
    om = OrderManager(db_session, mode="live", fyers_client=fake)
    order, position = om.place_entry(symbol="NSE:UNSURE-EQ", direction="BUY", quantity=10,
                                      reference_price=100, stop_loss=95, target=115, signal_id=None)
    assert order.status == "UNCONFIRMED"
    assert position is None


def test_live_mode_requires_a_connected_client():
    import pytest as _pytest
    from sqlalchemy.orm import Session
    with _pytest.raises(OrderManagerError):
        OrderManager(db=None, mode="live", fyers_client=None)


# ---- Phase 7: liquidity-aware paper fills -----------------------------------

def test_paper_entry_with_no_volume_context_fills_fully_as_before(db_session):
    om = OrderManager(db_session, mode="paper")
    order, position = om.place_entry(
        symbol="NSE:TEST-EQ", direction="BUY", quantity=1000, reference_price=100,
        stop_loss=95, target=115, signal_id=None,  # avg_bar_volume omitted entirely
    )
    assert order.status == "FILLED"
    assert position.quantity == 1000


def test_paper_entry_partially_fills_when_order_is_large_relative_to_volume(db_session):
    om = OrderManager(db_session, mode="paper")
    # quantity is 15% of avg_bar_volume - between the partial and reject thresholds
    order, position = om.place_entry(
        symbol="NSE:TEST-EQ", direction="BUY", quantity=1500, reference_price=100,
        stop_loss=95, target=115, signal_id=None, avg_bar_volume=10_000,
    )
    assert order.status == "PARTIAL"
    assert 0 < position.quantity < 1500


def test_paper_entry_rejected_when_order_dwarfs_available_volume(db_session):
    om = OrderManager(db_session, mode="paper")
    # quantity is 50% of avg_bar_volume - beyond the reject threshold
    order, position = om.place_entry(
        symbol="NSE:TEST-EQ", direction="BUY", quantity=5000, reference_price=100,
        stop_loss=95, target=115, signal_id=None, avg_bar_volume=10_000,
    )
    assert order.status == "REJECTED"
    assert position is None
    assert order.error_message is not None


# ---- Phase 7: available-capital enforcement ---------------------------------

def test_paper_entry_rejected_when_exceeding_available_capital(db_session):
    om = OrderManager(db_session, mode="paper")
    order, position = om.place_entry(
        symbol="NSE:TEST-EQ", direction="BUY", quantity=100, reference_price=100,  # needs Rs.10,000
        stop_loss=95, target=115, signal_id=None, available_capital=5000.0,
    )
    assert order.status == "REJECTED"
    assert position is None
    assert "capital" in order.error_message.lower()


def test_paper_entry_succeeds_when_within_available_capital(db_session):
    om = OrderManager(db_session, mode="paper")
    order, position = om.place_entry(
        symbol="NSE:TEST-EQ", direction="BUY", quantity=10, reference_price=100,  # needs Rs.1,000
        stop_loss=95, target=115, signal_id=None, available_capital=5000.0,
    )
    assert order.status == "FILLED"
    assert position is not None


def test_available_capital_check_never_blocks_when_not_provided(db_session):
    """Backward compatibility: omitting available_capital (e.g. existing
    callers/tests) must behave exactly as before - no capital check at all."""
    om = OrderManager(db_session, mode="paper")
    order, position = om.place_entry(
        symbol="NSE:TEST-EQ", direction="BUY", quantity=10_000_000, reference_price=100,
        stop_loss=95, target=115, signal_id=None,
    )
    assert order.status == "FILLED"
