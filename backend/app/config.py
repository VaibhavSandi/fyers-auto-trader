"""
Central application configuration.

Every secret (FYERS client id/secret, encryption key) is read from the
environment (.env file) and NEVER hard-coded. See .env.example.
"""
from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore")

    # FYERS app credentials (secrets - never log these)
    FYERS_CLIENT_ID: str = ""
    FYERS_SECRET_KEY: str = ""
    FYERS_REDIRECT_URI: str = "http://127.0.0.1:8000/api/auth/fyers/callback"

    APP_SECRET_KEY: str = ""

    BACKEND_HOST: str = "127.0.0.1"
    BACKEND_PORT: int = 8000

    DATABASE_PATH: str = "./data/trading.db"

    # Hard, application-wide ceilings. No risk profile, no user setting,
    # can ever exceed these values. This is the last line of defence.
    HARD_MAX_DAILY_LOSS_PCT: float = 5.0
    HARD_MAX_RISK_PER_TRADE_PCT: float = 2.0
    HARD_MAX_OPEN_POSITIONS: int = 3
    HARD_MAX_TRADES_PER_DAY: int = 8

    MARKET_OPEN_TIME: str = "09:15"
    MARKET_CLOSE_TIME: str = "15:30"
    # The opening minutes are unusually volatile/noisy and produce false
    # signals - standard intraday practice is to let the market settle
    # before taking any new entry. New positions are only opened between
    # ENTRY_START_TIME and ENTRY_CUTOFF_TIME.
    ENTRY_START_TIME: str = "09:30"
    ENTRY_CUTOFF_TIME: str = "14:45"
    SQUARE_OFF_TIME: str = "15:12"

    LOG_LEVEL: str = "INFO"

    @property
    def database_path(self) -> Path:
        p = Path(self.DATABASE_PATH)
        if not p.is_absolute():
            p = BACKEND_DIR / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def logs_dir(self) -> Path:
        d = BACKEND_DIR / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d


@lru_cache
def get_settings() -> Settings:
    return Settings()


def mask_secret(value: str | None, keep: int = 4) -> str:
    """Mask a secret for safe display in UI/logs."""
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "*" * max(0, len(value) - keep - 2) + value[-2:]
