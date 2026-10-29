"""
The Trading Engine - orchestrates the full automated flow end to end, once
per "tick" (default every 20 seconds):

  FYERS connection -> market status -> market regime -> universe -> live data
  -> stock filter -> liquidity/volatility/trend filter -> technical analysis
  -> signal scoring -> ranking -> best valid setup -> risk engine ->
  position sizing -> order validation -> order -> fill -> stop/target/trail
  -> position monitor -> automatic exit -> trade journal -> next opportunity

The engine loop itself runs continuously in the background from app
startup. Whether it actually DOES anything each tick is controlled entirely
by UserSettings.auto_trading_enabled / kill_switch_active - there is no
separate "start the loop" step, which avoids an entire class of bugs where
a stale thread doesn't see a stop request.

Position protection (stop/target monitoring and exits) keeps running even
when auto trading is paused or the kill switch is active, because closing
an already-open position safely is a capital-protection action, not a new
trade.

=== LIVE DATA & RATE LIMITING ===
Live prices come from the FYERS market-data WebSocket (one connection,
subscribed once to the whole universe) via the shared PriceCache - there is
NO repeated REST quote polling anywhere in this module. The only REST calls
still made here are historical candles (needed for EMA/VWAP/RSI/ATR, which
the tick feed doesn't provide) - FYERS has no multi-symbol batch endpoint
for history, so scanning costs one request PER symbol. To respect the
Standard plan's data-category limit (50 req/min officially, 40/min as this
app's safety margin), the full universe is scanned in rotating batches
(HISTORY_BATCH_SIZE symbols per SCAN_INTERVAL_SECONDS cycle) rather than
all at once, and candle results are cached between cycles.
"""
from __future__ import annotations

import logging
import datetime as dt
import threading
import time

from sqlalchemy.orm import Session

from app.database import session_scope
from app.config import get_settings
from app.models import UserSettings, Signal, SystemEvent, BrokerConnection, EngineActivity, Position
from app.engine import universe, scanner, market_regime, strategy, position_sizing
from app.engine.risk_engine import RiskEngine
from app.engine.order_manager import OrderManager
from app.engine.position_manager import PositionManager
from app.fyers.client import FyersClient, FyersApiError, FyersRateLimitError
from app.fyers.rate_limiter import get_rate_limiter
from app.fyers.price_cache import get_price_cache
from app.fyers.websocket_feed import LiveFeed, STATUS_CONNECTED, STATUS_STALE_DATA, STATUS_DISCONNECTED
from app.security import decrypt, SecretsNotConfiguredError

logger = logging.getLogger(__name__)

TICK_INTERVAL_SECONDS = 20       # fast tick: position protection + (free) health computation
SCAN_INTERVAL_SECONDS = 60       # slow cadence: market regime + a rotating slice of the universe
HISTORY_BATCH_SIZE = 35          # symbols refreshed per scan cycle - keeps us under the data-category limit
CANDLE_CACHE_TTL_SECONDS = 180   # 5-min candles don't meaningfully change inside this window
CANDLE_RESOLUTION = "5"
MAX_CANDIDATES_TO_SCORE = 12
POSITION_MONITOR_MAX_STALE_SECONDS = 60  # how old a cached tick may be and still be used to protect an open position


def _today() -> str:
    return dt.date.today().isoformat()


def _log_health(db: Session, component: str, status: str, message: str = "") -> None:
    db.add(SystemEvent(component=component, status=status, message=message))
    db.commit()


