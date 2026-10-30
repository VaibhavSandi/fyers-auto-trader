from app.engine.trading_engine import TradingEngine


def test_connectivity_transition_only_notifies_once_while_blocked(monkeypatch):
    notified = []
    monkeypatch.setattr("app.notifications.telegram.notify", lambda msg: notified.append(msg))

    engine = TradingEngine()
    engine._check_connectivity_transition(True, "down")
    engine._check_connectivity_transition(True, "still down")
    engine._check_connectivity_transition(True, "still down again")

    assert len(notified) == 1


def test_connectivity_transition_notifies_again_on_recovery_and_redrop(monkeypatch):
    notified = []
    monkeypatch.setattr("app.notifications.telegram.notify", lambda msg: notified.append(msg))

    engine = TradingEngine()
    engine._check_connectivity_transition(True, "down")
    engine._check_connectivity_transition(False, "back up")
    engine._check_connectivity_transition(True, "down again")

    assert len(notified) == 3
