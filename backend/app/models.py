"""
SQLAlchemy ORM models - the full persistent schema for the trading app.

Tables:
  user_settings      - single-row app configuration (capital, risk profile, mode)
  broker_connections - encrypted FYERS tokens + connection state
  market_data        - cached OHLCV candles used by the scanner/strategy
  signals             - every signal the strategy engine evaluated (incl. rejected)
  orders              - every order sent to FYERS or the paper broker
  positions           - open & closed intraday positions
  trades              - the trade journal (one row per completed round-trip)
  risk_events         - every risk-engine decision/block/trip (audit trail)
  system_events       - health/connectivity/engine state transitions
  audit_logs          - generic append-only audit trail of user/engine actions
  daily_statistics    - per-day aggregated performance numbers
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, JSON, ForeignKey
)
from sqlalchemy.orm import relationship

from app.database import Base


def utcnow() -> dt.datetime:
    return dt.datetime.utcnow()


class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, default=1)

    trading_capital = Column(Float, nullable=False, default=10000.0)
    risk_profile = Column(String, nullable=False, default="conservative")  # conservative|balanced|aggressive
    trading_mode = Column(String, nullable=False, default="paper")  # paper|live

    # Derived/overridable safe defaults (auto-calculated when profile/capital changes,
    # but stored explicitly so the user can see & the engine can use a stable value)
    max_risk_per_trade_pct = Column(Float, nullable=False, default=0.5)
    max_daily_loss_pct = Column(Float, nullable=False, default=2.0)
    max_trades_per_day = Column(Integer, nullable=False, default=3)
    max_open_positions = Column(Integer, nullable=False, default=1)
    min_risk_reward = Column(Float, nullable=False, default=1.5)
    max_consecutive_losses = Column(Integer, nullable=False, default=3)

    auto_trading_enabled = Column(Boolean, nullable=False, default=False)
    kill_switch_active = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class BrokerConnection(Base):
    __tablename__ = "broker_connections"

    id = Column(Integer, primary_key=True)
    broker = Column(String, default="fyers")
    client_id_masked = Column(String)
    access_token_encrypted = Column(Text)
    auth_state = Column(String)  # random state used during oauth handshake
    connected = Column(Boolean, default=False)
    connected_at = Column(DateTime)
    token_date = Column(String)  # trading-day the token was issued for (YYYY-MM-DD); FYERS tokens expire daily
    last_validated_at = Column(DateTime)
    last_error = Column(Text)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class MarketData(Base):
    """Locally persisted OHLCV candles - the historical data store used by
    the backtesting/research engine. One row per (symbol, timeframe,
    timestamp); re-syncing the same candle updates it in place rather than
    duplicating it (see the unique index in the migration)."""
    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True, nullable=False)
    timeframe = Column(String, default="5min")
    timestamp = Column(DateTime, index=True, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    source = Column(String, default="fyers_history")  # where this candle came from - never "interpolated"
    is_complete = Column(Boolean, default=True)  # False only for the still-forming current-session candle
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class DataSyncState(Base):
    """Per (symbol, timeframe) historical-data coverage bookkeeping - lets
    incremental syncs fetch only what's actually missing."""
    __tablename__ = "data_sync_state"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False)
    timeframe = Column(String, nullable=False)
    earliest_synced = Column(DateTime)
    latest_synced = Column(DateTime)
    last_sync_at = Column(DateTime)
    last_sync_status = Column(String)  # OK|PARTIAL|ERROR
    last_sync_message = Column(Text)
    candles_stored = Column(Integer, default=0)


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True, nullable=False)
    direction = Column(String)  # BUY|SELL|WAIT|NO_TRADE
    score = Column(Integer)
    max_score = Column(Integer, default=10)
    passed = Column(Boolean, default=False)
    reasons = Column(JSON)  # list[str] human-readable confirmations
    components = Column(JSON)  # dict of sub-scores for explainability
    market_regime = Column(String)
    entry_price = Column(Float)
    stop_loss = Column(Float)
    target = Column(Float)
    risk_per_share = Column(Float)
    reward_per_share = Column(Float)
    risk_reward = Column(Float)
    rejected_reason = Column(Text)
    created_at = Column(DateTime, default=utcnow, index=True)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    client_order_id = Column(String, unique=True, index=True)  # our idempotency key
    broker_order_id = Column(String, index=True)
    symbol = Column(String, index=True, nullable=False)
    side = Column(String)  # BUY|SELL
    order_type = Column(String, default="MARKET")
    quantity = Column(Integer)
    price = Column(Float)
    trigger_price = Column(Float)
    purpose = Column(String)  # ENTRY|STOP_LOSS|TARGET|TRAIL_SL|EOD_SQUAREOFF|MANUAL_CLOSE
    status = Column(String, default="PENDING")  # PENDING|PLACED|FILLED|PARTIAL|REJECTED|CANCELLED|ERROR
    mode = Column(String, default="paper")  # paper|live
    filled_quantity = Column(Integer, default=0)
    average_price = Column(Float)
    raw_response = Column(JSON)
    error_message = Column(Text)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=True)

    created_at = Column(DateTime, default=utcnow, index=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    position = relationship("Position", back_populates="orders")


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True, nullable=False)
    direction = Column(String)  # BUY|SELL
    quantity = Column(Integer)
    entry_price = Column(Float)
    stop_loss = Column(Float)
    original_stop_loss = Column(Float)
    target = Column(Float)
    trailing_active = Column(Boolean, default=False)
    current_price = Column(Float)
    status = Column(String, default="OPEN")  # OPEN|CLOSED|CLOSING
    mode = Column(String, default="paper")
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=True)

    opened_at = Column(DateTime, default=utcnow)
    closed_at = Column(DateTime)
    exit_price = Column(Float)
    exit_reason = Column(String)  # STOP_LOSS|TARGET|TRAILING_STOP|TIME_EXIT|MANUAL|KILL_SWITCH|EOD_SQUAREOFF|SETUP_INVALIDATED
    gross_pnl = Column(Float)
    charges = Column(Float, default=0.0)
    net_pnl = Column(Float)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    orders = relationship("Order", back_populates="position")


