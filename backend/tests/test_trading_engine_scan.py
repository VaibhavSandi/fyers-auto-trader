import datetime as dt

from app.engine.trading_engine import TradingEngine, HISTORY_BATCH_SIZE, WARMUP_LOOKBACK_DAYS
from app.fyers.websocket_feed import LiveFeed


class FakeFyersClient:
    def __init__(self):
        self.history_calls = []
        self.history_ranges = []

    def get_history(self, symbol, resolution, range_from, range_to, caller="unspecified"):
        self.history_calls.append(symbol)
        self.history_ranges.append((range_from, range_to))
        return [{"timestamp": i, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000} for i in range(30)]


def test_scan_batch_rotates_through_the_whole_universe_without_repeats_within_a_cycle():
    tengine = TradingEngine()
    symbols = [f"NSE:SYM{i}-EQ" for i in range(HISTORY_BATCH_SIZE + 10)]

    first_batch = tengine._next_scan_batch(symbols)
    assert len(first_batch) == HISTORY_BATCH_SIZE
    assert len(first_batch) == len(set(first_batch))  # no duplicates within one batch

    second_batch = tengine._next_scan_batch(symbols)
    # the cursor must have advanced - the two batches should not be identical
    assert first_batch != second_batch


def test_scan_batch_eventually_covers_every_symbol():
    tengine = TradingEngine()
    symbols = [f"NSE:SYM{i}-EQ" for i in range(HISTORY_BATCH_SIZE + 10)]
    covered = set()
    for _ in range(5):
        covered |= tengine._next_scan_batch(symbols)
    assert covered == set(symbols)


def test_get_candles_without_refresh_never_calls_fyers_when_uncached():
    tengine = TradingEngine()
    tengine._fyers_client = FakeFyersClient()
    result = tengine._get_candles("NSE:NEVER-SEEN-EQ", allow_refresh=False)
    assert result == []
    assert tengine._fyers_client.history_calls == []


def test_get_candles_without_refresh_returns_stale_cache_instead_of_calling_fyers():
    tengine = TradingEngine()
    fake = FakeFyersClient()
    tengine._fyers_client = fake
    fresh = tengine._get_candles("NSE:A-EQ", allow_refresh=True)
    assert len(fake.history_calls) == 1
    assert fresh

    # force the cache entry to look old
    tengine._candle_cache["NSE:A-EQ"] = (0.0, fresh)
    again = tengine._get_candles("NSE:A-EQ", allow_refresh=False)
    assert again == fresh
    assert len(fake.history_calls) == 1  # no second REST call


def test_get_candles_with_refresh_uses_cache_within_ttl():
    tengine = TradingEngine()
    fake = FakeFyersClient()
    tengine._fyers_client = fake
    tengine._get_candles("NSE:A-EQ", allow_refresh=True)
    tengine._get_candles("NSE:A-EQ", allow_refresh=True)
    assert len(fake.history_calls) == 1  # second call hit the cache, not FYERS


def test_find_best_setup_refuses_to_scan_when_feed_not_connected():
    tengine = TradingEngine()
    tengine._fyers_client = FakeFyersClient()
    tengine._live_feed = LiveFeed(access_token="dummy", client_id="dummy")  # never started -> DISCONNECTED

    from app.models import UserSettings
    settings = UserSettings(trading_capital=10000, min_risk_reward=1.5)
    best_setup, signal_row, candidates, universe_size, eligible_count, avg_bar_volume = tengine._find_best_setup(
        db=None, user_settings=settings, regime="BULLISH"
    )
    assert best_setup is None
    assert universe_size == 0
    assert len(fake_calls(tengine)) == 0


def fake_calls(tengine):
    return getattr(tengine._fyers_client, "history_calls", [])


def test_get_candles_fetches_a_warmup_window_not_just_today():
    """Regression test for the 11:20 AM start-delay bug: the live engine
    must request several PRIOR calendar days of history too (zero added API
    cost - one request either way), not just today, so EMA/RSI/ATR/regime
    classification are warm from market open instead of needing ~25 FRESH
    same-day bars to accumulate first."""
    tengine = TradingEngine()
    fake = FakeFyersClient()
    tengine._fyers_client = fake

    tengine._get_candles("NSE:A-EQ", allow_refresh=True)

    assert len(fake.history_ranges) == 1
    range_from, range_to = fake.history_ranges[0]
    today = dt.date.today()
    expected_start = today - dt.timedelta(days=WARMUP_LOOKBACK_DAYS)
    assert range_from == expected_start.isoformat()
    assert range_to == today.isoformat()
    assert range_from != range_to  # the old bug requested (today, today)


def test_get_candles_trims_to_a_bounded_max_length():
    from app.engine.trading_engine import MAX_CANDLES_PER_SYMBOL

    class ManyCandlesClient(FakeFyersClient):
        def get_history(self, symbol, resolution, range_from, range_to, caller="unspecified"):
            self.history_calls.append(symbol)
            self.history_ranges.append((range_from, range_to))
            return [{"timestamp": i, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}
                    for i in range(MAX_CANDLES_PER_SYMBOL + 50)]

    tengine = TradingEngine()
    tengine._fyers_client = ManyCandlesClient()
    result = tengine._get_candles("NSE:A-EQ", allow_refresh=True)
    assert len(result) == MAX_CANDLES_PER_SYMBOL
