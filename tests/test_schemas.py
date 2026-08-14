from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core.schemas import Action, AssetClass, OrderType, TradingProposal


def _base(**overrides):
    data = dict(
        action=Action.BUY,
        symbol="aapl",
        confidence=0.7,
        reason="momentum breakout",
        position_size=0.05,
    )
    data.update(overrides)
    return TradingProposal(**data)


def test_symbol_is_normalized_upper():
    p = _base(symbol="aapl")
    assert p.symbol == "AAPL"


def test_client_order_id_is_generated_and_unique():
    a, b = _base(), _base()
    assert a.client_order_id != b.client_order_id


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        _base(confidence=1.5)


def test_limit_order_requires_price():
    with pytest.raises(ValidationError):
        _base(order_type=OrderType.LIMIT)
    p = _base(order_type=OrderType.LIMIT, limit_price=150.0)
    assert p.limit_price == 150.0


def test_hold_requires_zero_position_size():
    with pytest.raises(ValidationError):
        _base(action=Action.HOLD, position_size=0.05)
    p = _base(action=Action.HOLD, position_size=0.0)
    assert p.action == Action.HOLD


def test_asset_class_defaults_to_us_equity():
    assert _base().asset_class == AssetClass.US_EQUITY