class Trade(Base):
    """The trade journal - one immutable row per completed round-trip."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    position_id = Column(Integer, ForeignKey("positions.id"))
    date = Column(String, index=True)  # YYYY-MM-DD
    time_entry = Column(String)
    time_exit = Column(String)
    symbol = Column(String, index=True)
    direction = Column(String)
    entry_price = Column(Float)
    exit_price = Column(Float)
    quantity = Column(Integer)
    stop_loss = Column(Float)
    target = Column(Float)
    exit_reason = Column(String)
    gross_pnl = Column(Float)
    charges = Column(Float)
    net_pnl = Column(Float)
    risk_amount = Column(Float)
    reward_amount = Column(Float)
    risk_reward = Column(Float)
    strategy_score = Column(Integer)
    market_condition = Column(String)
    mode = Column(String)
    explanation = Column(JSON)  # list[str] - "why this trade" for the UI

    created_at = Column(DateTime, default=utcnow)


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id = Column(Integer, primary_key=True)
    event_type = Column(String, index=True)  # DAILY_LOSS_LIMIT|CONSECUTIVE_LOSSES|TRADE_REJECTED|MAX_POSITIONS|KILL_SWITCH|...
    severity = Column(String, default="INFO")  # INFO|WARNING|CRITICAL
    message = Column(Text)
    details = Column(JSON)
    created_at = Column(DateTime, default=utcnow, index=True)


class SystemEvent(Base):
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True)
    component = Column(String, index=True)  # FYERS_API|LIVE_DATA|STRATEGY|RISK_ENGINE|ORDER_MANAGER|POSITION_SYNC|DATABASE|ENGINE
    status = Column(String)  # HEALTHY|DEGRADED|DOWN
    message = Column(Text)
    details = Column(JSON)
    created_at = Column(DateTime, default=utcnow, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    actor = Column(String, default="SYSTEM")  # SYSTEM|USER
    action = Column(String, index=True)
    details = Column(JSON)
    created_at = Column(DateTime, default=utcnow, index=True)


class EngineActivity(Base):
    """One row per trading-engine tick (~every 20s) - the full live detail of
    what the engine actually did that tick, for the dashboard's live feed."""
    __tablename__ = "engine_activity"

    id = Column(Integer, primary_key=True)
    mode = Column(String)  # paper|live
    stage = Column(String, index=True)  # see trading_engine.py Stage constants
    message = Column(Text)
    market_regime = Column(String)
    universe_size = Column(Integer)
    eligible_count = Column(Integer)
    candidates = Column(JSON)  # list[{symbol, direction, score, max_score, passed, rejected_reason}]
    action = Column(String)  # NO_TRADE | ENTERED_BUY | ENTERED_SELL | ERROR
    symbol_acted = Column(String)

    created_at = Column(DateTime, default=utcnow, index=True)


