"""
Self-learning loop endpoints (Phase 8). Running an experiment here never
changes live/paper trading behavior by itself - it only runs walk-forward
evidence for a candidate vs a baseline strategy and records a logged
promote/reject/inconclusive decision. Wiring a promoted strategy into live
trading is a deliberate, separate step this module does not perform.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import get_settings
from app.models import BacktestTrade, BacktestRun, LearningExperiment, ModelVersion
from app.data.historical import HistoricalDataService
from app.backtest.engine import Backtester
from app.backtest.walkforward import run_walk_forward
from app.engine.trading_engine import engine as trading_engine
from app.learning.diagnostics import diagnose_trades
from app.learning.promotion import register_model_version, get_active_version, compare_and_decide, rollback
from app.learning.scheduler import scheduler as auto_learning_scheduler

router = APIRouter(prefix="/api/learning", tags=["learning"])


@router.get("/auto-status")
def auto_status():
    """Whether the automatic nightly backtest/train/compare pipeline is
    enabled, and when it last attempted to run - see app/learning/scheduler.py.
    This never reflects live/paper trading behavior, since a promoted
    version is never wired into either automatically."""
    return auto_learning_scheduler.status()


@router.get("/diagnose")
def diagnose(strategy_name: str | None = None, db: Session = Depends(get_db)):
    query = db.query(BacktestTrade)
    if strategy_name:
        run_ids = [r.id for r in db.query(BacktestRun.id).filter_by(strategy_name=strategy_name).all()]
        query = query.filter(BacktestTrade.run_id.in_(run_ids))
    trades = query.all()
    return diagnose_trades(trades)


class RunExperimentRequest(BaseModel):
    hypothesis: str
    candidate_strategy_name: str
    baseline_strategy_name: str | None = "rule_based_v1"
    symbol: str
    timeframe: str = "5"
    start_date: str
    end_date: str
    train_days: int = 3
    test_days: int = 2
    embargo_days: int = 1
    capital: float = 10000.0
    risk_profile: str = "conservative"


@router.post("/experiment")
def run_experiment(payload: RunExperimentRequest, db: Session = Depends(get_db)):
    try:
        start = dt.date.fromisoformat(payload.start_date)
        end = dt.date.fromisoformat(payload.end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="start_date/end_date must be YYYY-MM-DD")

    data_service = HistoricalDataService(db, trading_engine._fyers_client)
    backtester = Backtester(data_service, get_settings())
    wf_kwargs = dict(
        symbol=payload.symbol, timeframe=payload.timeframe, overall_start=start, overall_end=end,
        train_days=payload.train_days, test_days=payload.test_days, embargo_days=payload.embargo_days,
        capital=payload.capital, risk_profile=payload.risk_profile,
    )

    candidate_report = run_walk_forward(backtester, strategy_name=payload.candidate_strategy_name, **wf_kwargs)
    candidate_version = register_model_version(
        db, strategy_name=payload.candidate_strategy_name,
        version_label=f"{payload.candidate_strategy_name}-{dt.datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        kind="rule_based", parameters={"symbol": payload.symbol, "timeframe": payload.timeframe},
        training_data_summary=candidate_report.aggregate,
    )

    baseline_version = None
    baseline_evidence = None
    same_family = payload.baseline_strategy_name == payload.candidate_strategy_name
    if payload.baseline_strategy_name and not same_family:
        baseline_version = get_active_version(db, payload.baseline_strategy_name)
        baseline_report = run_walk_forward(backtester, strategy_name=payload.baseline_strategy_name, **wf_kwargs)
        baseline_evidence = baseline_report.aggregate
        if baseline_version is None:
            # No promoted baseline exists yet - register a reference point
            # so the comparison still has something concrete to log against.
            baseline_version = register_model_version(
                db, strategy_name=payload.baseline_strategy_name,
                version_label=f"{payload.baseline_strategy_name}-reference",
                kind="rule_based", training_data_summary=baseline_evidence,
            )

    experiment = compare_and_decide(
        db, hypothesis=payload.hypothesis, strategy_name=payload.candidate_strategy_name,
        candidate_version=candidate_version, candidate_evidence=candidate_report.aggregate,
        baseline_version=baseline_version, baseline_evidence=baseline_evidence,
    )

    return {
        "experiment_id": experiment.id, "decision": experiment.decision,
        "decision_reason": experiment.decision_reason,
        "candidate_version_id": candidate_version.id, "candidate_evidence": candidate_report.aggregate,
        "baseline_version_id": baseline_version.id if baseline_version else None,
        "baseline_evidence": baseline_evidence,
        "candidate_warnings": candidate_report.warnings,
    }


@router.get("/experiments")
def list_experiments(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.query(LearningExperiment).order_by(LearningExperiment.id.desc()).limit(limit).all()
    return [{
        "id": r.id, "hypothesis": r.hypothesis, "strategy_name": r.strategy_name,
        "candidate_version_id": r.candidate_version_id, "baseline_version_id": r.baseline_version_id,
        "decision": r.decision, "decision_reason": r.decision_reason, "decided_at": r.decided_at,
        "created_at": r.created_at,
    } for r in rows]


class RollbackRequest(BaseModel):
    strategy_name: str
    reason: str


@router.post("/rollback")
def rollback_strategy(payload: RollbackRequest, db: Session = Depends(get_db)):
    restored = rollback(db, payload.strategy_name, payload.reason)
    return {
        "strategy_name": payload.strategy_name,
        "restored_version_id": restored.id if restored else None,
        "restored_version_label": restored.version_label if restored else None,
    }


@router.get("/active")
def list_active_versions(db: Session = Depends(get_db)):
    rows = db.query(ModelVersion).filter_by(status="ACTIVE").all()
    return [{"strategy_name": r.strategy_name, "version_label": r.version_label, "id": r.id,
             "promoted_at": r.promoted_at, "promoted_reason": r.promoted_reason} for r in rows]
