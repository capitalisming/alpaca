"""Opt-in paper-account smoke test; never enabled by the normal test run."""

from datetime import datetime, timezone
import os

import pytest

from adapters.alpaca_client import AlpacaRestClient
from core.config import RiskConfig
from core.risk_engine import RiskContext, evaluate
from core.schemas import Action, TradingProposal


RUN_PAPER_TEST = os.getenv("RUN_ALPACA_PAPER_INTEGRATION") == "1"


@pytest.mark.skipif(
    not RUN_PAPER_TEST,
    reason="set RUN_ALPACA_PAPER_INTEGRATION=1 for the manual paper-order smoke test",
)
def test_vertical_slice_submits_real_paper_order():
    """Submit a small AAPL paper order after the real deterministic risk gate."""

    if os.getenv("CI"):
        pytest.fail("paper integration must not run in CI")
    if os.getenv("ALPACA_PAPER_TRADE", "").strip().lower() != "true":
        pytest.fail("ALPACA_PAPER_TRADE=true is required")

    client = AlpacaRestClient()
    now = datetime.now(timezone.utc)
    proposal = TradingProposal(
        action=Action.BUY,
        symbol="AAPL",
        confidence=0.9,
        reason="TASK-01 manual paper integration smoke test",
        position_size=0.0001,
        timestamp=now,
    )
    context = RiskContext(
        now=now,
        open_positions=client.get_open_positions(),
        recent_orders=client.get_recent_orders(30),
        daily_pnl_pct=client.get_daily_pnl_pct(),
    )
    risk_decision = evaluate(proposal, context, RiskConfig())

    assert risk_decision.is_executable, risk_decision.reasons
    result = client.submit_order(risk_decision)

    assert result.order_id
    assert result.status
