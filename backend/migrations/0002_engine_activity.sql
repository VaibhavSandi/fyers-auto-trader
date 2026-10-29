-- Adds the live engine-activity feed: one row per trading-engine tick,
-- showing exactly what that tick did (market regime, candidates scanned
-- and scored, and the final action taken).

CREATE TABLE IF NOT EXISTS engine_activity (
    id INTEGER PRIMARY KEY,
    mode TEXT,
    stage TEXT,
    message TEXT,
    market_regime TEXT,
    universe_size INTEGER,
    eligible_count INTEGER,
    candidates TEXT,
    action TEXT,
    symbol_acted TEXT,
    created_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_engine_activity_stage ON engine_activity (stage);
CREATE INDEX IF NOT EXISTS ix_engine_activity_created_at ON engine_activity (created_at);
