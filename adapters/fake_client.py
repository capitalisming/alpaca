"""
adapters/fake_client.py

Structurally satisfies the same AlpacaClient Protocol as AlpacaRestClient,
with zero network calls. Lets the full pipeline (reasoning -> risk engine ->
execution -> trace) run and be demoed/tested before real credentials exist,
and after rotation the only change needed is which client gets constructed —
nothing about run_vertical_slice.py's logic changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from adapters.alpaca_client import AlpacaClient, ExecutionResult
from core.risk_engine import OpenPosition, RecentOrder
from core.schemas import Action, AssetClass, OrderType, RiskDecision


@dataclass(frozen=True)
class FakeExecutionResult(ExecutionResult):
    order_id: str
    status: str
    filled_qty: float | None
    raw: dict


@dataclass
class FakeAlpacaClient:
    """In-memory stand-in. Starting state is deliberately boring/safe:
    no open positions, flat PnL — override via constructor args for
    scenario testing (e.g. simulating an already-near-limit portfolio)."""

    equity: float = 100_000.0
    open_positions: list[OpenPosition] = field(default_factory=list)
    daily_pnl_pct: float = 0.0
    _orders: list[RecentOrder] = field(default_factory=list, repr=False)

    def get_open_positions(self) -> list[OpenPosition]:
        return list(self.open_positions)

    def get_recent_orders(self, lookback_seconds: int) -> list[RecentOrder]:
        if (
            isinstance(lookback_seconds, bool)
            or not isinstance(lookback_seconds, int)
            or lookback_seconds < 0
        ):
            raise ValueError("lookback_seconds must be a non-negative integer")
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=lookback_seconds)
        return [o for o in self._orders if o.decided_at >= cutoff]

    def get_daily_pnl_pct(self) -> float:
        return self.daily_pnl_pct

    def submit_order(self, decision: RiskDecision) -> ExecutionResult:
        # Mirrors AlpacaRestClient's guard rails so a test written against
        # the fake catches the same misuse a real call would reject.
        if not isinstance(decision, RiskDecision):
            raise TypeError("submit_order requires a RiskDecision")
        if not decision.is_executable:
            raise ValueError("refusing to submit a non-executable RiskDecision")
        proposal = decision.proposal
        if proposal.action == Action.HOLD:
            raise ValueError("HOLD decisions do not create orders")
        if proposal.asset_class != AssetClass.US_EQUITY:
            raise ValueError("fake client mirrors TASK-01 scope: US equities only")

        self._orders.append(
            RecentOrder(symbol=proposal.symbol, action=proposal.action,
                        decided_at=datetime.now(timezone.utc))
        )
        notional = round(self.equity * decision.effective_position_size, 2)
        return FakeExecutionResult(
            order_id=f"fake-{uuid4().hex[:12]}",
            status="filled",
            filled_qty=round(notional / 100.0, 4),  # pretend $100/share, good enough for a dry run
            raw={"notional": notional, "mode": "fake"},
        )


def _typecheck() -> AlpacaClient:
    """mypy/IDE-only: fails to type-check if FakeAlpacaClient drifts from the Protocol."""
    return FakeAlpacaClient()
