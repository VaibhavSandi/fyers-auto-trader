"""
Automatic self-learning scheduler (opt-in, OFF by default via
Settings.ENABLE_AUTO_LEARNING).

This runs the exact same backtest -> walk-forward -> compare-and-decide
pipeline that POST /api/learning/experiment already exposes manually - the
only thing this adds is a clock, so you don't have to call that endpoint
yourself. Nothing about the evidence gates in app/learning/promotion.py is
loosened for the automatic path: a candidate strategy only gets promoted if
it clears the same sample-size/expectancy/drawdown thresholds a manual run
would require, and every comparison (promoted, rejected, or inconclusive) is
logged as a LearningExperiment row exactly as before.

It also runs a separate daily diagnosis over that day's REAL closed trades
(paper or live, from the actual trade journal - not backtest data), logging
a by-market-regime / by-exit-reason / by-strategy-score breakdown as an
AUTO_LEARNING system event. This step needs no FYERS connection and always
runs, even on a day the backtest/train pipeline below can't (e.g. not
connected yet) - "learn from today's real trading" shouldn't depend on
connectivity the way syncing fresh history does.

Deliberately NOT done here, matching promotion.py's own module docstring:
  - Wiring a promoted version into live or paper trading. Nothing in
    app/engine/trading_engine.py reads ModelVersion.status - that stays a
    separate, explicit step regardless of what this scheduler decides.
  - Loosening or bypassing MIN_SAMPLE_TRADES / expectancy / drawdown checks.
  - Retrying within the same day - one attempt per calendar day is enough;
    a failure (no FYERS connection, rate limit, etc.) just waits for
    tomorrow rather than retry-storming.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time

from app.database import session_scope
from app.config import get_settings
from app.data.historical import HistoricalDataService, HistoricalDataError
from app.backtest.engine import Backtester
from app.backtest.walkforward import run_walk_forward
from app.strategies.registry import STRATEGIES, DEFAULT_STRATEGY
from app.learning.promotion import register_model_version, get_active_version, compare_and_decide
from app.engine.trading_engine import engine as trading_engine
from app.engine import universe
from app.models import SystemEvent

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 300  # how often the scheduler thread wakes up to check the clock
BACKTEST_CAPITAL = 10000.0
BACKTEST_RISK_PROFILE = "conservative"


class AutoLearningScheduler:
    def __init__(self):
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_attempt_date: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Auto-learning scheduler thread started")

    def stop(self) -> None:
        self._stop_flag.set()

    def status(self) -> dict:
        settings = get_settings()
        return {
            "enabled": settings.ENABLE_AUTO_LEARNING,
            "run_time": settings.AUTO_LEARNING_RUN_TIME,
            "symbols": settings.auto_learning_symbol_list(),
            "last_attempt_date": self._last_attempt_date,
        }

    # ---- background loop -------------------------------------------------

    def _loop(self) -> None:
        while not self._stop_flag.is_set():
            try:
                settings = get_settings()
                if settings.ENABLE_AUTO_LEARNING:
                    self._maybe_run(settings)
            except Exception:
                logger.exception("Unhandled error in auto-learning scheduler")
            time.sleep(CHECK_INTERVAL_SECONDS)

    def _maybe_run(self, settings) -> None:
        now = dt.datetime.now()
        today = now.date().isoformat()
        if self._last_attempt_date == today:
            return

        run_at = dt.datetime.strptime(settings.AUTO_LEARNING_RUN_TIME, "%H:%M").time()
        if now.time() < run_at:
            return

        self._last_attempt_date = today  # one attempt per day, success or failure

        with session_scope() as db:
            try:
                self._run_daily_trade_diagnosis(db)
            except Exception:
                logger.exception("Auto-learning: daily trade diagnosis failed")

        if trading_engine._fyers_client is None:
            logger.info("Auto-learning: no FYERS connection - skipping backtest/train pipeline today "
                        "(trade diagnosis still ran)")
            return

        try:
            self._run_daily_pipeline(settings)
        except Exception:
            logger.exception("Auto-learning: daily pipeline failed")

    # ---- daily diagnosis of REAL trades (paper or live) -------------------

    def _run_daily_trade_diagnosis(self, db) -> None:
        from app.models import Trade
        from app.learning.diagnostics import diagnose_trades

        today = dt.date.today().isoformat()
        trades = db.query(Trade).filter(Trade.date == today).all()
        if not trades:
            self._log(db, "HEALTHY", "Daily trade diagnosis: no trades closed today - nothing to analyze.")
            return

        diagnosis = diagnose_trades(trades)
        wins = sum(1 for t in trades if (t.net_pnl or 0) > 0)
        net_pnl = round(sum(t.net_pnl or 0 for t in trades), 2)
        regime_summary = ", ".join(
            f"{k} {v['win_rate']}%({v['total']})" for k, v in diagnosis["by_market_regime"].items()
        )
        exit_summary = ", ".join(
            f"{k} {v['win_rate']}%({v['total']})" for k, v in diagnosis["by_exit_reason"].items()
        )
        self._log(db, "HEALTHY",
                   f"Daily trade diagnosis: {len(trades)} trades, {wins} wins, net Rs.{net_pnl}. "
                   f"By regime: {regime_summary}. By exit reason: {exit_summary}.")

    # ---- the actual pipeline ----------------------------------------------

    def _run_daily_pipeline(self, settings) -> None:
        symbols = settings.auto_learning_symbol_list()
        end = dt.date.today()
        start = end - dt.timedelta(days=settings.AUTO_LEARNING_LOOKBACK_DAYS)
        candidate_names = [name for name in STRATEGIES if name != DEFAULT_STRATEGY]

        with session_scope() as db:
            data_service = HistoricalDataService(db, trading_engine._fyers_client)
            backtester = Backtester(data_service, settings)

            for symbol in symbols:
                fsymbol = universe.to_fyers_symbol(symbol)
                try:
                    data_service.sync_symbol(fsymbol, "5", start, end, caller="auto_learning.sync")
                except HistoricalDataError as exc:
                    self._log(db, "DEGRADED", f"{symbol}: history sync failed - {exc}")
                    continue

                for candidate_name in candidate_names:
                    try:
                        self._run_one_experiment(db, backtester, fsymbol, symbol, candidate_name, settings, start, end)
                    except Exception as exc:
                        logger.exception("Auto-learning: experiment failed for %s/%s", candidate_name, symbol)
                        self._log(db, "DEGRADED", f"{symbol}/{candidate_name}: experiment failed - {exc}")

    def _run_one_experiment(self, db, backtester: Backtester, fsymbol: str, display_symbol: str,
                             candidate_name: str, settings, start: dt.date, end: dt.date) -> None:
        wf_kwargs = dict(
            symbol=fsymbol, timeframe="5", overall_start=start, overall_end=end,
            train_days=settings.AUTO_LEARNING_TRAIN_DAYS, test_days=settings.AUTO_LEARNING_TEST_DAYS,
            embargo_days=settings.AUTO_LEARNING_EMBARGO_DAYS, capital=BACKTEST_CAPITAL,
            risk_profile=BACKTEST_RISK_PROFILE,
        )

        candidate_report = run_walk_forward(backtester, strategy_name=candidate_name, **wf_kwargs)
        candidate_version = register_model_version(
            db, strategy_name=candidate_name,
            version_label=f"{candidate_name}-auto-{dt.datetime.utcnow():%Y%m%d%H%M%S}",
            kind="rule_based", parameters={"symbol": fsymbol, "timeframe": "5"},
            training_data_summary=candidate_report.aggregate,
        )

        baseline_version = get_active_version(db, DEFAULT_STRATEGY)
        baseline_report = run_walk_forward(backtester, strategy_name=DEFAULT_STRATEGY, **wf_kwargs)
        baseline_evidence = baseline_report.aggregate
        if baseline_version is None:
            baseline_version = register_model_version(
                db, strategy_name=DEFAULT_STRATEGY, version_label=f"{DEFAULT_STRATEGY}-reference",
                kind="rule_based", training_data_summary=baseline_evidence,
            )

        experiment = compare_and_decide(
            db, hypothesis=f"Scheduled auto-learning: does {candidate_name} beat {DEFAULT_STRATEGY} on {display_symbol}?",
            strategy_name=candidate_name, candidate_version=candidate_version,
            candidate_evidence=candidate_report.aggregate, baseline_version=baseline_version,
            baseline_evidence=baseline_evidence,
        )
        self._log(db, "HEALTHY",
                   f"{display_symbol}/{candidate_name}: {experiment.decision} - {experiment.decision_reason}")

    @staticmethod
    def _log(db, status: str, message: str) -> None:
        db.add(SystemEvent(component="AUTO_LEARNING", status=status, message=message))
        db.commit()


# Module-level singleton used by the API layer / app startup
scheduler = AutoLearningScheduler()
