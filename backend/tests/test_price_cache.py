from app.fyers.price_cache import PriceCache


def test_update_and_get():
    cache = PriceCache()
    cache.update("NSE:X-EQ", ltp=100.5, bid=100.4, ask=100.6, volume=1000)
    tick = cache.get("NSE:X-EQ")
    assert tick.ltp == 100.5
    assert tick.bid == 100.4
    assert tick.ask == 100.6


def test_unknown_symbol_returns_none_rather_than_guessing():
    cache = PriceCache()
    assert cache.get("NSE:UNKNOWN-EQ") is None


def test_is_stale_true_for_missing_symbol():
    cache = PriceCache()
    assert cache.is_stale("NSE:X-EQ", max_age_seconds=10) is True


def test_is_stale_false_for_fresh_tick():
    cache = PriceCache()
    cache.update("NSE:X-EQ", ltp=100)
    assert cache.is_stale("NSE:X-EQ", max_age_seconds=10) is False


def test_is_stale_true_once_tick_ages_past_threshold():
    cache = PriceCache()
    cache.update("NSE:X-EQ", ltp=100)
    cache._ticks["NSE:X-EQ"].received_at -= 30
    assert cache.is_stale("NSE:X-EQ", max_age_seconds=10) is True


def test_zero_or_negative_price_is_rejected_not_cached():
    cache = PriceCache()
    cache.update("NSE:X-EQ", ltp=0)
    assert cache.get("NSE:X-EQ") is None
    cache.update("NSE:X-EQ", ltp=-5)
    assert cache.get("NSE:X-EQ") is None


def test_snapshot_ages_empty_cache():
    cache = PriceCache()
    snap = cache.snapshot_ages()
    assert snap == {"symbol_count": 0, "oldest_age_seconds": None, "newest_age_seconds": None}


def test_snapshot_ages_with_data():
    cache = PriceCache()
    cache.update("NSE:A-EQ", ltp=1)
    cache.update("NSE:B-EQ", ltp=2)
    snap = cache.snapshot_ages()
    assert snap["symbol_count"] == 2
    assert snap["oldest_age_seconds"] is not None
    assert snap["newest_age_seconds"] is not None


def test_update_overwrites_previous_tick_for_same_symbol():
    cache = PriceCache()
    cache.update("NSE:X-EQ", ltp=100)
    cache.update("NSE:X-EQ", ltp=105)
    assert cache.get("NSE:X-EQ").ltp == 105


def test_clear_empties_the_cache():
    cache = PriceCache()
    cache.update("NSE:X-EQ", ltp=100)
    cache.clear()
    assert cache.get("NSE:X-EQ") is None
    assert cache.all_symbols() == []
