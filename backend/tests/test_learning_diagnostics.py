from app.learning.diagnostics import diagnose_trades
from app.models import Trade, BacktestTrade


def test_diagnose_trades_handles_live_trade_rows_using_market_condition(db_session):
    """Regression test: Trade (the live journal) stores its regime under
    `market_condition`, not `market_regime` - diagnose_trades() must read
    whichever one the object actually has, not crash on live rows."""
    db_session.add(Trade(date="2024-01-01", symbol="NSE:A-EQ", exit_reason="TARGET",
                          net_pnl=50.0, strategy_score=8, market_condition="BULLISH"))
    db_session.add(Trade(date="2024-01-01", symbol="NSE:B-EQ", exit_reason="STOP_LOSS",
                          net_pnl=-20.0, strategy_score=7, market_condition="NEUTRAL"))
    db_session.commit()

    trades = db_session.query(Trade).all()
    result = diagnose_trades(trades)  # must not raise

    assert result["total_trades_analyzed"] == 2
    assert result["by_market_regime"]["BULLISH"]["wins"] == 1
    assert result["by_market_regime"]["NEUTRAL"]["losses"] == 1
    assert result["by_exit_reason"]["TARGET"]["net_pnl"] == 50.0


def test_diagnose_trades_still_handles_backtest_trade_rows_using_market_regime():
    bt = BacktestTrade(symbol="NSE:A-EQ", exit_reason="TARGET", net_pnl=10.0,
                        strategy_score=9, market_regime="STRONG_BULLISH")
    result = diagnose_trades([bt])
    assert result["by_market_regime"]["STRONG_BULLISH"]["wins"] == 1
