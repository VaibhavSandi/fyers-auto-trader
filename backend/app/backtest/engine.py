"""
Backtesting engine (Phase 3) - replays the EXISTING rule-based strategy
(app/engine/strategy.py) bar-by-bar over locally stored historical candles
(app/data/historical.py), using the exact same position sizing, trailing
stop, risk gating, and cost model as live/paper trading - so a backtest
result means the same thing a live trading day would have meant.

What makes this trustworthy, by construction:
  - Look-ahead is structurally impossible: at bar i, the strategy only ever
    sees candles[0:i+1] (and the index/regime data sliced to the SAME
    point in time). There is no code path that can read a future bar.
  - Entry/stop/target are computed by calling strategy.py directly - this
    is not a reimplemented "backtest version" of the strategy, it's the
    same function the live engine calls.
  - Stop-loss/target fills use a conservative same-bar tie-break: if a
    single bar's range could have hit BOTH the stop and the target, the
    stop is assumed to have hit first. This can only ever understate a
    backtest's performance, never flatter it.
  - Position sizing uses the trading DAY's starting equity, never
    mid-day running equity - identical to the live risk engine's
    anti-martingale rule (app/engine/risk_engine.py).
  - Costs use the exact same estimate_charges() live trading uses.
  - A missing precondition (not enough history, no index data for regime)
    is reported as a warning and that period is SKIPPED, never silently
    filled in or faked.

Known, deliberate scope limit: this runs ONE symbol at a time, as if that
symbol were the entire universe with the full configured capital. It does
NOT reproduce the live engine's cross-symbol ranking (only the best-scoring
candidate across the ~50-symbol universe gets taken each live cycle). This
answers a narrower, still-useful question first: does the strategy have an
edge on THIS symbol at all. Portfolio-level backtesting is a natural next
step, not this one.

The "Sharpe-like" / "Sortino-like" metrics are a simple mean/stdev ratio
over PER-TRADE returns - deliberately not labelled as an annualized Sharpe
ratio, because trades don't arrive at a fixed frequency and annualizing
them would imply a precision this number doesn't have.
"""
from __future__ import annotations

import datetime as dt
import logging
import statistics
from dataclasses import dataclass, field

from app.engine import market_regime, position_sizing
from app.engine import indicators as ind
from app.engine.trailing_stop import update_trailing_stop
from app.engine.costs import estimate_charges
from app.engine.risk_profiles import compute_safe_defaults
from app.data.historical import HistoricalDataService
from app.strategies.registry import get_strategy, DEFAULT_STRATEGY

logger = logging.getLogger(__name__)

IST_OFFSET = dt.timedelta(hours=5, minutes=30)
MIN_CANDLES_FOR_STRATEGY = 30
SLIPPAGE_PCT = 0.03  # matches app/engine/paper_broker.py - kept identical on purpose
NIFTY_SYMBOL = "NSE:NIFTY50-INDEX"
BANKNIFTY_SYMBOL = "NSE:NIFTYBANK-INDEX"


def _to_ist(utc_naive: dt.datetime) -> dt.datetime:
    return utc_naive + IST_OFFSET


