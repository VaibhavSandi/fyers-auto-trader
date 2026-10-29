from app.learning.promotion import (
    register_model_version, get_active_version, compare_and_decide, rollback, MIN_SAMPLE_TRADES,
)
from app.learning.diagnostics import diagnose_trades
from app.models import LearningExperiment, ModelVersion, BacktestTrade


def _evidence(total_trades: int, expectancy: float, max_drawdown_pct: float = 5.0,
              profitable_fold_pct: float = 50.0) -> dict:
    return {
        "fold_count": 3, "profitable_fold_pct": profitable_fold_pct,
        "overall_out_of_sample": {
            "total_trades": total_trades, "expectancy": expectancy, "max_drawdown_pct": max_drawdown_pct,
            "net_pnl": expectancy * total_trades, "win_rate": 50.0, "profit_factor": 1.2,
        },
    }


def test_no_baseline_profitable_candidate_is_promoted(db_session, user_settings):
    candidate = register_model_version(db_session, strategy_name="strat_a", version_label="v1")
    evidence = _evidence(total_trades=MIN_SAMPLE_TRADES, expectancy=10.0)

    experiment = compare_and_decide(
        db_session, hypothesis="test hypothesis", strategy_name="strat_a",
        candidate_version=candidate, candidate_evidence=evidence,
        baseline_version=None, baseline_evidence=None,
    )

    assert experiment.decision == "PROMOTED"
    db_session.refresh(candidate)
    assert candidate.status == "ACTIVE"
    assert candidate.promoted_reason is not None


def test_no_baseline_unprofitable_candidate_is_rejected(db_session, user_settings):
    candidate = register_model_version(db_session, strategy_name="strat_b", version_label="v1")
    evidence = _evidence(total_trades=MIN_SAMPLE_TRADES, expectancy=-5.0)

    experiment = compare_and_decide(
        db_session, hypothesis="h", strategy_name="strat_b",
        candidate_version=candidate, candidate_evidence=evidence,
        baseline_version=None, baseline_evidence=None,
    )

    assert experiment.decision == "REJECTED"
    db_session.refresh(candidate)
    assert candidate.status == "REJECTED"
    assert candidate.rejected_reason is not None


def test_candidate_below_minimum_sample_is_inconclusive_and_unchanged(db_session, user_settings):
    candidate = register_model_version(db_session, strategy_name="strat_c", version_label="v1")
    evidence = _evidence(total_trades=MIN_SAMPLE_TRADES - 1, expectancy=50.0)

    experiment = compare_and_decide(
        db_session, hypothesis="h", strategy_name="strat_c",
        candidate_version=candidate, candidate_evidence=evidence,
        baseline_version=None, baseline_evidence=None,
    )

    assert experiment.decision == "INCONCLUSIVE"
    db_session.refresh(candidate)
    assert candidate.status == "RESEARCH"  # unchanged


def test_baseline_below_minimum_sample_is_inconclusive(db_session, user_settings):
    candidate = register_model_version(db_session, strategy_name="strat_d", version_label="v1")
    baseline = register_model_version(db_session, strategy_name="strat_d_base", version_label="base")
    cand_evidence = _evidence(total_trades=MIN_SAMPLE_TRADES, expectancy=10.0)
    base_evidence = _evidence(total_trades=MIN_SAMPLE_TRADES - 5, expectancy=5.0)

    experiment = compare_and_decide(
        db_session, hypothesis="h", strategy_name="strat_d",
        candidate_version=candidate, candidate_evidence=cand_evidence,
        baseline_version=baseline, baseline_evidence=base_evidence,
    )
    assert experiment.decision == "INCONCLUSIVE"


def test_candidate_beats_baseline_on_everything_is_promoted_and_demotes_old_active(db_session, user_settings):
    baseline = register_model_version(db_session, strategy_name="strat_e", version_label="v1")
    baseline.status = "ACTIVE"
    db_session.commit()

    candidate = register_model_version(db_session, strategy_name="strat_e", version_label="v2")
    cand_evidence = _evidence(total_trades=MIN_SAMPLE_TRADES, expectancy=20.0, max_drawdown_pct=4.0)
    base_evidence = _evidence(total_trades=MIN_SAMPLE_TRADES, expectancy=5.0, max_drawdown_pct=5.0)

    experiment = compare_and_decide(
        db_session, hypothesis="candidate improves expectancy", strategy_name="strat_e",
        candidate_version=candidate, candidate_evidence=cand_evidence,
        baseline_version=baseline, baseline_evidence=base_evidence,
    )

    assert experiment.decision == "PROMOTED"
    db_session.refresh(candidate)
    db_session.refresh(baseline)
    assert candidate.status == "ACTIVE"
    assert baseline.status == "PAUSED"
    assert candidate.parent_version_id == baseline.id
    # only one ACTIVE version per strategy_name
    assert get_active_version(db_session, "strat_e").id == candidate.id


