import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_PATH"] = _tmp_db.name
os.environ.setdefault("FYERS_CLIENT_ID", "TEST-100")
os.environ.setdefault("FYERS_SECRET_KEY", "test-secret")
os.environ.setdefault("APP_SECRET_KEY", "ZnNi0snhYJ602pHrMf3zy6IAnlITb17Mjdqe7JPmb_M=")  # fixed test-only fernet key
os.environ.setdefault("MARKET_OPEN_TIME", "00:00")
os.environ.setdefault("MARKET_CLOSE_TIME", "23:59")
os.environ.setdefault("ENTRY_START_TIME", "00:00")
os.environ.setdefault("ENTRY_CUTOFF_TIME", "23:58")
os.environ.setdefault("SQUARE_OFF_TIME", "23:59")

import pytest  # noqa: E402

from app.database import Base, engine as db_engine, SessionLocal  # noqa: E402
from app.models import UserSettings  # noqa: E402
from app.fyers.rate_limiter import reset_rate_limiter_for_tests  # noqa: E402
from app.fyers.price_cache import reset_price_cache_for_tests  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(bind=db_engine)
    Base.metadata.create_all(bind=db_engine)
    yield
    Base.metadata.drop_all(bind=db_engine)


@pytest.fixture(autouse=True)
def fresh_fyers_shared_state():
    """Every test gets an isolated rate limiter and price cache instead of
    sharing process-wide singletons - otherwise one test's FYERS calls could
    affect another test's rate-limit counting."""
    reset_rate_limiter_for_tests()
    reset_price_cache_for_tests()
    yield


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def user_settings(db_session):
    settings = UserSettings(
        trading_capital=10000.0, risk_profile="conservative", trading_mode="paper",
        max_risk_per_trade_pct=0.5, max_daily_loss_pct=1.5, max_trades_per_day=3,
        max_open_positions=1, min_risk_reward=1.5, max_consecutive_losses=2,
        auto_trading_enabled=True, kill_switch_active=False,
    )
    db_session.add(settings)
    db_session.commit()
    return settings


def make_trending_candles(start_price: float, bars: int = 40, drift_pct: float = 0.15,
                           base_volume: float = 50_000, direction: int = 1) -> list[dict]:
    """Synthetic candle generator for deterministic strategy/indicator tests.

    Produces a clear net trend in `direction` but with regular pullback bars
    (every 3rd bar), so indicators like RSI behave like a real (if clean)
    trending market instead of pegging at an extreme of 0/100.
    """
    candles = []
    price = start_price
    for i in range(bars):
        open_p = price
        bar_direction = -0.9 if (i % 3 == 2) else 1.0
        price = price * (1 + direction * bar_direction * drift_pct / 100)
        high = max(open_p, price) * 1.001
        low = min(open_p, price) * 0.999
        volume = base_volume * (1.5 if i == bars - 1 else 1.0)
        candles.append({
            "timestamp": 1_700_000_000 + i * 300, "open": round(open_p, 2), "high": round(high, 2),
            "low": round(low, 2), "close": round(price, 2), "volume": volume,
        })
    return candles
