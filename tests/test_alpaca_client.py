from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from alpaca.trading.enums import OrderSide, QueryOrderStatus
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest
import pytest

import adapters.alpaca_client as alpaca_adapter
from adapters.alpaca_client import AlpacaRestClient
from core.schemas import Action, OrderType, RiskDecision, RiskVerdict, TradingProposal


class FakeTradingClient:
    def __init__(self):
        self.account = SimpleNamespace(equity="100000", last_equity="98000")
        self.positions = []
        self.orders = []
        self.order_response = {
            "id": "order-123",
            "status": "accepted",
            "filled_qty": None,
        }
        self.submitted = []
        self.order_filter = None

    def get_account(self):
        return self.account

    def get_all_positions(self):
        return self.positions

    def get_orders(self, filter):
        self.order_filter = filter
        return self.orders

    def submit_order(self, order_data):
        self.submitted.append(order_data)
        return self.order_response


def proposal(**overrides):
    data = dict(
        action=Action.BUY,
        symbol="AAPL",
        confidence=0.8,
        reason="adapter test",
        position_size=0.05,
        client_order_id="proposal-order-1",
    )
    data.update(overrides)
    return TradingProposal(**data)


def decision(*, verdict=RiskVerdict.APPROVE, adjusted=None, **proposal_overrides):
    return RiskDecision(
        proposal=proposal(**proposal_overrides),
        verdict=verdict,
        adjusted_position_size=adjusted,
    )


def test_constructor_builds_paper_client(monkeypatch):
    captured = {}

    def fake_constructor(**kwargs):
        captured.update(kwargs)
        return FakeTradingClient()

    monkeypatch.setattr(alpaca_adapter, "TradingClient", fake_constructor)
    client = AlpacaRestClient(api_key="paper-key", secret_key="paper-secret")

    assert isinstance(client._client, FakeTradingClient)
    assert captured == {
        "api_key": "paper-key",
        "secret_key": "paper-secret",
        "paper": True,
    }


def test_constructor_requires_credentials(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="required"):
        AlpacaRestClient()


def test_constructor_rejects_live_mode_even_with_injected_client(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_TRADE", "false")
    with pytest.raises(ValueError, match="ALPACA_PAPER_TRADE=true"):
        AlpacaRestClient(trading_client=FakeTradingClient())


def test_get_open_positions_converts_market_value_to_absolute_exposure():
    fake = FakeTradingClient()
    fake.positions = [
        SimpleNamespace(symbol="aapl", market_value="5000"),
        SimpleNamespace(symbol="MSFT", market_value="-2500"),
    ]

    positions = AlpacaRestClient(trading_client=fake).get_open_positions()

    assert [(p.symbol, p.exposure) for p in positions] == [
        ("AAPL", 0.05),
        ("MSFT", 0.025),
    ]


def test_get_daily_pnl_pct_uses_last_equity():
    client = AlpacaRestClient(trading_client=FakeTradingClient())
    assert client.get_daily_pnl_pct() == pytest.approx(0.0204081633)


def test_get_recent_orders_maps_sides_and_filters_stale_results():
    fake = FakeTradingClient()
    now = datetime.now(timezone.utc)
    fake.orders = [
        SimpleNamespace(symbol="aapl", side=OrderSide.BUY, submitted_at=now),
        SimpleNamespace(
            symbol="MSFT",
            side=OrderSide.SELL,
            submitted_at=now - timedelta(seconds=10),
        ),
        SimpleNamespace(
            symbol="OLD",
            side=OrderSide.BUY,
            submitted_at=now - timedelta(minutes=10),
        ),
    ]

    orders = AlpacaRestClient(trading_client=fake).get_recent_orders(60)

    assert [(o.symbol, o.action) for o in orders] == [
        ("AAPL", Action.BUY),
        ("MSFT", Action.SELL),
    ]
    assert fake.order_filter.status == QueryOrderStatus.ALL
    assert fake.order_filter.after.tzinfo == timezone.utc


@pytest.mark.parametrize("lookback", [-1, 1.5, True])
def test_get_recent_orders_rejects_invalid_lookback(lookback):
    with pytest.raises(ValueError, match="lookback_seconds"):
        AlpacaRestClient(trading_client=FakeTradingClient()).get_recent_orders(lookback)


def test_submit_order_requires_risk_decision():
    fake = FakeTradingClient()
    with pytest.raises(TypeError, match="RiskDecision"):
        AlpacaRestClient(trading_client=fake).submit_order(proposal())
    assert fake.submitted == []


def test_submit_order_refuses_rejected_decision_before_account_call():
    fake = FakeTradingClient()
    rejected = decision(verdict=RiskVerdict.REJECT)
    with pytest.raises(ValueError, match="non-executable"):
        AlpacaRestClient(trading_client=fake).submit_order(rejected)
    assert fake.submitted == []


def test_submit_order_refuses_hold_decision():
    fake = FakeTradingClient()
    hold = decision(action=Action.HOLD, position_size=0.0)
    with pytest.raises(ValueError, match="HOLD"):
        AlpacaRestClient(trading_client=fake).submit_order(hold)
    assert fake.submitted == []


def test_submit_market_order_uses_adjusted_size_and_client_order_id(caplog):
    fake = FakeTradingClient()
    modified = decision(
        verdict=RiskVerdict.MODIFY,
        adjusted=0.02,
        position_size=0.05,
        client_order_id="idempotency-123",
    )

    with caplog.at_level("INFO"):
        result = AlpacaRestClient(trading_client=fake).submit_order(modified)

    request = fake.submitted[0]
    assert isinstance(request, MarketOrderRequest)
    assert request.symbol == "AAPL"
    assert request.side == OrderSide.BUY
    assert request.notional == 2000
    assert request.client_order_id == "idempotency-123"
    assert result.order_id == "order-123"
    assert result.status == "accepted"
    assert "client_order_id=idempotency-123" in caplog.text


def test_submit_limit_order_converts_exposure_to_quantity():
    fake = FakeTradingClient()
    approved = decision(
        order_type=OrderType.LIMIT,
        limit_price=200,
        position_size=0.01,
    )

    AlpacaRestClient(trading_client=fake).submit_order(approved)

    request = fake.submitted[0]
    assert isinstance(request, LimitOrderRequest)
    assert request.qty == 5
    assert request.limit_price == 200
    assert request.client_order_id == "proposal-order-1"


def test_network_errors_are_not_hidden():
    fake = FakeTradingClient()

    def fail(order_data):
        raise ConnectionError("paper endpoint unavailable")

    fake.submit_order = fail
    with pytest.raises(ConnectionError, match="paper endpoint unavailable"):
        AlpacaRestClient(trading_client=fake).submit_order(decision())