def test_candidate_with_worse_expectancy_is_rejected(db_session, user_settings):
    baseline = register_model_version(db_session, strategy_name="strat_f", version_label="v1")
    baseline.status = "ACTIVE"
    db_session.commit()
    candidate = register_model_version(db_session, strategy_name="strat_f", version_label="v2")

    cand_evidence = _evidence(total_trades=MIN_SAMPLE_TRADES, expectancy=2.0)
    base_evidence = _evidence(total_trades=MIN_SAMPLE_TRADES, expectancy=20.0)

    experiment = compare_and_decide(
        db_session, hypothesis="h", strategy_name="strat_f",
        candidate_version=candidate, candidate_evidence=cand_evidence,
        baseline_version=baseline, baseline_evidence=base_evidence,
    )
    assert experiment.decision == "REJECTED"
    assert "expectancy" in experiment.decision_reason
    db_session.refresh(baseline)
    assert baseline.status == "ACTIVE"  # untouched - rejection never demotes the baseline


def test_candidate_with_excessive_drawdown_is_rejected_even_with_better_expectancy(db_session, user_settings):
    baseline = register_model_version(db_session, strategy_name="strat_g", version_label="v1")
    baseline.status = "ACTIVE"
    db_session.commit()
    candidate = register_model_version(db_session, strategy_name="strat_g", version_label="v2")

    cand_evidence = _evidence(total_trades=MIN_SAMPLE_TRADES, expectancy=50.0, max_drawdown_pct=20.0)
    base_evidence = _evidence(total_trades=MIN_SAMPLE_TRADES, expectancy=10.0, max_drawdown_pct=5.0)

    experiment = compare_and_decide(
        db_session, hypothesis="h", strategy_name="strat_g",
        candidate_version=candidate, candidate_evidence=cand_evidence,
        baseline_version=baseline, baseline_evidence=base_evidence,
    )
    assert experiment.decision == "REJECTED"
    assert "drawdown" in experiment.decision_reason


def test_every_decision_is_logged_as_a_learning_experiment(db_session, user_settings):
    candidate = register_model_version(db_session, strategy_name="strat_h", version_label="v1")
    evidence = _evidence(total_trades=MIN_SAMPLE_TRADES, expectancy=10.0)
    compare_and_decide(db_session, hypothesis="logged?", strategy_name="strat_h",
                        candidate_version=candidate, candidate_evidence=evidence,
                        baseline_version=None, baseline_evidence=None)

    rows = db_session.query(LearningExperiment).filter_by(strategy_name="strat_h").all()
    assert len(rows) == 1
    assert rows[0].hypothesis == "logged?"
    assert rows[0].comparison_metrics is not None


def test_rollback_restores_the_parent_version(db_session, user_settings):
    v1 = register_model_version(db_session, strategy_name="strat_i", version_label="v1")
    v1.status = "ACTIVE"
    db_session.commit()
    v2 = register_model_version(db_session, strategy_name="strat_i", version_label="v2")
    evidence = _evidence(total_trades=MIN_SAMPLE_TRADES, expectancy=20.0, max_drawdown_pct=4.0)
    base_evidence = _evidence(total_trades=MIN_SAMPLE_TRADES, expectancy=5.0, max_drawdown_pct=5.0)
    compare_and_decide(db_session, hypothesis="h", strategy_name="strat_i",
                        candidate_version=v2, candidate_evidence=evidence,
                        baseline_version=v1, baseline_evidence=base_evidence)
    db_session.refresh(v2)
    assert v2.status == "ACTIVE"

    restored = rollback(db_session, "strat_i", "v2 underperformed live")
    assert restored is not None
    assert restored.id == v1.id
    db_session.refresh(v1)
    db_session.refresh(v2)
    assert v1.status == "ACTIVE"
    assert v2.status == "REJECTED"
    assert "Rolled back" in v2.rejected_reason


def test_rollback_with_no_parent_returns_none_but_still_demotes(db_session, user_settings):
    v1 = register_model_version(db_session, strategy_name="strat_j", version_label="v1")
    v1.status = "ACTIVE"
    db_session.commit()

    restored = rollback(db_session, "strat_j", "bad performance")
    assert restored is None
    db_session.refresh(v1)
    assert v1.status == "REJECTED"


def test_rollback_on_strategy_with_no_active_version_is_a_noop(db_session, user_settings):
    assert rollback(db_session, "strat_never_existed", "n/a") is None


def test_diagnose_trades_groups_by_regime_and_exit_reason(db_session):
    trades = [
        BacktestTrade(run_id=1, symbol="X", net_pnl=50.0, market_regime="BULLISH", exit_reason="TARGET", strategy_score=8),
        BacktestTrade(run_id=1, symbol="X", net_pnl=-30.0, market_regime="BULLISH", exit_reason="STOP_LOSS", strategy_score=7),
        BacktestTrade(run_id=1, symbol="X", net_pnl=-20.0, market_regime="BEARISH", exit_reason="STOP_LOSS", strategy_score=6),
    ]
    report = diagnose_trades(trades)
    assert report["total_trades_analyzed"] == 3
    assert report["by_market_regime"]["BULLISH"]["total"] == 2
    assert report["by_market_regime"]["BULLISH"]["wins"] == 1
    assert report["by_exit_reason"]["STOP_LOSS"]["total"] == 2
    assert report["by_market_regime"]["BEARISH"]["win_rate"] == 0.0


def test_diagnose_trades_handles_empty_list():
    report = diagnose_trades([])
    assert report["total_trades_analyzed"] == 0
    assert report["by_market_regime"] == {}
