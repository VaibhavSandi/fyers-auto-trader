import time

from app.fyers.websocket_feed import LiveFeed, STALE_AFTER_SECONDS, MAX_STANDARD_SYMBOLS
from app.fyers.price_cache import PriceCache


def test_feed_is_stale_if_no_tick_received_recently():
    feed = LiveFeed(access_token="dummy", client_id="dummy")
    feed._last_tick_at = time.time() - (STALE_AFTER_SECONDS + 5)
    assert feed.is_stale() is True


def test_feed_is_not_stale_right_after_a_tick():
    feed = LiveFeed(access_token="dummy", client_id="dummy")
    feed._on_message({"symbol": "NSE:RELIANCE-EQ", "ltp": 1500.0})
    assert feed.is_stale() is False
    assert feed.get_ltp("NSE:RELIANCE-EQ") == 1500.0


def test_unknown_symbol_returns_no_price_rather_than_guessing():
    feed = LiveFeed(access_token="dummy", client_id="dummy")
    assert feed.get_ltp("NSE:UNKNOWN-EQ") is None


def test_tick_is_written_into_the_shared_price_cache():
    cache = PriceCache()
    feed = LiveFeed(access_token="dummy", client_id="dummy", price_cache=cache)
    feed._on_message({"symbol": "NSE:RELIANCE-EQ", "ltp": 1500.0, "bid_price": 1499.5, "ask_price": 1500.5})
    tick = cache.get("NSE:RELIANCE-EQ")
    assert tick.ltp == 1500.0
    assert tick.bid == 1499.5


def test_subscribe_is_idempotent_no_duplicate_subscriptions():
    feed = LiveFeed(access_token="dummy", client_id="dummy")
    feed.subscribe(["NSE:A-EQ", "NSE:B-EQ"])
    feed.subscribe(["NSE:A-EQ", "NSE:B-EQ", "NSE:C-EQ"])  # A and B already subscribed
    assert feed.subscribed_count() == 3
    assert set(feed.subscribed_symbols()) == {"NSE:A-EQ", "NSE:B-EQ", "NSE:C-EQ"}


def test_subscribe_enforces_standard_plan_symbol_cap():
    feed = LiveFeed(access_token="dummy", client_id="dummy")
    too_many = [f"NSE:SYM{i}-EQ" for i in range(MAX_STANDARD_SYMBOLS + 10)]
    feed.subscribe(too_many)
    assert feed.subscribed_count() == MAX_STANDARD_SYMBOLS


def test_subscribe_past_cap_drops_extra_symbols_without_crashing():
    feed = LiveFeed(access_token="dummy", client_id="dummy")
    feed.subscribe([f"NSE:SYM{i}-EQ" for i in range(MAX_STANDARD_SYMBOLS)])
    assert feed.subscribed_count() == MAX_STANDARD_SYMBOLS
    feed.subscribe(["NSE:ONE_MORE-EQ"])
    assert feed.subscribed_count() == MAX_STANDARD_SYMBOLS  # still capped, not crashed


def test_status_disconnected_before_start():
    feed = LiveFeed(access_token="dummy", client_id="dummy")
    assert feed.status() == "DISCONNECTED"


def test_status_connected_after_connect_and_fresh_tick():
    feed = LiveFeed(access_token="dummy", client_id="dummy")
    feed.connected = True
    feed._on_message({"symbol": "NSE:A-EQ", "ltp": 100})
    assert feed.status() == "CONNECTED"


def test_status_stale_when_connected_but_no_recent_tick():
    feed = LiveFeed(access_token="dummy", client_id="dummy")
    feed.connected = True
    feed._last_tick_at = time.time() - (STALE_AFTER_SECONDS + 5)
    assert feed.status() == "STALE_DATA"


def test_invalid_symbol_subscription_error_does_not_disconnect_the_feed():
    """A delisted/renamed symbol being rejected on subscribe must not take
    down monitoring for every OTHER subscribed symbol."""
    feed = LiveFeed(access_token="dummy", client_id="dummy")
    feed.connected = True
    feed.subscribe(["NSE:GOOD-EQ", "NSE:BAD-EQ"])
    feed._on_error({
        "code": -300, "message": "Please provide a valid symbol", "s": "error",
        "type": "sub", "invalid_symbols": ["NSE:BAD-EQ"],
    })
    assert feed.connected is True
    assert "NSE:BAD-EQ" not in feed.subscribed_symbols()
    assert "NSE:GOOD-EQ" in feed.subscribed_symbols()


def test_genuine_connection_error_does_disconnect_the_feed():
    feed = LiveFeed(access_token="dummy", client_id="dummy")
    feed.connected = True
    feed._on_error("connection reset")
    assert feed.connected is False
