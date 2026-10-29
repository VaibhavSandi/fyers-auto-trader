"""
The three user-facing risk profiles, and the "safe defaults" calculator.

The user never sets numbers directly. They pick Conservative / Balanced /
Aggressive and enter their capital; everything else is derived here - and
then clipped against the application's HARD_MAX_* ceilings (app/config.py),
which no profile, and no future setting, is ever allowed to exceed.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings


@dataclass
class RiskProfileConfig:
    name: str
    risk_per_trade_pct: float
    daily_loss_pct: float
    max_trades_per_day: int
    max_open_positions: int
    min_risk_reward: float
    max_consecutive_losses: int
    explanation: str


_RAW_PROFILES: dict[str, RiskProfileConfig] = {
    "conservative": RiskProfileConfig(
        name="Conservative",
        risk_per_trade_pct=0.5,
        daily_loss_pct=1.5,
        max_trades_per_day=3,
        max_open_positions=1,
        min_risk_reward=1.5,
        max_consecutive_losses=2,
        explanation=(
            "Built for beginners. The app risks only 0.5% of your capital per trade, "
            "takes at most 3 trades a day, holds only 1 position at a time, and stops "
            "completely for the day if losses reach 1.5% of your capital. It only trades "
            "when the setup is very clean."
        ),
    ),
    "balanced": RiskProfileConfig(
        name="Balanced",
        risk_per_trade_pct=1.0,
        daily_loss_pct=2.5,
        max_trades_per_day=5,
        max_open_positions=2,
        min_risk_reward=1.4,
        max_consecutive_losses=3,
        explanation=(
            "A moderate setting. The app risks 1% of your capital per trade, allows up "
            "to 5 trades a day across 2 positions at once, and stops for the day if "
            "losses reach 2.5% of your capital."
        ),
    ),
    "aggressive": RiskProfileConfig(
        name="Aggressive",
        risk_per_trade_pct=1.5,
        daily_loss_pct=4.0,
        max_trades_per_day=8,
        max_open_positions=3,
        min_risk_reward=1.3,
        max_consecutive_losses=3,
        explanation=(
            "For experienced users comfortable with more risk. The app risks 1.5% of "
            "your capital per trade and allows more trades/positions - but it NEVER "
            "exceeds the application's absolute hard safety ceilings, no matter what."
        ),
    ),
}


def available_profiles() -> list[str]:
    return list(_RAW_PROFILES.keys())


def get_profile(name: str) -> RiskProfileConfig:
    key = (name or "conservative").lower()
    if key not in _RAW_PROFILES:
        key = "conservative"
    return _RAW_PROFILES[key]


def compute_safe_defaults(capital: float, profile_name: str) -> dict:
    """Translate a profile + capital into concrete, hard-capped numbers."""
    settings = get_settings()
    profile = get_profile(profile_name)

    risk_per_trade_pct = min(profile.risk_per_trade_pct, settings.HARD_MAX_RISK_PER_TRADE_PCT)
    daily_loss_pct = min(profile.daily_loss_pct, settings.HARD_MAX_DAILY_LOSS_PCT)
    max_trades_per_day = min(profile.max_trades_per_day, settings.HARD_MAX_TRADES_PER_DAY)
    max_open_positions = min(profile.max_open_positions, settings.HARD_MAX_OPEN_POSITIONS)

    max_risk_per_trade_amount = round(capital * risk_per_trade_pct / 100, 2)
    max_daily_loss_amount = round(capital * daily_loss_pct / 100, 2)

    return {
        "risk_profile": profile_name.lower(),
        "profile_label": profile.name,
        "explanation": profile.explanation,
        "max_risk_per_trade_pct": risk_per_trade_pct,
        "max_daily_loss_pct": daily_loss_pct,
        "max_trades_per_day": max_trades_per_day,
        "max_open_positions": max_open_positions,
        "min_risk_reward": profile.min_risk_reward,
        "max_consecutive_losses": profile.max_consecutive_losses,
        "max_risk_per_trade_amount": max_risk_per_trade_amount,
        "max_daily_loss_amount": max_daily_loss_amount,
    }
