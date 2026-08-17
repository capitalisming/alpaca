from adapters.fake_client import FakeAlpacaClient
from core.risk_engine import OpenPosition
from core.portfolio_state import build_risk_context


def test_build_risk_context_reflects_client_state():
    client = FakeAlpacaClient(open_positions=[OpenPosition("MSFT", 0.1)], daily_pnl_pct=-0.02)
    ctx = build_risk_context(client)
    assert ctx.current_exposure() == 0.1
    assert ctx.daily_pnl_pct == -0.02
    assert ctx.recent_orders == []
