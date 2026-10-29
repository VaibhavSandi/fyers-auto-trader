from app.engine.order_manager import OrderManager
from app.engine.position_manager import PositionManager
from app.models import Position, Trade


def test_close_all_positions_closes_every_open_position(db_session, user_settings):
    db_session.add(Position(symbol="NSE:A-EQ", direction="BUY", quantity=10, entry_price=100,
                             stop_loss=95, original_stop_loss=95, target=110, current_price=103,
                             status="OPEN", mode="paper"))
    db_session.add(Position(symbol="NSE:B-EQ", direction="SELL", quantity=5, entry_price=200,
                             stop_loss=205, original_stop_loss=205, target=190, current_price=198,
                             status="OPEN", mode="paper"))
    db_session.commit()

    om = OrderManager(db_session, mode="paper")
    pm = PositionManager(db_session, om)
    closed = pm.force_close_all("MANUAL", price_lookup=lambda s: None)  # fall back to current_price

    assert len(closed) == 2
    positions = db_session.query(Position).all()
    assert all(p.status == "CLOSED" for p in positions)
    assert all(p.exit_reason == "MANUAL" for p in positions)


def test_close_all_positions_writes_trade_journal_entries(db_session, user_settings):
    db_session.add(Position(symbol="NSE:A-EQ", direction="BUY", quantity=10, entry_price=100,
                             stop_loss=95, original_stop_loss=95, target=110, current_price=103,
                             status="OPEN", mode="paper"))
    db_session.commit()

    om = OrderManager(db_session, mode="paper")
    pm = PositionManager(db_session, om)
    pm.force_close_all("MANUAL", price_lookup=lambda s: 103)

    trades = db_session.query(Trade).all()
    assert len(trades) == 1
    assert trades[0].exit_reason == "MANUAL"


def test_close_all_positions_does_nothing_when_no_open_positions(db_session, user_settings):
    om = OrderManager(db_session, mode="paper")
    pm = PositionManager(db_session, om)
    closed = pm.force_close_all("MANUAL", price_lookup=lambda s: 100)
    assert closed == []
