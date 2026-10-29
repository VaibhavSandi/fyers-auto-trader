-- Initial schema for FYERS Auto Trader
-- This file is applied once by migrations/migrate.py and tracked in schema_migrations.
-- SQLAlchemy models (app/models.py) are the source of truth; this file gives an explicit,
-- reviewable migration history as required for "clean database architecture".

CREATE TABLE IF NOT EXISTS user_settings (
    id INTEGER PRIMARY KEY,
    trading_capital REAL NOT NULL DEFAULT 10000.0,
    risk_profile TEXT NOT NULL DEFAULT 'conservative',
    trading_mode TEXT NOT NULL DEFAULT 'paper',
    max_risk_per_trade_pct REAL NOT NULL DEFAULT 0.5,
    max_daily_loss_pct REAL NOT NULL DEFAULT 2.0,
    max_trades_per_day INTEGER NOT NULL DEFAULT 3,
    max_open_positions INTEGER NOT NULL DEFAULT 1,
    min_risk_reward REAL NOT NULL DEFAULT 1.5,
    max_consecutive_losses INTEGER NOT NULL DEFAULT 3,
    auto_trading_enabled BOOLEAN NOT NULL DEFAULT 0,
    kill_switch_active BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS broker_connections (
    id INTEGER PRIMARY KEY,
    broker TEXT DEFAULT 'fyers',
    client_id_masked TEXT,
    access_token_encrypted TEXT,
    auth_state TEXT,
    connected BOOLEAN DEFAULT 0,
    connected_at DATETIME,
    token_date TEXT,
    last_validated_at DATETIME,
    last_error TEXT,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS market_data (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT DEFAULT '5min',
    timestamp DATETIME NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    created_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_market_data_symbol ON market_data (symbol);
CREATE INDEX IF NOT EXISTS ix_market_data_timestamp ON market_data (timestamp);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    direction TEXT,
    score INTEGER,
    max_score INTEGER DEFAULT 10,
    passed BOOLEAN DEFAULT 0,
    reasons TEXT,
    components TEXT,
    market_regime TEXT,
    entry_price REAL, stop_loss REAL, target REAL,
    risk_per_share REAL, reward_per_share REAL, risk_reward REAL,
    rejected_reason TEXT,
    created_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_signals_symbol ON signals (symbol);
CREATE INDEX IF NOT EXISTS ix_signals_created_at ON signals (created_at);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    direction TEXT,
    quantity INTEGER,
    entry_price REAL,
    stop_loss REAL,
    original_stop_loss REAL,
    target REAL,
    trailing_active BOOLEAN DEFAULT 0,
    current_price REAL,
    status TEXT DEFAULT 'OPEN',
    mode TEXT DEFAULT 'paper',
    signal_id INTEGER,
    opened_at DATETIME,
    closed_at DATETIME,
    exit_price REAL,
    exit_reason TEXT,
    gross_pnl REAL,
    charges REAL DEFAULT 0.0,
    net_pnl REAL,
    created_at DATETIME,
    updated_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_positions_symbol ON positions (symbol);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    client_order_id TEXT UNIQUE,
    broker_order_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT,
    order_type TEXT DEFAULT 'MARKET',
    quantity INTEGER,
    price REAL,
    trigger_price REAL,
    purpose TEXT,
    status TEXT DEFAULT 'PENDING',
    mode TEXT DEFAULT 'paper',
    filled_quantity INTEGER DEFAULT 0,
    average_price REAL,
    raw_response TEXT,
    error_message TEXT,
    position_id INTEGER REFERENCES positions(id),
    created_at DATETIME,
    updated_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_orders_client_order_id ON orders (client_order_id);
CREATE INDEX IF NOT EXISTS ix_orders_broker_order_id ON orders (broker_order_id);
CREATE INDEX IF NOT EXISTS ix_orders_symbol ON orders (symbol);
CREATE INDEX IF NOT EXISTS ix_orders_created_at ON orders (created_at);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    position_id INTEGER REFERENCES positions(id),
    date TEXT,
    time_entry TEXT,
    time_exit TEXT,
    symbol TEXT,
    direction TEXT,
    entry_price REAL,
    exit_price REAL,
    quantity INTEGER,
    stop_loss REAL,
    target REAL,
    exit_reason TEXT,
    gross_pnl REAL,
    charges REAL,
    net_pnl REAL,
    risk_amount REAL,
    reward_amount REAL,
    risk_reward REAL,
    strategy_score INTEGER,
    market_condition TEXT,
    mode TEXT,
    explanation TEXT,
    created_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_trades_date ON trades (date);
CREATE INDEX IF NOT EXISTS ix_trades_symbol ON trades (symbol);

CREATE TABLE IF NOT EXISTS risk_events (
    id INTEGER PRIMARY KEY,
    event_type TEXT,
    severity TEXT DEFAULT 'INFO',
    message TEXT,
    details TEXT,
    created_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_risk_events_event_type ON risk_events (event_type);
CREATE INDEX IF NOT EXISTS ix_risk_events_created_at ON risk_events (created_at);

CREATE TABLE IF NOT EXISTS system_events (
    id INTEGER PRIMARY KEY,
    component TEXT,
    status TEXT,
    message TEXT,
    details TEXT,
    created_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_system_events_component ON system_events (component);
CREATE INDEX IF NOT EXISTS ix_system_events_created_at ON system_events (created_at);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY,
    actor TEXT DEFAULT 'SYSTEM',
    action TEXT,
    details TEXT,
    created_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_audit_logs_action ON audit_logs (action);
CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs (created_at);

CREATE TABLE IF NOT EXISTS daily_statistics (
    id INTEGER PRIMARY KEY,
    date TEXT UNIQUE,
    starting_capital REAL,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    gross_pnl REAL DEFAULT 0.0,
    charges REAL DEFAULT 0.0,
    net_pnl REAL DEFAULT 0.0,
    max_drawdown REAL DEFAULT 0.0,
    max_consecutive_losses INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0.0,
    profit_factor REAL DEFAULT 0.0,
    avg_win REAL DEFAULT 0.0,
    avg_loss REAL DEFAULT 0.0,
    trading_stopped_reason TEXT,
    market_regime_summary TEXT,
    created_at DATETIME,
    updated_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_daily_statistics_date ON daily_statistics (date);
