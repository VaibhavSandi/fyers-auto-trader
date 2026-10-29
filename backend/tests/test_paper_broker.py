from app.engine.paper_broker import simulate_fill, PARTIAL_FILL_THRESHOLD, REJECT_THRESHOLD


def test_no_volume_context_fills_fully():
    fill = simulate_fill(symbol="NSE:X-EQ", side="BUY", quantity=1_000_000, reference_price=100)
    assert fill.status == "FILLED"
    assert fill.filled_quantity == 1_000_000


def test_small_order_relative_to_volume_fills_fully():
    fill = simulate_fill(symbol="NSE:X-EQ", side="BUY", quantity=100, reference_price=100,
                          avg_bar_volume=10_000)  # 1% participation - well under the partial threshold
    assert fill.status == "FILLED"
    assert fill.filled_quantity == 100


def test_medium_order_partially_fills(seed=1):
    fill = simulate_fill(symbol="NSE:X-EQ", side="BUY", quantity=1500, reference_price=100,
                          avg_bar_volume=10_000, seed=1)  # 15% participation
    assert fill.status == "PARTIAL"
    assert 0 < fill.filled_quantity < 1500
    assert "Partial fill" in fill.message


def test_oversized_order_is_rejected_not_partially_filled():
    fill = simulate_fill(symbol="NSE:X-EQ", side="BUY", quantity=5000, reference_price=100,
                          avg_bar_volume=10_000)  # 50% participation - beyond reject threshold
    assert fill.status == "REJECTED"
    assert fill.filled_quantity == 0
    assert "too large" in fill.message.lower()


def test_fill_is_deterministic_given_a_seed():
    a = simulate_fill(symbol="NSE:X-EQ", side="BUY", quantity=1500, reference_price=100,
                       avg_bar_volume=10_000, seed=42)
    b = simulate_fill(symbol="NSE:X-EQ", side="BUY", quantity=1500, reference_price=100,
                       avg_bar_volume=10_000, seed=42)
    assert a.filled_quantity == b.filled_quantity
    assert a.average_price == b.average_price


def test_partial_fill_never_exceeds_requested_quantity():
    for seed in range(20):
        fill = simulate_fill(symbol="NSE:X-EQ", side="BUY", quantity=1500, reference_price=100,
                              avg_bar_volume=10_000, seed=seed)
        assert fill.filled_quantity <= 1500


def test_fill_ratio_tapers_as_participation_increases():
    """Higher participation should, on average, fill a smaller fraction -
    not a strict guarantee per-call (there's jitter), but true on average."""
    def avg_fill_ratio(quantity):
        ratios = []
        for seed in range(30):
            fill = simulate_fill(symbol="NSE:X-EQ", side="BUY", quantity=quantity, reference_price=100,
                                  avg_bar_volume=10_000, seed=seed)
            ratios.append(fill.filled_quantity / quantity)
        return sum(ratios) / len(ratios)

    low_participation_qty = int(10_000 * (PARTIAL_FILL_THRESHOLD + 0.02))
    high_participation_qty = int(10_000 * (REJECT_THRESHOLD - 0.02))
    assert avg_fill_ratio(low_participation_qty) > avg_fill_ratio(high_participation_qty)


def test_sell_side_slippage_moves_price_down_not_up():
    fill = simulate_fill(symbol="NSE:X-EQ", side="SELL", quantity=10, reference_price=100)
    assert fill.average_price < 100


def test_buy_side_slippage_moves_price_up_not_down():
    fill = simulate_fill(symbol="NSE:X-EQ", side="BUY", quantity=10, reference_price=100)
    assert fill.average_price > 100


def test_invalid_inputs_are_rejected():
    assert simulate_fill(symbol="X", side="BUY", quantity=0, reference_price=100).status == "REJECTED"
    assert simulate_fill(symbol="X", side="BUY", quantity=10, reference_price=0).status == "REJECTED"
