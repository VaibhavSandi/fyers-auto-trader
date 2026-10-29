"""
FYERS OAuth-style login flow.

Flow:
  1. generate_login_url()  -> frontend opens this URL in the user's browser
  2. user logs in on FYERS' own site with their own credentials (we never see
     their FYERS password)
  3. FYERS redirects the browser to FYERS_REDIRECT_URI with ?auth_code=...&state=...
  4. our backend's /api/auth/fyers/callback route receives that request and
     calls exchange_auth_code() to get an access_token
  5. the access_token is encrypted and stored in broker_connections

FYERS access tokens are valid only for the trading day they were issued
(they expire overnight), so this flow must be repeated once per day.
"""
from __future__ import annotations

import logging
import secrets as pysecrets
import datetime as dt

from fyers_apiv3 import fyersModel

from app.config import get_settings

logger = logging.getLogger(__name__)


class FyersAuthError(RuntimeError):
    pass


def new_state_token() -> str:
    return pysecrets.token_urlsafe(24)


def generate_login_url(state: str) -> str:
    settings = get_settings()
    if not settings.FYERS_CLIENT_ID or not settings.FYERS_SECRET_KEY:
        raise FyersAuthError(
            "FYERS_CLIENT_ID / FYERS_SECRET_KEY are not configured in .env. "
            "Create an app at https://myapi.fyers.in/dashboard first."
        )
    session = fyersModel.SessionModel(
        client_id=settings.FYERS_CLIENT_ID,
        secret_key=settings.FYERS_SECRET_KEY,
        redirect_uri=settings.FYERS_REDIRECT_URI,
        response_type="code",
        state=state,
        grant_type="authorization_code",
    )
    return session.generate_authcode()


def exchange_auth_code(auth_code: str) -> str:
    """Exchange a one-time auth_code for an access_token. Returns the access_token."""
    settings = get_settings()
    session = fyersModel.SessionModel(
        client_id=settings.FYERS_CLIENT_ID,
        secret_key=settings.FYERS_SECRET_KEY,
        redirect_uri=settings.FYERS_REDIRECT_URI,
        response_type="code",
        grant_type="authorization_code",
    )
    session.set_token(auth_code)
    response = session.generate_token()

    if not isinstance(response, dict) or response.get("s") != "ok" or "access_token" not in response:
        logger.error("FYERS token exchange failed: %s", {k: v for k, v in (response or {}).items() if k != "access_token"})
        raise FyersAuthError(f"FYERS token exchange failed: {response.get('message', 'unknown error') if isinstance(response, dict) else response}")

    return response["access_token"]


def today_str() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d")
