from __future__ import annotations

from pydantic import BaseModel, Field


class SetupDefaultsRequest(BaseModel):
    capital: float = Field(gt=0)
    risk_profile: str = "conservative"


class SaveSettingsRequest(BaseModel):
    trading_capital: float = Field(gt=0)
    risk_profile: str = "conservative"
    trading_mode: str = "paper"
    # Advanced overrides (optional - simple dashboard never sends these)
    max_risk_per_trade_pct: float | None = None
    max_daily_loss_pct: float | None = None
    max_trades_per_day: int | None = None
    max_open_positions: int | None = None
    min_risk_reward: float | None = None
    max_consecutive_losses: int | None = None


class FyersCallbackQuery(BaseModel):
    auth_code: str | None = None
    state: str | None = None
    s: str | None = None
