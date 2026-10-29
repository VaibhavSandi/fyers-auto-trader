"""
Application-wide logging. Rotating file logs + console. All logs are
automatically scrubbed of anything that looks like a secret/token.
"""
from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler

from app.config import get_settings

_SECRET_PATTERNS = [
    re.compile(r"(access_token\"?\s*[:=]\s*\"?)([A-Za-z0-9._-]{10,})", re.IGNORECASE),
    re.compile(r"(secret_key\"?\s*[:=]\s*\"?)([A-Za-z0-9._-]{10,})", re.IGNORECASE),
    re.compile(r"(client_id\"?\s*[:=]\s*\"?)([A-Za-z0-9._-]{6,})", re.IGNORECASE),
]


class SecretScrubFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        scrubbed = msg
        for pattern in _SECRET_PATTERNS:
            scrubbed = pattern.sub(lambda m: m.group(1) + "***MASKED***", scrubbed)
        if scrubbed != msg:
            record.msg = scrubbed
            record.args = ()
        return True


def setup_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)

    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.addFilter(SecretScrubFilter())

    file_handler = RotatingFileHandler(
        settings.logs_dir / "app.log", maxBytes=5_000_000, backupCount=10, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.addFilter(SecretScrubFilter())

    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(file_handler)
