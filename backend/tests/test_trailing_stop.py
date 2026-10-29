from app.engine.trailing_stop import update_trailing_stop


def test_no_trail_before_activation_threshold():
    result = update_trailing_stop(
        direction="BUY", entry_price=100, original_stop_loss=95, current_stop_loss=95,
        current_price=102, atr_value=2,
    )
    assert result.trailing_active is False
    assert result.new_stop_loss == 95


def test_trail_moves_to_breakeven_or_better_once_activated_buy():
    result = update_trailing_stop(
        direction="BUY", entry_price=100, original_stop_loss=95, current_stop_loss=95,
        current_price=106, atr_value=2,
    )
    assert result.trailing_active is True
    assert result.new_stop_loss >= 100  # never worse than breakeven once trailing


def test_trail_never_moves_backwards_buy():
    result = update_trailing_stop(
        direction="BUY", entry_price=100, original_stop_loss=95, current_stop_loss=103,
        current_price=104, atr_value=10,  # wide ATR would otherwise suggest a lower stop
    )
    assert result.new_stop_loss >= 103


def test_trail_moves_down_for_sell_positions():
    result = update_trailing_stop(
        direction="SELL", entry_price=100, original_stop_loss=105, current_stop_loss=105,
        current_price=94, atr_value=2,
    )
    assert result.trailing_active is True
    assert result.new_stop_loss <= 100


def test_trail_never_increases_original_risk():
    result = update_trailing_stop(
        direction="BUY", entry_price=100, original_stop_loss=95, current_stop_loss=95,
        current_price=101, atr_value=2,
    )
    # even just barely past activation, the stop can never be moved below the original stop
    assert result.new_stop_loss >= 95
