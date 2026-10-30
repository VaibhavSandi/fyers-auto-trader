"""
Telegram alerting (opt-in, OFF by default) - the only purpose of this module
is to tell you about something you'd otherwise only see by having the
dashboard open: the kill switch firing, the daily loss limit or a
consecutive-loss pause, the backend (re)starting and needing a recovery
check, or FYERS going unreachable.

Design rules:
  - A no-op unless BOTH Settings.TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are
    set - no accidental network calls for users who never configured this.
  - Fire-and-forget: the HTTP call runs in its own short-lived thread so a
    slow/unreachable Telegram API can never add latency to an engine tick,
    a kill-switch API request, or app startup.
  - Best-effort only: a failed send is logged, never raised - alerting must
    never become a second way for the trading engine to break.
"""
from __future__ import annotations

import logging
import threading

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
REQUEST_TIMEOUT_SECONDS = 5


def notify(message: str) -> None:
    settings = get_settings()
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    thread = threading.Thread(target=_send, args=(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID, message),
                               daemon=True)
    thread.start()


def _send(token: str, chat_id: str, message: str) -> None:
    try:
        resp = requests.post(
            TELEGRAM_API_URL.format(token=token),
            json={"chat_id": chat_id, "text": f"FYERS Auto Trader\n\n{message}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            logger.warning("Telegram alert failed (%s): %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("Telegram alert failed to send: %s", exc)
