from app.engine import position_sizing


def test_quantity_derived_from_risk_per_share():
    result = position_sizing.calculate_position_size(
        available_capital=10000, max_risk_amount=50, entry_price=100, risk_per_share=10,
    )
    assert result.quantity == 5  # 50 / 10
    assert result.sizing_limited_by == "risk"


def test_capital_constraint_caps_quantity_even_if_risk_allows_more():
    result = position_sizing.calculate_position_size(
        available_capital=500, max_risk_amount=1000, entry_price=100, risk_per_share=5,
    )
    # risk would allow 200 shares, but capital (80% of 500 = 400) allows only ~4 shares
    assert result.quantity < 200
    assert result.sizing_limited_by == "capital"


def test_zero_quantity_when_risk_per_share_too_large():
    result = position_sizing.calculate_position_size(
        available_capital=10000, max_risk_amount=20, entry_price=100, risk_per_share=50,
    )
    assert result.quantity == 0
    assert result.reason is not None


def test_zero_quantity_when_capital_insufficient_for_one_share():
    result = position_sizing.calculate_position_size(
        available_capital=50, max_risk_amount=1000, entry_price=1000, risk_per_share=10,
    )
    assert result.quantity == 0


def test_never_exceeds_capital_allocation_ceiling():
    result = position_sizing.calculate_position_size(
        available_capital=10000, max_risk_amount=100000, entry_price=10, risk_per_share=0.1,
    )
    assert result.capital_required <= 10000 * (position_sizing.MAX_CAPITAL_ALLOCATION_PCT / 100) * 1.01