class BacktestRun(Base):
    """One backtest execution - the existing rule-based strategy replayed
    bar-by-bar over locally stored historical data, with no look-ahead."""
    __tablename__ = "backtest_runs"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True, nullable=False)
    timeframe = Column(String)
    start_date = Column(String)
    end_date = Column(String)
    risk_profile = Column(String)
    strategy_name = Column(String, index=True, default="rule_based_v1")
    starting_capital = Column(Float)
    ending_capital = Column(Float)

    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Float)
    gross_profit = Column(Float)
    gross_loss = Column(Float)
    profit_factor = Column(Float)
    expectancy = Column(Float)
    net_pnl = Column(Float)
    avg_win = Column(Float)
    avg_loss = Column(Float)
    max_drawdown = Column(Float)
    max_drawdown_pct = Column(Float)
    sharpe_like = Column(Float)   # per-trade mean/stdev ratio - NOT an annualized Sharpe, see engine.py
    sortino_like = Column(Float)

    strategy_version = Column(String)  # e.g. module hash/tag, for reproducibility
    warnings = Column(JSON)  # e.g. "insufficient index data", "symbol skipped - too few candles"
    status = Column(String, default="COMPLETED")  # COMPLETED|FAILED
    error_message = Column(Text)

    created_at = Column(DateTime, default=utcnow, index=True)


class BacktestTrade(Base):
    """One simulated trade from a BacktestRun - mirrors the live Trade
    journal's shape so the two are directly comparable."""
    __tablename__ = "backtest_trades"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("backtest_runs.id"), index=True)
    symbol = Column(String, index=True)
    direction = Column(String)
    entry_time = Column(DateTime)
    exit_time = Column(DateTime)
    entry_price = Column(Float)
    exit_price = Column(Float)
    quantity = Column(Integer)
    stop_loss = Column(Float)
    target = Column(Float)
    exit_reason = Column(String)
    gross_pnl = Column(Float)
    charges = Column(Float)
    net_pnl = Column(Float)
    strategy_score = Column(Integer)
    market_regime = Column(String)
    reasons = Column(JSON)

    created_at = Column(DateTime, default=utcnow)


class ModelVersion(Base):
    """One trained/versioned strategy configuration or ML model, carried
    through RESEARCH -> VALIDATED -> SHADOW -> ACTIVE (or REJECTED/PAUSED).
    Only one version per strategy_name is ever ACTIVE at a time (enforced
    in app/learning code, not the schema)."""
    __tablename__ = "model_versions"

    id = Column(Integer, primary_key=True)
    strategy_name = Column(String, index=True, nullable=False)
    version_label = Column(String, nullable=False)
    kind = Column(String, default="rule_based")  # rule_based|ml_classifier|ml_regressor
    status = Column(String, default="RESEARCH", index=True)
    parameters = Column(JSON)
    training_data_summary = Column(JSON)
    model_path = Column(String)
    backtest_run_id = Column(Integer, ForeignKey("backtest_runs.id"), nullable=True)
    parent_version_id = Column(Integer, ForeignKey("model_versions.id"), nullable=True)
    promoted_at = Column(DateTime)
    promoted_reason = Column(Text)
    rejected_reason = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class LearningExperiment(Base):
    """One self-learning hypothesis test: a candidate model/strategy
    version compared against the current baseline, with the decision and
    the metrics that produced it - the audit trail for Phase 8."""
    __tablename__ = "learning_experiments"

    id = Column(Integer, primary_key=True)
    hypothesis = Column(Text, nullable=False)
    strategy_name = Column(String, index=True, nullable=False)
    candidate_version_id = Column(Integer, ForeignKey("model_versions.id"), nullable=True)
    baseline_version_id = Column(Integer, ForeignKey("model_versions.id"), nullable=True)
    comparison_metrics = Column(JSON)
    decision = Column(String)  # PROMOTED|REJECTED|INCONCLUSIVE
    decision_reason = Column(Text)
    decided_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow)


class DailyStatistics(Base):
    __tablename__ = "daily_statistics"

    id = Column(Integer, primary_key=True)
    date = Column(String, unique=True, index=True)  # YYYY-MM-DD
    starting_capital = Column(Float)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    gross_pnl = Column(Float, default=0.0)
    charges = Column(Float, default=0.0)
    net_pnl = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    max_consecutive_losses = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    profit_factor = Column(Float, default=0.0)
    avg_win = Column(Float, default=0.0)
    avg_loss = Column(Float, default=0.0)
    trading_stopped_reason = Column(String)
    market_regime_summary = Column(String)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
