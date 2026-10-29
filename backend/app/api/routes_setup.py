from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import UserSettings, AuditLog
from app.engine.risk_profiles import compute_safe_defaults, available_profiles, get_profile
from app.schemas import SetupDefaultsRequest, SaveSettingsRequest
from app.config import get_settings as get_app_settings

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/profiles")
def list_profiles():
    return {name: get_profile(name).explanation for name in available_profiles()}


@router.get("/defaults")
def defaults(capital: float, risk_profile: str = "conservative"):
    if capital <= 0:
        raise HTTPException(status_code=400, detail="Capital must be positive")
    return compute_safe_defaults(capital, risk_profile)


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    settings = db.query(UserSettings).first()
    if settings is None:
        settings = UserSettings()
        db.add(settings)
        db.commit()
    return _settings_to_dict(settings)


@router.post("/settings")
def save_settings(payload: SaveSettingsRequest, db: Session = Depends(get_db)):
    app_settings = get_app_settings()
    settings = db.query(UserSettings).first()
    if settings is None:
        settings = UserSettings()
        db.add(settings)

    defaults_calc = compute_safe_defaults(payload.trading_capital, payload.risk_profile)

    settings.trading_capital = payload.trading_capital
    settings.risk_profile = payload.risk_profile.lower()
    settings.trading_mode = payload.trading_mode.lower()

    settings.max_risk_per_trade_pct = min(
        payload.max_risk_per_trade_pct if payload.max_risk_per_trade_pct is not None else defaults_calc["max_risk_per_trade_pct"],
        app_settings.HARD_MAX_RISK_PER_TRADE_PCT,
    )
    settings.max_daily_loss_pct = min(
        payload.max_daily_loss_pct if payload.max_daily_loss_pct is not None else defaults_calc["max_daily_loss_pct"],
        app_settings.HARD_MAX_DAILY_LOSS_PCT,
    )
    settings.max_trades_per_day = min(
        payload.max_trades_per_day if payload.max_trades_per_day is not None else defaults_calc["max_trades_per_day"],
        app_settings.HARD_MAX_TRADES_PER_DAY,
    )
    settings.max_open_positions = min(
        payload.max_open_positions if payload.max_open_positions is not None else defaults_calc["max_open_positions"],
        app_settings.HARD_MAX_OPEN_POSITIONS,
    )
    settings.min_risk_reward = payload.min_risk_reward if payload.min_risk_reward is not None else defaults_calc["min_risk_reward"]
    settings.max_consecutive_losses = payload.max_consecutive_losses if payload.max_consecutive_losses is not None else defaults_calc["max_consecutive_losses"]

    db.commit()
    db.add(AuditLog(actor="USER", action="SETTINGS_SAVED", details=_settings_to_dict(settings)))
    db.commit()
    return _settings_to_dict(settings)


def _settings_to_dict(s: UserSettings) -> dict:
    return {
        "trading_capital": s.trading_capital, "risk_profile": s.risk_profile, "trading_mode": s.trading_mode,
        "max_risk_per_trade_pct": s.max_risk_per_trade_pct, "max_daily_loss_pct": s.max_daily_loss_pct,
        "max_trades_per_day": s.max_trades_per_day, "max_open_positions": s.max_open_positions,
        "min_risk_reward": s.min_risk_reward, "max_consecutive_losses": s.max_consecutive_losses,
        "auto_trading_enabled": s.auto_trading_enabled, "kill_switch_active": s.kill_switch_active,
    }