def _parse_time(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


@dataclass
class BacktestTradeResult:
    direction: str
    entry_time: dt.datetime
    entry_price: float
    quantity: int
    stop_loss: float
    original_stop_loss: float
    target: float
    score: int
    market_regime: str
    reasons: list[str] = field(default_factory=list)
    trailing_active: bool = False
    exit_time: dt.datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    gross_pnl: float = 0.0
    charges: float = 0.0
    net_pnl: float = 0.0


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    risk_profile: str
    starting_capital: float
    ending_capital: float
    trades: list[BacktestTradeResult]
    warnings: list[str]
    metrics: dict
    strategy_name: str = DEFAULT_STRATEGY


class Backtester:
    def __init__(self, data_service: HistoricalDataService, app_settings):
        self.data = data_service
        self.settings = app_settings

    def run(self, *, symbol: str, timeframe: str, start: dt.date, end: dt.date,
            capital: float, risk_profile: str, strategy_name: str = DEFAULT_STRATEGY,
            warm_start: bool = True) -> BacktestResult:
        """warm_start=True (default, and the realistic live behavior as of
        this change): every bar sees the full multi-day candle history up
        to that point, so EMA/RSI/ATR/regime classification are warm from
        the first bar of any day after the first. warm_start=False
        reproduces the PREVIOUS live bug on purpose (for the A/B comparison
        in /api/backtest/compare-warmup): each new calendar day is
        truncated back to that day's own bars only, so indicators must
        re-accumulate ~25 bars from scratch every single day (09:15 + 125min
        = 11:20 effective start), exactly as the live engine used to."""
        warnings: list[str] = []
        defaults = compute_safe_defaults(capital, risk_profile)
        strategy_module = get_strategy(strategy_name)

        candles = self.data.get_candles(symbol, timeframe, start, end)
        if len(candles) < MIN_CANDLES_FOR_STRATEGY:
            warnings.append(
                f"Only {len(candles)} candles available for {symbol} in this range - need at least "
                f"{MIN_CANDLES_FOR_STRATEGY}. Sync more history before backtesting. No trades simulated."
            )
            return BacktestResult(symbol, timeframe, start.isoformat(), end.isoformat(), risk_profile,
                                   capital, capital, [], warnings, _compute_metrics([], capital), strategy_name)

        nifty = self.data.get_candles(NIFTY_SYMBOL, timeframe, start, end)
        banknifty = self.data.get_candles(BANKNIFTY_SYMBOL, timeframe, start, end)
        if len(nifty) < MIN_CANDLES_FOR_STRATEGY or len(banknifty) < MIN_CANDLES_FOR_STRATEGY:
            warnings.append(
                "Index history (NIFTY50/BANKNIFTY) is missing or too short for this range - the market-regime "
                "filter cannot run faithfully, so every bar will correctly evaluate as 'regime unknown -> no "
                "trade'. Sync index history (NSE:NIFTY50-INDEX, NSE:NIFTYBANK-INDEX) for a meaningful result."
            )

        open_t = _parse_time(self.settings.MARKET_OPEN_TIME)
        entry_start_t = _parse_time(self.settings.ENTRY_START_TIME)
        cutoff_t = _parse_time(self.settings.ENTRY_CUTOFF_TIME)
        square_off_t = _parse_time(self.settings.SQUARE_OFF_TIME)

        trades: list[BacktestTradeResult] = []
        open_trade: BacktestTradeResult | None = None
        equity = capital
        day_start_capital = capital
        current_date: dt.date | None = None
        trades_today = 0
        daily_pnl = 0.0
        day_trade_results: list[float] = []  # net_pnl of today's closed trades, oldest first

        nifty_ptr = 0
        banknifty_ptr = 0

        for i in range(MIN_CANDLES_FOR_STRATEGY - 1, len(candles)):
            window = candles[:i + 1]  # ONLY past + current bar - a future bar is never reachable here
            bar = window[-1]
            bar_ts: dt.datetime = bar["timestamp"]
            bar_ist = _to_ist(bar_ts)
            bar_date = bar_ist.date()
            bar_time = bar_ist.time()

            if bar_date != current_date:
                current_date = bar_date
                day_start_capital = equity
                trades_today = 0
                daily_pnl = 0.0
                day_trade_results = []

            # Slice index data to no later than this bar's own timestamp -
            # the regime filter must never see index candles from the future either.
            while nifty_ptr + 1 < len(nifty) and nifty[nifty_ptr + 1]["timestamp"] <= bar_ts:
                nifty_ptr += 1
            while banknifty_ptr + 1 < len(banknifty) and banknifty[banknifty_ptr + 1]["timestamp"] <= bar_ts:
                banknifty_ptr += 1
            nifty_window = nifty[:nifty_ptr + 1] if nifty and nifty[0]["timestamp"] <= bar_ts else []
            banknifty_window = banknifty[:banknifty_ptr + 1] if banknifty and banknifty[0]["timestamp"] <= bar_ts else []

            if not warm_start:
                window = ind.session_slice(window)
                nifty_window = ind.session_slice(nifty_window)
                banknifty_window = ind.session_slice(banknifty_window)

            past_square_off = bar_time >= square_off_t

            # --- manage an existing open position first, every bar -----------
            if open_trade is not None:
                atr_val = ind.atr(window)
                trail = update_trailing_stop(
                    direction=open_trade.direction, entry_price=open_trade.entry_price,
                    original_stop_loss=open_trade.original_stop_loss, current_stop_loss=open_trade.stop_loss,
                    current_price=bar["close"], atr_value=atr_val,
                )
                if trail.moved:
                    open_trade.stop_loss = trail.new_stop_loss
                    open_trade.trailing_active = True

                exit_price = None
                exit_reason = None
                if past_square_off:
                    exit_price, exit_reason = bar["close"], "EOD_SQUAREOFF"
                else:
                    exit_price, exit_reason = self._check_bar_exit(open_trade, bar)

                if exit_price is not None:
                    self._close_trade(open_trade, bar_ist, exit_price, exit_reason)
                    trades.append(open_trade)
                    equity += open_trade.net_pnl
                    daily_pnl += open_trade.net_pnl
                    day_trade_results.append(open_trade.net_pnl)
                    open_trade = None

            if past_square_off:
                continue  # never open a new position once square-off has passed

            # --- consider a new entry -----------------------------------------
            consecutive_losses = 0
            for pnl in reversed(day_trade_results):
                if pnl < 0:
                    consecutive_losses += 1
                else:
                    break

            can_enter = (
                open_trade is None
                and entry_start_t <= bar_time < cutoff_t
                and bar_time >= open_t
                and daily_pnl > -(day_start_capital * defaults["max_daily_loss_pct"] / 100)
                and consecutive_losses < defaults["max_consecutive_losses"]
                and trades_today < defaults["max_trades_per_day"]
            )
            if not can_enter:
                continue

            regime_result = market_regime.classify_market_regime(nifty_window, banknifty_window)
            if not regime_result.tradeable:
                continue

            setup = strategy_module.evaluate(symbol, window, regime_result.regime, defaults["min_risk_reward"])
            if not setup.passed:
                continue

            max_risk_amount = day_start_capital * defaults["max_risk_per_trade_pct"] / 100
            sizing = position_sizing.calculate_position_size(
                available_capital=day_start_capital, max_risk_amount=max_risk_amount,
                entry_price=setup.entry_price, risk_per_share=setup.risk_per_share,
            )
            if sizing.quantity <= 0:
                continue

            slip = setup.entry_price * (SLIPPAGE_PCT / 100)
            fill_price = setup.entry_price + slip if setup.direction == "BUY" else setup.entry_price - slip

            open_trade = BacktestTradeResult(
                direction=setup.direction, entry_time=bar_ist, entry_price=round(fill_price, 2),
                quantity=sizing.quantity, stop_loss=setup.stop_loss, original_stop_loss=setup.stop_loss,
                target=setup.target, score=setup.score, market_regime=regime_result.regime,
                reasons=setup.reasons,
            )
            trades_today += 1

        if open_trade is not None:
            last_bar = candles[-1]
            warnings.append(
                f"A position was still open when historical data ran out ({open_trade.direction} "
                f"{symbol} from {open_trade.entry_time}) - force-closed at the last available price for "
                f"reporting. This is a backtest-data-boundary artifact, not a real exit signal."
            )
            self._close_trade(open_trade, _to_ist(last_bar["timestamp"]), last_bar["close"], "BACKTEST_END")
            trades.append(open_trade)
            equity += open_trade.net_pnl

        metrics = _compute_metrics(trades, capital)
        return BacktestResult(
            symbol=symbol, timeframe=timeframe, start_date=start.isoformat(), end_date=end.isoformat(),
            risk_profile=risk_profile, starting_capital=capital, ending_capital=round(equity, 2),
            trades=trades, warnings=warnings, metrics=metrics, strategy_name=strategy_name,
        )

    @staticmethod
    def _check_bar_exit(trade: BacktestTradeResult, bar: dict) -> tuple[float | None, str | None]:
        """Conservative same-bar tie-break: if both the stop and the target
        fall inside this single bar's range, the stop is assumed to have
        been hit first (we have no intra-bar sequencing with OHLC-only
        data). This can only ever understate performance, never flatter it."""
        if trade.direction == "BUY":
            hit_stop = bar["low"] <= trade.stop_loss
            hit_target = bar["high"] >= trade.target
            if hit_stop:
                reason = "TRAILING_STOP" if trade.trailing_active and trade.stop_loss > trade.original_stop_loss else "STOP_LOSS"
                return trade.stop_loss, reason
            if hit_target:
                return trade.target, "TARGET"
        else:
            hit_stop = bar["high"] >= trade.stop_loss
            hit_target = bar["low"] <= trade.target
            if hit_stop:
                reason = "TRAILING_STOP" if trade.trailing_active and trade.stop_loss < trade.original_stop_loss else "STOP_LOSS"
                return trade.stop_loss, reason
            if hit_target:
                return trade.target, "TARGET"
        return None, None

    @staticmethod
    def _close_trade(trade: BacktestTradeResult, exit_time: dt.datetime, exit_price: float, reason: str) -> None:
        direction_sign = 1 if trade.direction == "BUY" else -1
        gross_pnl = direction_sign * (exit_price - trade.entry_price) * trade.quantity
        charges = estimate_charges(trade.entry_price, exit_price, trade.quantity)
        trade.exit_time = exit_time
        trade.exit_price = round(exit_price, 2)
        trade.exit_reason = reason
        trade.gross_pnl = round(gross_pnl, 2)
        trade.charges = charges
        trade.net_pnl = round(gross_pnl - charges, 2)


def _compute_metrics(trades: list[BacktestTradeResult], starting_capital: float) -> dict:
    total = len(trades)
    if total == 0:
        return {
            "total_trades": 0, "winning_trades": 0, "losing_trades": 0, "win_rate": 0.0,
            "gross_profit": 0.0, "gross_loss": 0.0, "profit_factor": 0.0, "expectancy": 0.0,
            "net_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "max_drawdown": 0.0, "max_drawdown_pct": 0.0,
            "sharpe_like": None, "sortino_like": None,
        }

    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl <= 0]
    gross_profit = sum(t.net_pnl for t in wins)
    gross_loss = abs(sum(t.net_pnl for t in losses))
    net_pnl = sum(t.net_pnl for t in trades)

    equity = starting_capital
    peak = starting_capital
    max_dd = 0.0
    for t in trades:
        equity += t.net_pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    returns = [t.net_pnl / starting_capital for t in trades] if starting_capital else []
    sharpe_like = None
    sortino_like = None
    if len(returns) >= 2:
        mean_r = statistics.mean(returns)
        stdev_r = statistics.pstdev(returns)
        if stdev_r > 0:
            sharpe_like = round(mean_r / stdev_r, 3)
        downside = [r for r in returns if r < 0]
        if len(downside) >= 2:
            dd_std = statistics.pstdev(downside)
            if dd_std > 0:
                sortino_like = round(mean_r / dd_std, 3)

    return {
        "total_trades": total, "winning_trades": len(wins), "losing_trades": len(losses),
        "win_rate": round(len(wins) / total * 100, 1),
        "gross_profit": round(gross_profit, 2), "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else (round(gross_profit, 2) if gross_profit else 0.0),
        "expectancy": round(net_pnl / total, 2),
        "net_pnl": round(net_pnl, 2),
        "avg_win": round(gross_profit / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd / starting_capital * 100, 2) if starting_capital else 0.0,
        "sharpe_like": sharpe_like, "sortino_like": sortino_like,
    }
