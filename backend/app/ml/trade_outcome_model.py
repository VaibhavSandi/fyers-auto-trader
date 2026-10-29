"""
Trade-outcome probability model (Phase 4/6's ML component) - a classifier
predicting P(win) for a candidate setup, trained on REAL completed
backtest trades (never synthetic data), using the same indicator values
(app/ml/features.py) the rule-based strategies already compute.

IMPORTANT - this model is ADVISORY ONLY in this version: nothing in live
or paper trading reads its output yet. It exists to be trained, inspected,
and evaluated via the API. The self-learning promotion loop (Phase 8) is
what would eventually be allowed to wire a properly validated version of
this into real decisions - never this training step directly. This
mirrors the master prompt's own instruction: "Do not confuse a high
predicted probability of winning with positive expected profitability",
and its Phase 8 caution against live parameter changes that haven't been
validated.

With few training examples, treat every prediction as exploratory, not
reliable - MIN_TRAINING_EXAMPLES is a floor below which training is
refused outright, not a guarantee of quality above it. Also note: trades
drawn from multiple strategies backtested over the same overlapping
periods/symbols are NOT independent samples - the reported metrics
describe this specific training set, not a generalizable truth.
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, brier_score_loss, accuracy_score

from app.ml.features import FEATURE_NAMES, extract_features
from app.data.historical import HistoricalDataService
from app.models import BacktestTrade

logger = logging.getLogger(__name__)

MIN_TRAINING_EXAMPLES = 30
MODEL_DIR_NAME = "ml_models"


def build_training_set(db, data_service: HistoricalDataService) -> list[tuple[dict, int, float]]:
    """Reconstructs the feature vector AS OF each historical trade's entry
    time (never using data from after the trade was taken), by re-slicing
    the same locally stored candles the backtester itself used."""
    trades = db.query(BacktestTrade).filter(BacktestTrade.net_pnl.isnot(None)).all()
    examples: list[tuple[dict, int, float]] = []
    candle_cache: dict[str, list[dict]] = {}

    for t in trades:
        if t.entry_time is None or t.entry_price is None or t.stop_loss is None:
            continue
        if t.symbol not in candle_cache:
            start = (t.entry_time - dt.timedelta(days=45)).date()
            candle_cache[t.symbol] = data_service.get_candles(t.symbol, "5", start, dt.date.today())
        window = [c for c in candle_cache[t.symbol] if c["timestamp"] <= t.entry_time]
        if len(window) < 25:
            continue

        risk_per_share = abs(t.entry_price - t.stop_loss)
        reward_per_share = abs((t.target or t.entry_price) - t.entry_price)
        risk_reward = round(reward_per_share / risk_per_share, 2) if risk_per_share else 0.0

        features = extract_features(window, t.market_regime or "NEUTRAL", t.strategy_score or 0, risk_reward)
        if features is None:
            continue
        examples.append((features, 1 if t.net_pnl > 0 else 0, t.net_pnl))

    return examples


class TradeOutcomeModel:
    def __init__(self):
        self.classifier: LogisticRegression | None = None
        self.avg_win = 0.0
        self.avg_loss = 0.0
        self.metrics: dict = {}
        self.trained_at: dt.datetime | None = None
        self.sample_size = 0

    def train(self, examples: list[tuple[dict, int, float]]) -> dict:
        if len(examples) < MIN_TRAINING_EXAMPLES:
            raise ValueError(
                f"Only {len(examples)} usable training examples - need at least {MIN_TRAINING_EXAMPLES}. "
                f"Run more backtests (more symbols/longer synced history) before training."
            )

        X = [[ex[0][name] for name in FEATURE_NAMES] for ex in examples]
        y = [ex[1] for ex in examples]
        pnls = [ex[2] for ex in examples]

        # Examples are drawn from many different backtests/symbols, not one
        # continuous timeline, so a chronological split isn't meaningful
        # here (unlike the walk-forward backtester). This is a stratified
        # RANDOM split - reported as such, not claimed as time-based
        # out-of-sample validation.
        stratify = y if len(set(y)) > 1 else None
        X_train, X_test, y_train, y_test, _pnl_train, _pnl_test = train_test_split(
            X, y, pnls, test_size=0.3, random_state=42, stratify=stratify,
        )

        clf = LogisticRegression(max_iter=1000, class_weight="balanced")
        clf.fit(X_train, y_train)

        y_pred = clf.predict(X_test)
        y_proba = clf.predict_proba(X_test)[:, 1]

        metrics: dict = {
            "train_size": len(X_train), "test_size": len(X_test),
            "accuracy": round(accuracy_score(y_test, y_pred), 3),
        }
        if len(set(y_test)) > 1:
            metrics["roc_auc"] = round(roc_auc_score(y_test, y_proba), 3)
            metrics["brier_score"] = round(brier_score_loss(y_test, y_proba), 3)
        else:
            metrics["roc_auc"] = None
            metrics["brier_score"] = None
            metrics["warning"] = "Test split has only one outcome class - AUC/Brier not meaningful on this split"

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        self.avg_win = sum(wins) / len(wins) if wins else 0.0
        self.avg_loss = sum(losses) / len(losses) if losses else 0.0
        self.classifier = clf
        self.metrics = metrics
        self.trained_at = dt.datetime.utcnow()
        self.sample_size = len(examples)
        return metrics

    def predict(self, features: dict) -> dict:
        if self.classifier is None:
            raise RuntimeError("Model is not trained")
        x = [[features[name] for name in FEATURE_NAMES]]
        p_win = float(self.classifier.predict_proba(x)[0][1])
        expected_value = p_win * self.avg_win + (1 - p_win) * self.avg_loss
        return {"p_win": round(p_win, 3), "expected_value": round(expected_value, 2),
                "sample_size": self.sample_size}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "classifier": self.classifier, "avg_win": self.avg_win, "avg_loss": self.avg_loss,
            "metrics": self.metrics, "trained_at": self.trained_at, "sample_size": self.sample_size,
        }, path)

    @classmethod
    def load(cls, path: Path) -> "TradeOutcomeModel":
        data = joblib.load(path)
        model = cls()
        model.classifier = data["classifier"]
        model.avg_win = data["avg_win"]
        model.avg_loss = data["avg_loss"]
        model.metrics = data["metrics"]
        model.trained_at = data["trained_at"]
        model.sample_size = data["sample_size"]
        return model
