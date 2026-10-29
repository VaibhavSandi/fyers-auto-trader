import datetime as dt
import random

import pytest

from app.ml.features import extract_features, FEATURE_NAMES
from app.ml.trade_outcome_model import TradeOutcomeModel, build_training_set, MIN_TRAINING_EXAMPLES
from app.data.historical import HistoricalDataService
from app.models import MarketData, BacktestTrade


def _trending_candles(bars: int, start_price: float, drift_pct: float, direction: int,
                       start: dt.datetime, base_volume: float = 50_000) -> list[dict]:
    candles = []
    price = start_price
    ts = start
    for i in range(bars):
        open_p = price
        bar_direction = -0.9 if (i % 3 == 2) else 1.0
        price = price * (1 + direction * bar_direction * drift_pct / 100)
        high = max(open_p, price) * 1.001
        low = min(open_p, price) * 0.999
        volume = base_volume * (1.5 if i == bars - 1 else 1.0)
        candles.append({"timestamp": ts, "open": round(open_p, 2), "high": round(high, 2),
                         "low": round(low, 2), "close": round(price, 2), "volume": volume})
        ts += dt.timedelta(minutes=5)
    return candles


def test_extract_features_returns_none_for_insufficient_candles():
    candles = _trending_candles(10, 1000, 0.1, 1, dt.datetime(2026, 1, 5, 3, 45))
    assert extract_features(candles, "BULLISH", 8, 1.5) is None


def test_extract_features_returns_all_expected_keys():
    candles = _trending_candles(40, 1000, 0.1, 1, dt.datetime(2026, 1, 5, 3, 45))
    features = extract_features(candles, "BULLISH", 8, 1.5)
    assert features is not None
    assert set(features.keys()) == set(FEATURE_NAMES)
    assert features["strategy_score"] == 8
    assert features["risk_reward"] == 1.5


def test_build_training_set_empty_when_no_trades(db_session):
    service = HistoricalDataService(db_session, fyers_client=None)
    examples = build_training_set(db_session, service)
    assert examples == []


def test_build_training_set_never_uses_candles_after_entry_time(db_session):
    base = dt.datetime(2026, 1, 5, 3, 45)
    history = _trending_candles(40, 1000, 0.1, 1, base)
    entry_time = history[-1]["timestamp"]
    # candles AFTER the trade's entry - a wild, unmistakable price spike
    future = _trending_candles(10, 50000, 0.1, 1, entry_time + dt.timedelta(minutes=5))

    for c in history + future:
        db_session.add(MarketData(symbol="NSE:TEST-EQ", timeframe="5", timestamp=c["timestamp"],
                                   open=c["open"], high=c["high"], low=c["low"], close=c["close"],
                                   volume=c["volume"], source="test"))
    db_session.commit()

    db_session.add(BacktestTrade(
        run_id=1, symbol="NSE:TEST-EQ", direction="BUY", entry_time=entry_time,
        exit_time=entry_time + dt.timedelta(minutes=15), entry_price=1000.0, exit_price=1010.0,
        quantity=10, stop_loss=995.0, target=1010.0, exit_reason="TARGET",
        gross_pnl=100.0, charges=5.0, net_pnl=95.0, strategy_score=8, market_regime="BULLISH",
    ))
    db_session.commit()

    service = HistoricalDataService(db_session, fyers_client=None)
    examples = build_training_set(db_session, service)

    assert len(examples) == 1
    features, label, pnl = examples[0]
    # if the future 50000-price spike had leaked in, momentum/ema features
    # would be wildly different from what a 1000-ish price series produces
    assert features["momentum_pct"] < 50  # sane value, nowhere near what a jump to 50000 would cause
    assert label == 1
    assert pnl == 95.0


def _synthetic_examples(n: int, seed: int = 0) -> list[tuple[dict, int, float]]:
    rng = random.Random(seed)
    examples = []
    for i in range(n):
        is_win = rng.random() < 0.5
        features = {
            "rsi": rng.uniform(30, 70) + (10 if is_win else -10),
            "atr_pct": rng.uniform(0.1, 1.0),
            "relative_volume": rng.uniform(1.0, 2.0) + (0.5 if is_win else 0),
            "momentum_pct": rng.uniform(-1, 1) + (0.5 if is_win else -0.5),
            "ema_spread_pct": rng.uniform(-0.5, 0.5) + (0.2 if is_win else -0.2),
            "regime_score": rng.choice([1, 2, 3, 4]),
            "hour_of_day": rng.randint(9, 14),
            "day_of_week": rng.randint(0, 4),
            "strategy_score": rng.randint(6, 10),
            "risk_reward": rng.uniform(1.3, 2.5),
        }
        pnl = rng.uniform(20, 100) if is_win else -rng.uniform(20, 80)
        examples.append((features, 1 if is_win else 0, pnl))
    return examples


def test_train_refuses_below_minimum_sample_size():
    model = TradeOutcomeModel()
    with pytest.raises(ValueError):
        model.train(_synthetic_examples(MIN_TRAINING_EXAMPLES - 1))


def test_train_succeeds_at_minimum_sample_size_and_reports_metrics():
    model = TradeOutcomeModel()
    metrics = model.train(_synthetic_examples(MIN_TRAINING_EXAMPLES, seed=1))
    assert "accuracy" in metrics
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert model.sample_size == MIN_TRAINING_EXAMPLES


def test_predict_returns_probability_and_expected_value():
    model = TradeOutcomeModel()
    model.train(_synthetic_examples(80, seed=2))
    features, _, _ = _synthetic_examples(1, seed=3)[0]
    result = model.predict(features)
    assert 0.0 <= result["p_win"] <= 1.0
    assert isinstance(result["expected_value"], float)
    assert result["sample_size"] == 80


def test_predict_without_training_raises():
    model = TradeOutcomeModel()
    with pytest.raises(RuntimeError):
        model.predict({name: 0 for name in FEATURE_NAMES})


def test_save_and_load_round_trip_preserves_predictions(tmp_path):
    model = TradeOutcomeModel()
    model.train(_synthetic_examples(80, seed=4))
    features, _, _ = _synthetic_examples(1, seed=5)[0]
    before = model.predict(features)

    path = tmp_path / "model.joblib"
    model.save(path)
    loaded = TradeOutcomeModel.load(path)
    after = loaded.predict(features)

    assert before == after
    assert loaded.sample_size == model.sample_size
