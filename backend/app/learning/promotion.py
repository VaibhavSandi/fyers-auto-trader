"""
Self-learning promotion loop (Phase 8) - compares a CANDIDATE strategy
version's out-of-sample walk-forward evidence against the current ACTIVE
baseline for the same strategy family, and only promotes the candidate if
it clears concrete, conservative thresholds on real sample size,
expectancy, drawdown, and stability. Every comparison is logged as a
LearningExperiment row, win or lose - the audit trail is never only the
successes, and a rejection is just as recorded as a promotion.

Deliberately NOT built here: automatic hypothesis generation via NLP or
search over indicator combinations, continuous/online learning, or any
live-trading code path that reads a promotion decision. A "hypothesis" is
a short human (or calling code) -supplied text label, not something the
system invents unsupervised - this matches what the master prompt actually
specifies (interpretable, reproducible, versioned decisions), not magic.

Nothing in app/engine/trading_engine.py reads ModelVersion.status yet -
promotion here only updates bookkeeping. Wiring a promoted version into
live/paper trading is a deliberate, separate step (shadow-mode execution
first), not an automatic consequence of this module.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.models import ModelVersion, LearningExperiment

MIN_SAMPLE_TRADES = 20             # per side, before ANY promotion decision is made
MIN_EXPECTANCY_IMPROVEMENT = 0.0   # candidate's expectancy must be at least this much better (Rs./trade)
MAX_DRAWDOWN_TOLERANCE = 1.2       # candidate's max_drawdown_pct may be at most 20% worse than baseline's
MIN_PROFITABLE_FOLD_PCT_FLOOR = 0.0  # candidate's own walk-forward stability floor


def register_model_version(db: Session, *, strategy_name: str, version_label: str, kind: str = "rule_based",
                            parameters: dict | None = None, training_data_summary: dict | None = None,
                            backtest_run_id: int | None = None) -> ModelVersion:
    version = ModelVersion(
        strategy_name=strategy_name, version_label=version_label, kind=kind, status="RESEARCH",
        parameters=parameters or {}, training_data_summary=training_data_summary,
        backtest_run_id=backtest_run_id,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def get_active_version(db: Session, strategy_name: str) -> ModelVersion | None:
    return db.query(ModelVersion).filter_by(strategy_name=strategy_name, status="ACTIVE").first()


def compare_and_decide(db: Session, *, hypothesis: str, strategy_name: str,
                        candidate_version: ModelVersion, candidate_evidence: dict,
                        baseline_version: ModelVersion | None, baseline_evidence: dict | None) -> LearningExperiment:
    """candidate_evidence / baseline_evidence are WalkForwardReport.aggregate
    dicts (overall_out_of_sample{...}, fold_count, profitable_fold_pct, ...)."""
    decision, reason, comparison = _decide(candidate_evidence, baseline_evidence)

    experiment = LearningExperiment(
        hypothesis=hypothesis, strategy_name=strategy_name,
        candidate_version_id=candidate_version.id,
        baseline_version_id=baseline_version.id if baseline_version else None,
        comparison_metrics=comparison, decision=decision, decision_reason=reason,
        decided_at=dt.datetime.utcnow(),
    )
    db.add(experiment)

    if decision == "PROMOTED":
        _promote(db, strategy_name, candidate_version, reason)
    elif decision == "REJECTED":
        candidate_version.status = "REJECTED"
        candidate_version.rejected_reason = reason
        candidate_version.updated_at = dt.datetime.utcnow()
    # INCONCLUSIVE: candidate stays as-is (RESEARCH), no status change -
    # "do not retrain/decide from too little evidence" applies here.

    db.commit()
    db.refresh(experiment)
    return experiment


def _decide(candidate: dict, baseline: dict | None) -> tuple[str, str, dict]:
    comparison = {"candidate": candidate, "baseline": baseline}
    cand_n = candidate.get("overall_out_of_sample", {}).get("total_trades", 0)

    if cand_n < MIN_SAMPLE_TRADES:
        return ("INCONCLUSIVE",
                f"Candidate has only {cand_n} out-of-sample trades - need at least {MIN_SAMPLE_TRADES}",
                comparison)

    cand_metrics = candidate["overall_out_of_sample"]
    cand_dd = cand_metrics.get("max_drawdown_pct", 0.0)
    cand_expectancy = cand_metrics.get("expectancy", 0.0)
    cand_stability = candidate.get("profitable_fold_pct", 0.0)

    if baseline is None:
        # First version for this strategy family - promote on its own
        # merits, still gated by sample size and a basic sanity floor (must
        # be net profitable out-of-sample, not merely "ran without errors").
        if cand_expectancy > 0:
            return ("PROMOTED",
                    f"No existing baseline - candidate is net profitable out-of-sample "
                    f"(expectancy Rs.{cand_expectancy}/trade across {cand_n} trades)",
                    comparison)
        return ("REJECTED",
                f"No existing baseline, but candidate's out-of-sample expectancy is "
                f"Rs.{cand_expectancy}/trade (not profitable)",
                comparison)

    base_n = baseline.get("overall_out_of_sample", {}).get("total_trades", 0)
    if base_n < MIN_SAMPLE_TRADES:
        return ("INCONCLUSIVE",
                f"Baseline has only {base_n} out-of-sample trades - need at least {MIN_SAMPLE_TRADES} "
                f"for a fair comparison",
                comparison)

    base_metrics = baseline["overall_out_of_sample"]
    base_dd = base_metrics.get("max_drawdown_pct", 0.0)
    base_expectancy = base_metrics.get("expectancy", 0.0)

    reasons = []
    ok = True

    if cand_expectancy < base_expectancy + MIN_EXPECTANCY_IMPROVEMENT:
        ok = False
        reasons.append(f"expectancy Rs.{cand_expectancy}/trade does not beat baseline's Rs.{base_expectancy}/trade")

    if base_dd > 0 and cand_dd > base_dd * MAX_DRAWDOWN_TOLERANCE:
        ok = False
        reasons.append(
            f"max drawdown {cand_dd}% exceeds baseline's {base_dd}% by more than the "
            f"{int((MAX_DRAWDOWN_TOLERANCE - 1) * 100)}% tolerance"
        )

    if cand_stability < MIN_PROFITABLE_FOLD_PCT_FLOOR:
        ok = False
        reasons.append(f"only {cand_stability}% of walk-forward folds were profitable")

    if ok:
        return ("PROMOTED",
                f"Beats baseline: expectancy Rs.{cand_expectancy} vs Rs.{base_expectancy}/trade, "
                f"drawdown {cand_dd}% vs {base_dd}%, {cand_n} out-of-sample trades",
                comparison)
    return "REJECTED", "; ".join(reasons), comparison


def _promote(db: Session, strategy_name: str, candidate: ModelVersion, reason: str) -> None:
    now = dt.datetime.utcnow()
    previous_active = get_active_version(db, strategy_name)
    if previous_active is not None and previous_active.id != candidate.id:
        previous_active.status = "PAUSED"
        previous_active.updated_at = now
        candidate.parent_version_id = previous_active.id

    candidate.status = "ACTIVE"
    candidate.promoted_at = now
    candidate.promoted_reason = reason
    candidate.updated_at = now


def rollback(db: Session, strategy_name: str, reason: str) -> ModelVersion | None:
    """Demotes the current ACTIVE version and reactivates its parent (the
    version it replaced), if any - the explicit, logged rollback path
    Phase 8 requires ("support automatic rollback if a newly promoted
    model performs poorly"). Returns the version that is ACTIVE afterward,
    or None if nothing was active / nothing to roll back to."""
    active = get_active_version(db, strategy_name)
    if active is None:
        return None

    now = dt.datetime.utcnow()
    active.status = "REJECTED"
    active.rejected_reason = f"Rolled back: {reason}"
    active.updated_at = now

    if active.parent_version_id:
        parent = db.query(ModelVersion).filter_by(id=active.parent_version_id).first()
        if parent is not None:
            parent.status = "ACTIVE"
            parent.promoted_at = now
            parent.promoted_reason = f"Restored by rollback of {active.version_label}: {reason}"
            parent.updated_at = now
            db.commit()
            return parent

    db.commit()
    return None
