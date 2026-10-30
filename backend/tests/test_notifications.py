import time

from app.notifications import telegram


def test_notify_is_a_noop_when_not_configured(monkeypatch):
    monkeypatch.setattr(telegram, "get_settings", lambda: type(
        "S", (), {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}
    )())
    calls = []
    monkeypatch.setattr(telegram, "_send", lambda *a, **k: calls.append((a, k)))
    telegram.notify("should not send")
    time.sleep(0.05)
    assert calls == []


def test_notify_sends_when_configured(monkeypatch):
    monkeypatch.setattr(telegram, "get_settings", lambda: type(
        "S", (), {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}
    )())
    calls = []
    monkeypatch.setattr(telegram, "_send", lambda token, chat_id, message: calls.append((token, chat_id, message)))
    telegram.notify("hello")
    time.sleep(0.2)  # _send runs in a background thread
    assert calls == [("tok", "123", "hello")]


def test_send_failure_is_swallowed_not_raised(monkeypatch):
    class FailingResponse:
        status_code = 500
        text = "internal error"

    monkeypatch.setattr(telegram.requests, "post", lambda *a, **k: FailingResponse())
    telegram._send("tok", "123", "hello")  # must not raise
