"""
Training orchestration - runs TradeOutcomeModel.train() and registers the
result as a new RESEARCH-status ModelVersion. Training NEVER sets a model
to ACTIVE - promotion is a separate, explicit, evidence-gated step
(app/learning/promotion.py), never a side effect of training.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ModelVersion
from app.data.historical import HistoricalDataService
from app.ml.trade_outcome_model import TradeOutcomeModel, build_training_set, MODEL_DIR_NAME, MIN_TRAINING_EXAMPLES
from app.ml.features import FEATURE_NAMES


def train_and_register(db: Session, data_service: HistoricalDataService, strategy_name: str) -> ModelVersion:
    examples = build_training_set(db, data_service)
    model = TradeOutcomeModel()
    metrics = model.train(examples)  # raises ValueError if too few examples - never trains on too little silently

    settings = get_settings()
    models_dir = settings.database_path.parent / MODEL_DIR_NAME
    filename = f"trade_outcome_{strategy_name}_{dt.datetime.utcnow().strftime('%Y%m%d%H%M%S')}.joblib"
    path = models_dir / filename
    model.save(path)

    version = ModelVersion(
        strategy_name=strategy_name, version_label=filename.replace(".joblib", ""),
        kind="ml_classifier", status="RESEARCH",
        parameters={"features": FEATURE_NAMES, "model_type": "LogisticRegression", "class_weight": "balanced"},
        training_data_summary={"sample_size": len(examples), "min_required": MIN_TRAINING_EXAMPLES, **metrics},
        model_path=str(path),
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version
