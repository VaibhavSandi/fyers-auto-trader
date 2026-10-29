"""
Symmetric encryption for secrets at rest (the FYERS access token).

The encryption key (APP_SECRET_KEY) comes only from the environment.
If it is missing, we refuse to store/retrieve tokens rather than falling
back to a hard-coded key.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class SecretsNotConfiguredError(RuntimeError):
    pass


def _fernet() -> Fernet:
    settings = get_settings()
    if not settings.APP_SECRET_KEY:
        raise SecretsNotConfiguredError(
            "APP_SECRET_KEY is not set in .env. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(settings.APP_SECRET_KEY.encode())
    except Exception as exc:
        raise SecretsNotConfiguredError(f"APP_SECRET_KEY is invalid: {exc}") from exc


def encrypt(plain_text: str) -> str:
    return _fernet().encrypt(plain_text.encode()).decode()


def decrypt(cipher_text: str) -> str:
    try:
        return _fernet().decrypt(cipher_text.encode()).decode()
    except InvalidToken as exc:
        raise SecretsNotConfiguredError("Stored token could not be decrypted (key mismatch).") from exc


def mask(value: str | None, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "*" * max(0, len(value) - keep - 2) + value[-2:]
