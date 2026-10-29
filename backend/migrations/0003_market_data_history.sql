-- Turns market_data into a real historical data store: adds provenance
-- columns and a uniqueness guarantee so re-syncing a candle updates it in
-- place instead of creating duplicates (requirement: no duplicate candles,
-- no invented/interpolated prices - only what FYERS actually returned).

ALTER TABLE market_data ADD COLUMN source TEXT DEFAULT 'fyers_history';
ALTER TABLE market_data ADD COLUMN is_complete BOOLEAN DEFAULT 1;
ALTER TABLE market_data ADD COLUMN updated_at DATETIME;

CREATE UNIQUE INDEX IF NOT EXISTS ux_market_data_symbol_tf_ts
    ON market_data (symbol, timeframe, timestamp);

-- Tracks per-symbol/timeframe sync coverage so incremental syncs only
-- fetch what's actually missing, instead of re-downloading everything.
CREATE TABLE IF NOT EXISTS data_sync_state (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    earliest_synced DATETIME,
    latest_synced DATETIME,
    last_sync_at DATETIME,
    last_sync_status TEXT,
    last_sync_message TEXT,
    candles_stored INTEGER DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_data_sync_state_symbol_tf
    ON data_sync_state (symbol, timeframe);
