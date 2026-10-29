from __future__ import annotations

import logging
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BrokerConnection, AuditLog
from app.fyers import auth as fyers_auth
from app.fyers.client import FyersClient, FyersApiError
from app.security import encrypt, decrypt, mask, SecretsNotConfiguredError
from app.config import get_settings
from app.engine.trading_engine import engine as trading_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth/fyers", tags=["auth"])

# Some users' FYERS app dashboards were set up with the callback path
# /api/broker/fyers/callback instead of /api/auth/fyers/callback. FYERS
# rejects the login entirely if the redirect_uri we send doesn't exactly
# match what's registered on the dashboard, so rather than forcing every
# user to go edit that dashboard setting, this app accepts the callback on
# BOTH paths - whichever one is actually registered will work.
legacy_callback_router = APIRouter(prefix="/api/broker/fyers", tags=["auth"])


@router.get("/login-url")
def login_url(db: Session = Depends(get_db)):
    state = fyers_auth.new_state_token()
    conn = db.query(BrokerConnection).filter_by(broker="fyers").first()
    if conn is None:
        conn = BrokerConnection(broker="fyers")
        db.add(conn)
    conn.auth_state = state
    conn.connected = False
    db.commit()

    try:
        url = fyers_auth.generate_login_url(state)
    except fyers_auth.FyersAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"login_url": url}


@router.get("/callback")
@legacy_callback_router.get("/callback")
def callback(auth_code: str | None = None, state: str | None = None, s: str | None = None,
             db: Session = Depends(get_db)):
    """FYERS redirects the user's browser here after they log in on fyers.in."""
    conn = db.query(BrokerConnection).filter_by(broker="fyers").first()

    if s == "error" or not auth_code:
        if conn:
            conn.last_error = "Login was cancelled or failed at FYERS"
            db.commit()
        return HTMLResponse("<h2>FYERS login failed or was cancelled. You can close this tab and retry in the app.</h2>")

    if conn is None or conn.auth_state != state:
        return HTMLResponse("<h2>Security check failed (state mismatch). Please retry connecting from the app.</h2>", status_code=400)

    try:
        access_token = fyers_auth.exchange_auth_code(auth_code)
    except fyers_auth.FyersAuthError as exc:
        conn.last_error = str(exc)
        conn.connected = False
        db.commit()
        return HTMLResponse(f"<h2>Could not complete FYERS login: {exc}</h2>", status_code=400)

    settings = get_settings()
    try:
        conn.access_token_encrypted = encrypt(access_token)
    except SecretsNotConfiguredError as exc:
        return HTMLResponse(f"<h2>Server misconfiguration: {exc}</h2>", status_code=500)

    conn.connected = True
    conn.connected_at = dt.datetime.utcnow()
    conn.token_date = dt.date.today().isoformat()
    conn.client_id_masked = mask(settings.FYERS_CLIENT_ID)
    conn.last_error = None
    db.commit()

    try:
        client = FyersClient(access_token)
        client.get_profile()
        trading_engine.attach_fyers_client(client)
    except FyersApiError as exc:
        conn.last_error = f"Token saved but validation failed: {exc}"
        db.commit()

    db.add(AuditLog(actor="USER", action="FYERS_CONNECTED", details={}))
    db.commit()

    return HTMLResponse(
        "<h2>FYERS connected successfully.</h2><p>You can close this tab and return to the app.</p>"
    )


@router.get("/status")
def status(db: Session = Depends(get_db)):
    conn = db.query(BrokerConnection).filter_by(broker="fyers").first()
    if conn is None or not conn.connected:
        return {"connected": False}

    today = dt.date.today().isoformat()
    token_valid_today = conn.token_date == today
    return {
        "connected": bool(conn.connected and token_valid_today),
        "token_expired": not token_valid_today,
        "client_id_masked": conn.client_id_masked,
        "connected_at": conn.connected_at,
        "last_error": conn.last_error,
    }


@router.post("/disconnect")
def disconnect(db: Session = Depends(get_db)):
    conn = db.query(BrokerConnection).filter_by(broker="fyers").first()
    if conn:
        conn.connected = False
        conn.access_token_encrypted = None
        db.commit()
    trading_engine.attach_fyers_client(None)
    db.add(AuditLog(actor="USER", action="FYERS_DISCONNECTED", details={}))
    db.commit()
    return {"connected": False}
