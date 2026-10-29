"""
ML training/inspection endpoints (Phase 4/6). Nothing here is wired into
live or paper trading - these models are research/advisory only until a
future promotion step (Phase 8) explicitly validates and activates one.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ModelVersion
from app.data.historical import HistoricalDataService
from app.engine.trading_engine import engine as trading_engine
from app.ml.training import train_and_register
from app.ml.trade_outcome_model import TradeOutcomeModel

router = APIRouter(prefix="/api/ml", tags=["ml"])


class TrainRequest(BaseModel):
    strategy_name: str = "rule_based_v1"


@router.post("/train")
def train_model(payload: TrainRequest, db: Session = Depends(get_db)):
    data_service = HistoricalDataService(db, trading_engine._fyers_client)
    try:
        version = train_and_register(db, data_service, payload.strategy_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "model_version_id": version.id, "version_label": version.version_label,
        "status": version.status, "training_data_summary": version.training_data_summary,
    }


@router.get("/models")
def list_models(db: Session = Depends(get_db)):
    rows = db.query(ModelVersion).order_by(ModelVersion.id.desc()).all()
    return [_summary(r) for r in rows]


class PredictRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    model_version_id: int
    features: dict


@router.post("/predict")
def predict(payload: PredictRequest, db: Session = Depends(get_db)):
    version = db.query(ModelVersion).filter_by(id=payload.model_version_id).first()
    if version is None or not version.model_path:
        raise HTTPException(status_code=404, detail="Model version not found or has no saved artifact")

    from pathlib import Path
    model = TradeOutcomeModel.load(Path(version.model_path))
    try:
        result = model.predict(payload.features)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Missing required feature: {exc}")
    return {**result, "model_version_id": version.id, "status": version.status}


def _summary(r: ModelVersion) -> dict:
    return {
        "id": r.id, "strategy_name": r.strategy_name, "version_label": r.version_label, "kind": r.kind,
        "status": r.status, "training_data_summary": r.training_data_summary,
        "promoted_at": r.promoted_at, "promoted_reason": r.promoted_reason, "rejected_reason": r.rejected_reason,
        "created_at": r.created_at,
    }
