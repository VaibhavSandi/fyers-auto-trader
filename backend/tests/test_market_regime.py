import datetime as dt

from app.engine import market_regime

IST = dt.timedelta(hours=5, minutes=30)
EPOCH = dt.datetime(1970, 1, 1)


def _epoch(ist_dt: dt.datetime) -> int:
    utc_dt = ist_dt - IST
    return int((utc_dt - EPOCH).total_seconds())


def _flat_day(day: dt.date, bars: int = 30, price: float = 100.0) -> list[dict]:
    start = dt.datetime.combine(day, dt.time(9, 15))
    return [{"timestamp": _epoch(start + dt.timedelta(minutes=5 * i)),
              "open": price, "high": price * 1.001, "low": price * 0.999,
              "close": price, "volume": 50_000} for i in range(bars)]


def _trending_day(day: dt.date, bars: int, start_price: float, drift_pct: float) -> list[dict]:
    start = dt.datetime.combine(day, dt.time(9, 15))
    candles = []
    price = start_price
    for i in range(bars):
        price = price * (1 + drift_pct / 100)
        candles.append({"timestamp": _epoch(start + dt.timedelta(minutes=5 * i)),
                         "open": price, "high": price * 1.001, "low": price * 0.999,
                         "close": price, "volume": 50_000})
    return candles


def test_day_change_pct_uses_only_todays_session_not_the_whole_warmup_window():
    """Regression test: classify_market_regime() must compute "today's %
    change" from TODAY's bars only, even when handed a multi-day warm-up
    window (prior day + today) for the >=25-bar length check. Before the
    session_slice() fix, a wildly-moved prior day would silently distort
    today's reported change%."""
    day1 = dt.date(2024, 1, 2)
    day2 = dt.date(2024, 1, 3)

    # Day 1: a huge, unrelated move (should NOT leak into "today's" change%)
    prior_day = _trending_day(day1, 30, 100.0, drift_pct=5.0)  # ends far above 100
    # Day 2 (today): dead flat - today's change% should be ~0%, not reflecting day1's huge move
    today = _flat_day(day2, bars=30, price=prior_day[-1]["close"])

    combined = prior_day + today
    result = market_regime.classify_market_regime(combined, combined)

    assert result.nifty_change_pct is not None
    assert abs(result.nifty_change_pct) < 0.5  # today was flat - must not inherit day1's +5%/bar drift


def test_len_check_still_uses_the_full_warmup_window():
    """The >=25-bar minimum must be checked against the FULL window (prior
    day + today), not just today's slice - that's the whole point of
    warming up with prior-day candles so today's early bars aren't starved."""
    day1 = dt.date(2024, 1, 2)
    day2 = dt.date(2024, 1, 3)
    prior_day = _flat_day(day1, bars=30)
    today_so_far = _flat_day(day2, bars=3, price=prior_day[-1]["close"])  # only 3 bars into today

    combined = prior_day + today_so_far
    result = market_regime.classify_market_regime(combined, combined)

    # with only 3 bars of "today" alone this would have been HIGH_VOLATILITY_UNSAFE
    # pre-fix; the full 33-bar warmed-up window must pass the length check.
    assert result.regime != "HIGH_VOLATILITY_UNSAFE"
