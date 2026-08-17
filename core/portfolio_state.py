"""
core/portfolio_state.py

Turns "whatever client we were given" into the RiskContext the risk engine
actually consumes. The point of this module existing separately is that
risk_engine.py never imports adapters/* — this is the only seam allowed
to cross that boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone

from adapters.alpaca_client import AlpacaClient
from core.risk_engine import RiskContext


def build_risk_context(client: AlpacaClient, lookback_seconds: int = 3600) -> RiskContext:
    return RiskContext(
        now=datetime.now(timezone.utc),
        open_positions=client.get_open_positions(),
        recent_orders=client.get_recent_orders(lookback_seconds),
        daily_pnl_pct=client.get_daily_pnl_pct(),
    )
