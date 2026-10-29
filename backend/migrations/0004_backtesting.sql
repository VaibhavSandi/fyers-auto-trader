-- Backtesting engine (Phase 3): stores each backtest run's configuration,
-- aggregate metrics, and every simulated trade, so results are reproducible
-- and reviewable later rather than only existing in a single API response.

CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT,
    start_date TEXT,
    end_date TEXT,
    risk_profile TEXT,
    starting_capital REAL,
    ending_capital REAL,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    win_rate REAL,
    gross_profit REAL,
    gross_loss REAL,
    profit_factor REAL,
    expectancy REAL,
    net_pnl REAL,
    avg_win REAL,
    avg_loss REAL,
    max_drawdown REAL,
    max_drawdown_pct REAL,
    sharpe_like REAL,
    sortino_like REAL,
    strategy_version TEXT,
    warnings TEXT,
    status TEXT DEFAULT 'COMPLETED',
    error_message TEXT,
    created_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_backtest_runs_symbol ON backtest_runs (symbol);
CREATE INDEX IF NOT EXISTS ix_backtest_runs_created_at ON backtest_runs (created_at);

CREATE TABLE IF NOT EXISTS backtest_trades (
    id INTEGER PRIMARY KEY,
    run_id INTEGER REFERENCES backtest_runs(id),
    symbol TEXT,
    direction TEXT,
    entry_time DATETIME,
    exit_time DATETIME,
    entry_price REAL,
    exit_price REAL,
    quantity INTEGER,
    stop_loss REAL,
    target REAL,
    exit_reason TEXT,
    gross_pnl REAL,
    charges REAL,
    net_pnl REAL,
    strategy_score INTEGER,
    market_regime TEXT,
    reasons TEXT,
    created_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_backtest_trades_run_id ON backtest_trades (run_id);
