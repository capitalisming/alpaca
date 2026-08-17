"""
agent/reasoning.py

PLACEHOLDER. This is not a trading strategy and must not be mistaken for
one. Its only job is to emit valid TradingProposal instances so the rest of
the pipeline (risk engine -> execution -> trace) can be proven end-to-end
before Tracks are announced. Delete/replace this module's internals on
Day 1 of the hackathon once the real reasoning layer exists — the schema
contract (core/schemas.py) is what stays constant, not this function.
"""

from __future__ import annotations

from core.schemas import Action, AssetClass, TradingProposal


def dummy_signal(symbol: str = "AAPL") -> TradingProposal:
    """Deterministic placeholder: always proposes a small, boring BUY.
    Confidence is set just above the default risk_engine threshold (0.55)
    so the vertical slice actually exercises the APPROVE path by default,
    not just the reject paths already covered by the risk engine's own
    test suite.
    """
    return TradingProposal(
        action=Action.BUY,
        symbol=symbol,
        asset_class=AssetClass.US_EQUITY,
        confidence=0.60,
        reason="PLACEHOLDER signal — dummy_signal(), not a real strategy",
        position_size=0.02,
    )
