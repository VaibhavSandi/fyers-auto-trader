"""
The automatic stock universe.

The user never maintains a watchlist. Instead we start from a curated list
of the most consistently liquid, large-cap NSE equities (Nifty 50 constituents
plus a handful of other heavily-traded large caps) and then apply live
liquidity/volatility/trend filters (scanner.py) to shrink that down to
today's actually-tradeable subset.

We deliberately do NOT scan the entire exchange: thinly traded stocks are
excluded by construction, not just by filter, because wide spreads and poor
fills on illiquid names are a real capital-protection risk for a small
intraday account.
"""
from __future__ import annotations

NSE_EQ = "NSE:{}-EQ"

CURATED_LIQUID_UNIVERSE: list[str] = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "SBIN", "BHARTIARTL",
    "ITC", "KOTAKBANK", "LT", "AXISBANK", "HINDUNILVR", "BAJFINANCE", "MARUTI",
    "SUNPHARMA", "TITAN", "ASIANPAINT", "ULTRACEMCO", "NTPC", "ONGC",
    # NOTE: "TATAMOTORS" was removed - FYERS rejected it as an invalid
    # symbol (-300, "Please provide a valid symbol") on the live websocket,
    # most likely due to the 2025 Tata Motors Commercial Vehicles demerger
    # changing/retiring the old symbol. Verify the current correct symbol
    # on FYERS' symbol master before re-adding a Tata Motors entry here.
    "TATASTEEL", "POWERGRID", "M&M", "WIPRO", "HCLTECH",
    "ADANIENT", "ADANIPORTS", "COALINDIA", "BAJAJFINSV", "NESTLEIND",
    "GRASIM", "JSWSTEEL", "DRREDDY", "CIPLA", "EICHERMOT", "HEROMOTOCO",
    "HINDALCO", "BPCL", "INDUSINDBK", "TECHM", "DIVISLAB", "SBILIFE",
    "HDFCLIFE", "BRITANNIA", "APOLLOHOSP", "PIDILITIND", "SHREECEM",
    "BAJAJ-AUTO", "VEDL", "GAIL",
]

INDEX_SYMBOLS = {
    "NIFTY50": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
}


def to_fyers_symbol(trading_symbol: str) -> str:
    return NSE_EQ.format(trading_symbol)


def get_universe_symbols() -> list[str]:
    return [to_fyers_symbol(s) for s in CURATED_LIQUID_UNIVERSE]
