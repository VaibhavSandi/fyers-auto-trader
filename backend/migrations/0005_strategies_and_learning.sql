-- Phase 4 (pluggable strategies) + schema groundwork for Phase 8
-- (self-learning promotion loop) and Phase 11 (model/experiment tracking).

ALTER TABLE backtest_runs ADD COLUMN strategy_name TEXT DEFAULT 'rule_based_v1';
CREATE INDEX IF NOT EXISTS ix_backtest_runs_strategy_name ON backtest_runs (strategy_name);

-- One row per trained/versioned model-or-strategy-configuration. A
-- "version" here can be as simple as a named strategy at its current
-- constants, or (once the ML pipeline exists) an actual trained model
-- artifact reference - both go through the same promote/reject lifecycle.
CREATE TABLE IF NOT EXISTS model_versions (
    id INTEGER PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    version_label TEXT NOT NULL,
    kind TEXT DEFAULT 'rule_based',  -- rule_based | ml_classifier | ml_regressor
    status TEXT DEFAULT 'RESEARCH',  -- RESEARCH|VALIDATED|SHADOW|ACTIVE|REJECTED|PAUSED
    parameters TEXT,                 -- JSON: strategy constants / hyperparameters used
    training_data_summary TEXT,      -- JSON: symbols, date range, candle/sample counts
    model_path TEXT,                 -- filesystem path to a serialized model, if any (ml kind)
    backtest_run_id INTEGER REFERENCES backtest_runs(id),
    parent_version_id INTEGER REFERENCES model_versions(id),
    promoted_at DATETIME,
    promoted_reason TEXT,
    rejected_reason TEXT,
    created_at DATETIME,
    updated_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_model_versions_strategy_name ON model_versions (strategy_name);
CREATE INDEX IF NOT EXISTS ix_model_versions_status ON model_versions (status);

-- One row per self-learning hypothesis test: candidate vs the currently
-- active baseline, with the side-by-side comparison that produced the
-- promote/reject decision - the audit trail Phase 8 and Phase 10 need.
CREATE TABLE IF NOT EXISTS learning_experiments (
    id INTEGER PRIMARY KEY,
    hypothesis TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    candidate_version_id INTEGER REFERENCES model_versions(id),
    baseline_version_id INTEGER REFERENCES model_versions(id),
    comparison_metrics TEXT,  -- JSON: {candidate: {...}, baseline: {...}, deltas: {...}}
    decision TEXT,            -- PROMOTED | REJECTED | INCONCLUSIVE
    decision_reason TEXT,
    decided_at DATETIME,
    created_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_learning_experiments_strategy_name ON learning_experiments (strategy_name);
