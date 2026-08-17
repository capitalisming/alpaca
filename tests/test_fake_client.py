from datetime import datetime, timezone

import pytest

from adapters.fake_client import FakeAlpacaClient
from core.risk_engine import OpenPosition
from core.schemas import Action, AssetClass, OrderType, RiskDecision, RiskVerdict, TradingProposal


def _proposal(**overrides) -> TradingProposal:
    data = dict(action=Action.BUY, symbol="AAPL", confidence=0.7,
                reason="t", position_size=0.05)
    data.update(overrides)
    return TradingProposal(**data)


def test_fake_client_starts_flat():
    c = FakeAlpacaClient()
    assert c.get_open_positions() == []
    assert c.get_daily_pnl_pct() == 0.0
    assert c.get_recent_orders(3600) == []


def test_fake_client_seeds_are_respected():
    c = FakeAlpacaClient(equity=50_000, open_positions=[OpenPosition("MSFT", 0.2)], daily_pnl_pct=-0.01)
    assert c.get_open_positions() == [OpenPosition("MSFT", 0.2)]
    assert c.get_daily_pnl_pct() == -0.01


def test_fake_submit_order_rejects_non_riskdecision():
    c = FakeAlpacaClient()
    with pytest.raises(TypeError):
        c.submit_order(_proposal())  # not wrapped in a RiskDecision


def test_fake_submit_order_rejects_non_executable_decision():
    c = FakeAlpacaClient()
    d = RiskDecision(proposal=_proposal(), verdict=RiskVerdict.REJECT, rule_ids=["X"], reasons=["r"])
    with pytest.raises(ValueError):
        c.submit_order(d)


def test_fake_submit_order_records_recent_order_and_returns_result():
    c = FakeAlpacaClient()
    d = RiskDecision(proposal=_proposal(), verdict=RiskVerdict.APPROVE, rule_ids=["RISK-OK"], reasons=[])
    result = c.submit_order(d)
    assert result.status == "filled"
    assert result.order_id.startswith("fake-")
    recent = c.get_recent_orders(3600)
    assert len(recent) == 1
    assert recent[0].symbol == "AAPL"


def test_fake_submit_order_rejects_hold_and_non_equity():
    c = FakeAlpacaClient()
    hold = RiskDecision(
        proposal=_proposal(action=Action.HOLD, position_size=0.0),
        verdict=RiskVerdict.APPROVE, rule_ids=[], reasons=[],
    )
    with pytest.raises(ValueError):
        c.submit_order(hold)

    crypto = RiskDecision(
        proposal=_proposal(asset_class=AssetClass.CRYPTO, symbol="BTCUSD"),
        verdict=RiskVerdict.APPROVE, rule_ids=[], reasons=[],
    )
    with pytest.raises(ValueError):
        c.submit_order(crypto)
