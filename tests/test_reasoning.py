from core.config import RiskConfig
from core.risk_engine import RiskContext, evaluate
from core.schemas import Action, TradingProposal
from agent.reasoning import dummy_signal
from datetime import datetime, timezone


def test_dummy_signal_produces_valid_proposal():
    p = dummy_signal("msft")
    assert isinstance(p, TradingProposal)
    assert p.symbol == "MSFT"
    assert p.action == Action.BUY


def test_dummy_signal_clears_default_risk_config_on_a_flat_portfolio():
    """The whole point of dummy_signal(): it must actually clear the risk
    engine's default thresholds, otherwise the vertical slice always
    exercises the reject path and proves nothing about the happy path."""
    p = dummy_signal()
    ctx = RiskContext(now=datetime.now(timezone.utc))
    decision = evaluate(p, ctx, RiskConfig())
    assert decision.is_executable
