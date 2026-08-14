"""
core/schemas.py

The contract between LLM reasoning and everything downstream.
No free-text ever crosses this boundary — only validated instances of these models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class AssetClass(str, Enum):
    US_EQUITY = "us_equity"
    CRYPTO = "crypto"
    OPTION = "option"


class TradingProposal(BaseModel):
    """
    What the reasoning agent is allowed to emit.
    Deliberately narrow: no free-form fields, no nested arbitrary payload.
    """

    proposal_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    action: Action
    symbol: str
    asset_class: AssetClass = AssetClass.US_EQUITY

    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=500)

    # Fraction of portfolio equity to risk on this trade, NOT a share count.
    # Keeps the schema account-size-agnostic; execution layer converts to qty/notional.
    position_size: float = Field(ge=0.0, le=1.0)

    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = Field(default=None, gt=0)

    stop_loss: Optional[float] = Field(default=None, gt=0)
    take_profit: Optional[float] = Field(default=None, gt=0)

    # Idempotency key the execution layer must honor. Generated here so the
    # same proposal, retried, never becomes two orders.
    client_order_id: str = Field(default_factory=lambda: f"prop-{uuid4().hex[:16]}")

    @field_validator("symbol")
    @classmethod
    def symbol_upper(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("symbol must not be empty")
        return v

    @model_validator(mode="after")
    def limit_requires_price(self) -> "TradingProposal":
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price is required when order_type == limit")
        if self.action == Action.HOLD and self.position_size != 0.0:
            raise ValueError("HOLD proposals must carry position_size == 0.0")
        return self


class RiskVerdict(str, Enum):
    APPROVE = "APPROVE"
    MODIFY = "MODIFY"   # approved, but position_size (or similar) was clamped
    REJECT = "REJECT"


class RiskDecision(BaseModel):
    """Output of the deterministic Risk Engine. This is what the execution
    layer is actually allowed to act on — never the raw TradingProposal."""

    proposal: TradingProposal
    verdict: RiskVerdict
    adjusted_position_size: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    rule_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_executable(self) -> bool:
        return self.verdict in (RiskVerdict.APPROVE, RiskVerdict.MODIFY)

    @property
    def effective_position_size(self) -> float:
        if self.verdict == RiskVerdict.REJECT:
            return 0.0
        if self.verdict == RiskVerdict.MODIFY and self.adjusted_position_size is not None:
            return self.adjusted_position_size
        return self.proposal.position_size