class TradingEngine:
    def __init__(self):
        self._fyers_client: FyersClient | None = None
        self._live_feed: LiveFeed | None = None
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_scan_at: float = 0.0
        self._scan_cursor: int = 0
        self._candle_cache: dict[str, tuple[float, list[dict]]] = {}

    # ---- connection management -----------------------------------------

    def attach_fyers_client(self, client: FyersClient | None) -> None:
        self._fyers_client = client
        if client is not None:
            self._start_live_feed(client)
        else:
            if self._live_feed is not None:
                self._live_feed.stop()
            self._live_feed = None

    def has_live_client(self) -> bool:
        return self._fyers_client is not None

    def load_client_from_db_if_needed(self, db: Session) -> None:
        if self._fyers_client is not None:
            return
        conn = db.query(BrokerConnection).filter_by(broker="fyers").first()
        if conn and conn.connected and conn.access_token_encrypted and conn.token_date == _today():
            try:
                token = decrypt(conn.access_token_encrypted)
                self.attach_fyers_client(FyersClient(token))
            except SecretsNotConfiguredError as exc:
                logger.error("Cannot decrypt stored FYERS token: %s", exc)

    def _start_live_feed(self, client: FyersClient) -> None:
        if self._live_feed is not None and self._live_feed.started:
            return
        settings = get_settings()
        feed = LiveFeed(access_token=client.access_token, client_id=settings.FYERS_CLIENT_ID)
        feed.start()
        symbols = universe.get_universe_symbols() + list(universe.INDEX_SYMBOLS.values())
        feed.subscribe(symbols)
        self._live_feed = feed
        logger.info("Started FYERS live feed and subscribed %d symbols", len(symbols))

    # ---- background loop -------------------------------------------------

    def start_background_loop(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Trading engine background loop started")

    def stop_background_loop(self) -> None:
        self._stop_flag.set()

    def _loop(self) -> None:
        while not self._stop_flag.is_set():
            try:
                with session_scope() as db:
                    self.run_tick(db)
            except Exception:
                logger.exception("Unhandled error in trading engine tick")
            time.sleep(TICK_INTERVAL_SECONDS)

    # ---- one engine tick ---------------------------------------------------

    def run_tick(self, db: Session) -> None:
        user_settings = db.query(UserSettings).first()
        if user_settings is None:
            return

        _log_health(db, "DATABASE", "HEALTHY")
        _log_health(db, "RISK_ENGINE", "HEALTHY")
        _log_health(db, "ORDER_MANAGER", "HEALTHY")

        mode = user_settings.trading_mode
        if mode == "live":
            self.load_client_from_db_if_needed(db)

        order_manager = OrderManager(db, mode=mode, fyers_client=self._fyers_client if mode == "live" else None)
        position_manager = PositionManager(db, order_manager)

        risk_engine = RiskEngine(db)
        today = _today()
        self._ensure_daily_stats_row(db, user_settings, today)

        past_square_off = risk_engine.past_square_off_time()

        # --- always: monitor + protect existing open positions --------------
        # Uses only the shared price cache (written by the websocket feed) -
        # no REST call. If a position's own cached tick has gone stale beyond
        # POSITION_MONITOR_MAX_STALE_SECONDS, it is skipped rather than acted
        # on with a guess - never assume a price, never force an exit blind.
        for position in position_manager.get_open_positions():
            price = self._get_ltp(position.symbol)
            if price is None:
                _log_health(db, "LIVE_DATA", "DEGRADED",
                            f"No recent live price for open position {position.symbol} - monitoring paused for it")
                continue
            candles = self._get_candles(position.symbol, allow_refresh=False)
            from app.engine import indicators as ind
            atr_value = ind.atr(candles) if candles else None
            position_manager.update_price_and_check_exit(
                position, price, atr_value, force_time_exit=past_square_off,
            )

        if past_square_off:
            if user_settings.auto_trading_enabled:
                user_settings.auto_trading_enabled = False
                db.commit()
                logger.info("Mandatory square-off time reached - auto trading disabled for the day")
            self._record_activity(db, mode=mode, stage="SQUARE_OFF",
                                   message="Mandatory square-off time reached - no new trades", action="NO_TRADE")
            return

        # --- always refresh connectivity/live-data health FIRST --------------
        # Zero REST cost: derived from whether we hold a token, whether the
        # rate limiter is currently backing off, and the websocket feed's own
        # connection/tick-freshness state - never from a dedicated heartbeat
        # request. Must run before the gate below (which reads these same
        # values) so a bad status can always heal itself on a later tick.
        self._refresh_connectivity_health(db, mode)

        # --- gate: should we even look for new trades? -----------------------
        decision = risk_engine.check_trading_allowed(user_settings, today)
        if not decision.allowed:
            logger.debug("No new trades: %s", decision.reason)
            self._record_activity(db, mode=mode, stage="BLOCKED", message=decision.reason, action="NO_TRADE")
            return

        # --- the full market scan costs one FYERS request PER symbol (no
        # batch history endpoint exists) and runs on its own slower cadence,
        # independent of the fast 20s tick, specifically to stay well under
        # the FYERS Standard plan's data-category rate limit. Position
        # protection above still runs every tick regardless.
        if time.time() - self._last_scan_at < SCAN_INTERVAL_SECONDS:
            return
        self._last_scan_at = time.time()

        try:
            regime_result = self._get_market_regime()
        except FyersRateLimitError as exc:
            self._record_activity(db, mode=mode, stage="RATE_LIMITED", message=str(exc), action="NO_TRADE")
            return

        if regime_result is None or not regime_result.tradeable:
            _log_health(db, "STRATEGY", "HEALTHY", "No trade - market regime unsafe/unclear")
            self._record_activity(
                db, mode=mode, stage="REGIME_UNSAFE",
                message=(regime_result.reason if regime_result else "Not enough index data yet") +
                         " - no trade this cycle",
                market_regime=regime_result.regime if regime_result else "UNKNOWN", action="NO_TRADE",
            )
            return
        _log_health(db, "STRATEGY", "HEALTHY")

        best_setup, best_signal_row, candidates_summary, universe_size, eligible_count, best_avg_bar_volume = (
            self._find_best_setup(db, user_settings, regime_result.regime)
        )

        if best_setup is None:
            self._record_activity(
                db, mode=mode, stage="SCANNED_NO_TRADE",
                message=(f"Scanned {universe_size} stocks - {eligible_count} passed liquidity/volatility/spread "
                         f"filters - {len(candidates_summary)} scored - none met the minimum quality bar"
                         if universe_size else "No live data available to scan"),
                market_regime=regime_result.regime, universe_size=universe_size, eligible_count=eligible_count,
                candidates=candidates_summary, action="NO_TRADE",
            )
            return

        action, detail = self._execute_setup(
            db, user_settings, risk_engine, order_manager, best_setup, best_signal_row, today,
            avg_bar_volume=best_avg_bar_volume,
        )
        self._record_activity(
            db, mode=mode, stage="SCAN_RESULT", message=detail, market_regime=regime_result.regime,
            universe_size=universe_size, eligible_count=eligible_count, candidates=candidates_summary,
            action=f"ENTERED_{best_setup.direction}" if action == "ENTERED" else action,
            symbol_acted=best_setup.symbol if action == "ENTERED" else None,
        )

    def _record_activity(self, db: Session, *, mode: str, stage: str, message: str,
                          market_regime: str | None = None, universe_size: int | None = None,
                          eligible_count: int | None = None, candidates: list | None = None,
                          action: str | None = None, symbol_acted: str | None = None) -> None:
        db.add(EngineActivity(
            mode=mode, stage=stage, message=message, market_regime=market_regime,
            universe_size=universe_size, eligible_count=eligible_count, candidates=candidates,
            action=action, symbol_acted=symbol_acted,
        ))
        db.commit()

    # ---- health (no REST cost) ----------------------------------------------

    def _refresh_connectivity_health(self, db: Session, mode: str) -> None:
        if self._fyers_client is None:
            if mode == "live":
                _log_health(db, "FYERS_API", "DISCONNECTED", "Not connected to FYERS - new trades stopped")
                _log_health(db, "LIVE_DATA", "DISCONNECTED", "Not connected to FYERS")
            return

        limiter = get_rate_limiter()
        if limiter.is_backing_off("data") or limiter.is_backing_off("transaction"):
            remaining = max(limiter.backoff_seconds_remaining("data"), limiter.backoff_seconds_remaining("transaction"))
            msg = f"Backing off {remaining:.0f}s after a FYERS rate-limit response - new trades stopped"
            _log_health(db, "FYERS_API", "RATE_LIMITED", msg)
            _log_health(db, "LIVE_DATA", "RATE_LIMITED", msg)
            return

        _log_health(db, "FYERS_API", "CONNECTED", "Authenticated (token held for today)")

        if self._live_feed is None or not self._live_feed.started:
            _log_health(db, "LIVE_DATA", "DISCONNECTED", "Live price feed not started")
            return

        status = self._live_feed.status()
        if status == STATUS_CONNECTED:
            _log_health(db, "LIVE_DATA", "CONNECTED", f"{self._live_feed.subscribed_count()} symbols subscribed")
        elif status == STATUS_STALE_DATA:
            _log_health(db, "LIVE_DATA", "STALE_DATA", "No ticks received recently - new trades blocked")
        else:
            _log_health(db, "LIVE_DATA", "DISCONNECTED", "WebSocket disconnected - new trades blocked")

    # ---- helpers -----------------------------------------------------------

    def _ensure_daily_stats_row(self, db: Session, user_settings: UserSettings, today: str) -> None:
        from app.models import DailyStatistics
        row = db.query(DailyStatistics).filter_by(date=today).first()
        if row is None:
            db.add(DailyStatistics(date=today, starting_capital=user_settings.trading_capital))
            db.commit()

    def _get_ltp(self, symbol: str) -> float | None:
        """Reads the shared price cache (written by the websocket feed) -
        never a REST call. Returns None if we have no tick, or if the tick
        we have is older than POSITION_MONITOR_MAX_STALE_SECONDS - callers
        must treat None as "data unavailable", never substitute a guess."""
        cache = get_price_cache()
        tick = cache.get(symbol)
        if tick is None:
            return None
        if (time.time() - tick.received_at) > POSITION_MONITOR_MAX_STALE_SECONDS:
            return None
        return tick.ltp

    def _get_candles(self, symbol: str, allow_refresh: bool = True) -> list[dict]:
        """Cached for CANDLE_CACHE_TTL_SECONDS - 5-min candles don't change
        meaningfully inside that window, and this is called once PER SYMBOL
        (no batch endpoint exists), so caching is essential to stay within
        FYERS' requests-per-minute limit. When allow_refresh is False (used
        for position monitoring outside the scan's rotating batch) a stale-
        but-present cache entry is still returned rather than spending a
        request - freshness for that case is best-effort, not guaranteed."""
        if self._fyers_client is None:
            return []

        cached = self._candle_cache.get(symbol)
        fresh = cached and (time.time() - cached[0]) < CANDLE_CACHE_TTL_SECONDS
        if fresh:
            return cached[1]
        if not allow_refresh:
            return cached[1] if cached else []

        try:
            today = dt.date.today().isoformat()
            candles = self._fyers_client.get_history(symbol, CANDLE_RESOLUTION, today, today, caller="scanner.history")
        except FyersRateLimitError as exc:
            logger.warning("History fetch rate-limited for %s: %s", symbol, exc)
            return cached[1] if cached else []
        except FyersApiError as exc:
            logger.warning("History fetch failed for %s: %s", symbol, exc)
            return cached[1] if cached else []

        self._candle_cache[symbol] = (time.time(), candles)
        return candles

    def _get_market_regime(self):
        if self._fyers_client is None:
            return None
        nifty = self._get_candles(universe.INDEX_SYMBOLS["NIFTY50"])
        banknifty = self._get_candles(universe.INDEX_SYMBOLS["BANKNIFTY"])
        return market_regime.classify_market_regime(nifty, banknifty)

    def _next_scan_batch(self, symbols: list[str]) -> set[str]:
        """Rotates through the universe HISTORY_BATCH_SIZE symbols at a time,
        so a full universe scan is staged across several cycles instead of
        hitting FYERS with one request per symbol all at once."""
        n = len(symbols)
        if n == 0:
            return set()
        start = self._scan_cursor % n
        size = min(HISTORY_BATCH_SIZE, n)
        batch = {symbols[(start + i) % n] for i in range(size)}
        self._scan_cursor = (start + size) % n
        return batch

    def _find_best_setup(self, db: Session, user_settings: UserSettings, regime: str):
        """Returns (best_setup, best_signal_row, candidates_summary, universe_size,
        eligible_count, best_avg_bar_volume). Uses the shared price cache for
        live price/bid/ask (no REST) and a rotating batch for history refresh
        (see _next_scan_batch). best_avg_bar_volume feeds the paper broker's
        liquidity-aware fill simulation (Phase 7) - None if no setup passed."""
        if self._fyers_client is None or self._live_feed is None:
            return None, None, [], 0, 0, None
        if self._live_feed.status() != STATUS_CONNECTED:
            # Blocked per the trading-safety rule: never scan for NEW entries
            # on a disconnected or stale feed, even though existing positions
            # may still be monitored with best-effort cached data.
            return None, None, [], 0, 0, None

        symbols = universe.get_universe_symbols()
        refresh_batch = self._next_scan_batch(symbols)
        price_cache = get_price_cache()

        scan_results = []
        candle_cache: dict[str, list[dict]] = {}
        for symbol in symbols:
            candles = self._get_candles(symbol, allow_refresh=symbol in refresh_batch)
            if not candles:
                continue
            candle_cache[symbol] = candles
            tick = price_cache.get(symbol)
            quote_dict = {"bid": tick.bid, "ask": tick.ask} if tick else None
            scan_results.append(scanner.evaluate_symbol(symbol, candles, quote_dict))

        eligible = scanner.rank_candidates(scan_results)
        candidates = eligible[:MAX_CANDIDATES_TO_SCORE]

        best_setup = None
        best_signal_row = None
        best_avg_bar_volume = None
        candidates_summary: list[dict] = []
        for candidate in candidates:
            candles = candle_cache[candidate.symbol]
            setup = strategy.evaluate(candidate.symbol, candles, regime, user_settings.min_risk_reward)

            signal_row = Signal(
                symbol=candidate.symbol, direction=setup.direction, score=setup.score,
                max_score=setup.max_score, passed=setup.passed, reasons=setup.reasons,
                components=setup.components, market_regime=regime, entry_price=setup.entry_price,
                stop_loss=setup.stop_loss, target=setup.target, risk_per_share=setup.risk_per_share,
                reward_per_share=setup.reward_per_share, risk_reward=setup.risk_reward,
                rejected_reason=setup.rejected_reason,
            )
            db.add(signal_row)
            db.commit()

            tick = price_cache.get(candidate.symbol)
            candidates_summary.append({
                "symbol": candidate.symbol.replace("NSE:", "").replace("-EQ", ""),
                "direction": setup.direction, "score": setup.score, "max_score": setup.max_score,
                "passed": setup.passed, "rejected_reason": setup.rejected_reason,
                "entry_price": setup.entry_price, "ltp": tick.ltp if tick else None,
            })

            if setup.passed and (best_setup is None or setup.score > best_setup.score):
                best_setup = setup
                best_signal_row = signal_row
                recent = candles[-20:]
                best_avg_bar_volume = sum(c["volume"] for c in recent) / len(recent) if recent else None

        return best_setup, best_signal_row, candidates_summary, len(symbols), len(eligible), best_avg_bar_volume

    def _execute_setup(self, db: Session, user_settings: UserSettings, risk_engine: RiskEngine,
                        order_manager: OrderManager, setup, signal_row: Signal, today: str,
                        avg_bar_volume: float | None = None) -> tuple[str, str]:
        """Returns (outcome, detail) where outcome is ENTERED | REJECTED | ERROR."""
        setup_check = risk_engine.validate_setup(setup.symbol, setup.risk_reward, user_settings.min_risk_reward)
        if not setup_check.allowed:
            signal_row.rejected_reason = setup_check.reason
            signal_row.passed = False
            db.commit()
            return "REJECTED", f"Best setup was {setup.symbol} ({setup.direction}, {setup.score}/10) but: {setup_check.reason}"

        gate = risk_engine.check_trading_allowed(user_settings, today)
        if not gate.allowed:
            return "REJECTED", f"Best setup was {setup.symbol} ({setup.direction}, {setup.score}/10) but: {gate.reason}"

        day_capital = gate.details["day_start_capital"]

        # Phase 7: available capital must account for what's ALREADY locked
        # in other open positions, not just the day's starting capital -
        # otherwise two concurrent positions could each be sized as if the
        # full day-start capital were available to both.
        locked_capital = sum(
            (p.entry_price or 0) * (p.quantity or 0)
            for p in db.query(Position).filter(Position.status.in_(["OPEN", "CLOSING"])).all()
        )
        available_capital = max(0.0, day_capital - locked_capital)

        sizing = position_sizing.calculate_position_size(
            available_capital=available_capital, max_risk_amount=gate.max_risk_amount,
            entry_price=setup.entry_price, risk_per_share=setup.risk_per_share,
        )
        if sizing.quantity <= 0:
            signal_row.rejected_reason = sizing.reason
            signal_row.passed = False
            db.commit()
            return "REJECTED", f"Best setup was {setup.symbol} ({setup.direction}, {setup.score}/10) but: {sizing.reason}"

        hard_check = risk_engine.validate_order_hard_limits(
            risk_amount=sizing.quantity * setup.risk_per_share, day_start_capital=day_capital,
        )
        if not hard_check.allowed:
            signal_row.rejected_reason = hard_check.reason
            signal_row.passed = False
            db.commit()
            return "REJECTED", f"Best setup was {setup.symbol} ({setup.direction}, {setup.score}/10) but: {hard_check.reason}"

        try:
            order, position = order_manager.place_entry(
                symbol=setup.symbol, direction=setup.direction, quantity=sizing.quantity,
                reference_price=setup.entry_price, stop_loss=setup.stop_loss, target=setup.target,
                signal_id=signal_row.id, available_capital=available_capital, avg_bar_volume=avg_bar_volume,
            )
        except Exception as exc:
            logger.exception("Failed to place entry for %s", setup.symbol)
            from app.engine.risk_engine import log_risk_event
            log_risk_event(db, "ORDER_ERROR", f"Entry failed for {setup.symbol}: {exc}", severity="WARNING")
            return "ERROR", f"Order placement failed for {setup.symbol}: {exc}"

        if position is None:
            return "ERROR", f"Order for {setup.symbol} did not fill (status: {order.status}): {order.error_message or ''}"

        return "ENTERED", (
            f"Entered {setup.direction} {setup.symbol} x{position.quantity} @ Rs.{position.entry_price} "
            f"(score {setup.score}/10, SL Rs.{setup.stop_loss}, target Rs.{setup.target})"
        )


# Module-level singleton used by the API layer
engine = TradingEngine()
