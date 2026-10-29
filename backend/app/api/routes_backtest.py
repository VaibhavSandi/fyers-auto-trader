"""
Backtesting endpoints (Phase 3). Runs the EXISTING rule-based strategy
against locally stored historical data - no FYERS calls happen here at all,
so this works even while disconnected, and never touches the live rate
limit budget.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import get_settings
from app.models import BacktestRun, BacktestTrade
from app.data.historical import HistoricalDataService
from app.backtest.engine import Backtester
from app.backtest.walkforward import run_walk_forward
from app.engine.trading_engine import engine as trading_engine
from app.strategies.registry import list_strategies, DEFAULT_STRATEGY

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    symbol: str
    timeframe: str = "5"
    start_date: str  # YYYY-MM-DD
    end_date: str
    capital: float = 10000.0
    risk_profile: str = "conservative"
    strategy_name: str = DEFAULT_STRATEGY


@router.get("/strategies")
def get_strategies():
    return list_strategies()


class WalkForwardRequest(BaseModel):
    symbol: str
    timeframe: str = "5"
    start_date: str
    end_date: str
    train_days: int = 3
    test_days: int = 2
    embargo_days: int = 1
    capital: float = 10000.0
    risk_profile: str = "conservative"
    strategy_name: str = DEFAULT_STRATEGY


@router.post("/walk-forward")
def walk_forward(payload: WalkForwardRequest, db: Session = Depends(get_db)):
    try:
        start = dt.date.fromisoformat(payload.start_date)
        end = dt.date.fromisoformat(payload.end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="start_date/end_date must be YYYY-MM-DD")

    data_service = HistoricalDataService(db, trading_engine._fyers_client)
    backtester = Backtester(data_service, get_settings())

    report = run_walk_forward(
        backtester, symbol=payload.symbol, timeframe=payload.timeframe, overall_start=start, overall_end=end,
        train_days=payload.train_days, test_days=payload.test_days, embargo_days=payload.embargo_days,
        capital=payload.capital, risk_profile=payload.risk_profile, strategy_name=payload.strategy_name,
    )

    return {
        "symbol": report.symbol, "strategy_name": report.strategy_name, "warnings": report.warnings,
        "aggregate": report.aggregate,
        "folds": [{
            "fold_index": f.fold_index, "train_start": f.train_start, "train_end": f.train_end,
            "test_start": f.test_start, "test_end": f.test_end, "metrics": f.result.metrics,
            "baseline_net_pnl": f.baseline_net_pnl,
        } for f in report.folds],
    }


@router.post("/run")
def run_backtest(payload: BacktestRequest, db: Session = Depends(get_db)):
    try:
        start = dt.date.fromisoformat(payload.start_date)
        end = dt.date.fromisoformat(payload.end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="start_date/end_date must be YYYY-MM-DD")
    if start > end:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")

    # The backtester reads only the LOCAL historical store - a FYERS client
    # is accepted but never actually called from here (get_candles() never
    # hits the network); passing the live one just lets the same
    # HistoricalDataService be reused without a separate "offline" variant.
    data_service = HistoricalDataService(db, trading_engine._fyers_client)
    backtester = Backtester(data_service, get_settings())

    try:
        result = backtester.run(
            symbol=payload.symbol, timeframe=payload.timeframe, start=start, end=end,
            capital=payload.capital, risk_profile=payload.risk_profile, strategy_name=payload.strategy_name,
        )
    except Exception as exc:
        run = BacktestRun(
            symbol=payload.symbol, timeframe=payload.timeframe, start_date=payload.start_date,
            end_date=payload.end_date, risk_profile=payload.risk_profile, strategy_name=payload.strategy_name,
            starting_capital=payload.capital, status="FAILED", error_message=str(exc),
        )
        db.add(run)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Backtest failed: {exc}")

    m = result.metrics
    run = BacktestRun(
        symbol=result.symbol, timeframe=result.timeframe, start_date=result.start_date, end_date=result.end_date,
        risk_profile=result.risk_profile, starting_capital=result.starting_capital, ending_capital=result.ending_capital,
        total_trades=m["total_trades"], winning_trades=m["winning_trades"], losing_trades=m["losing_trades"],
        win_rate=m["win_rate"], gross_profit=m["gross_profit"], gross_loss=m["gross_loss"],
        profit_factor=m["profit_factor"], expectancy=m["expectancy"], net_pnl=m["net_pnl"],
        avg_win=m["avg_win"], avg_loss=m["avg_loss"], max_drawdown=m["max_drawdown"],
        max_drawdown_pct=m["max_drawdown_pct"], sharpe_like=m["sharpe_like"], sortino_like=m["sortino_like"],
        strategy_name=result.strategy_name, strategy_version=result.strategy_name, warnings=result.warnings,
        status="COMPLETED",
    )
    db.add(run)
    db.commit()

    for t in result.trades:
        db.add(BacktestTrade(
            run_id=run.id, symbol=result.symbol, direction=t.direction, entry_time=t.entry_time,
            exit_time=t.exit_time, entry_price=t.entry_price, exit_price=t.exit_price, quantity=t.quantity,
            stop_loss=t.original_stop_loss, target=t.target, exit_reason=t.exit_reason,
            gross_pnl=t.gross_pnl, charges=t.charges, net_pnl=t.net_pnl, strategy_score=t.score,
            market_regime=t.market_regime, reasons=t.reasons,
        ))
    db.commit()

    return {"run_id": run.id, "metrics": m, "warnings": result.warnings, "trade_count": len(result.trades)}


@router.get("")
def list_backtests(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.query(BacktestRun).order_by(BacktestRun.id.desc()).limit(limit).all()
    return [_run_summary(r) for r in rows]


@router.get("/{run_id}")
def get_backtest(run_id: int, db: Session = Depends(get_db)):
    run = db.query(BacktestRun).filter_by(id=run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    trades = db.query(BacktestTrade).filter_by(run_id=run_id).order_by(BacktestTrade.entry_time.asc()).all()
    return {
        **_run_summary(run),
        "trades": [{
            "symbol": t.symbol, "direction": t.direction, "entry_time": t.entry_time, "exit_time": t.exit_time,
            "entry_price": t.entry_price, "exit_price": t.exit_price, "quantity": t.quantity,
            "stop_loss": t.stop_loss, "target": t.target, "exit_reason": t.exit_reason,
            "gross_pnl": t.gross_pnl, "charges": t.charges, "net_pnl": t.net_pnl,
            "strategy_score": t.strategy_score, "market_regime": t.market_regime, "reasons": t.reasons,
        } for t in trades],
    }


def _run_summary(r: BacktestRun) -> dict:
    return {
        "id": r.id, "symbol": r.symbol, "timeframe": r.timeframe, "start_date": r.start_date,
        "end_date": r.end_date, "risk_profile": r.risk_profile, "strategy_name": r.strategy_name, "status": r.status,
        "error_message": r.error_message, "starting_capital": r.starting_capital,
        "ending_capital": r.ending_capital, "total_trades": r.total_trades, "winning_trades": r.winning_trades,
        "losing_trades": r.losing_trades, "win_rate": r.win_rate, "profit_factor": r.profit_factor,
        "expectancy": r.expectancy, "net_pnl": r.net_pnl, "avg_win": r.avg_win, "avg_loss": r.avg_loss,
        "max_drawdown": r.max_drawdown, "max_drawdown_pct": r.max_drawdown_pct,
        "sharpe_like": r.sharpe_like, "sortino_like": r.sortino_like, "warnings": r.warnings,
        "created_at": r.created_at,
    }
