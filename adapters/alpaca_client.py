"""Paper-trading execution adapter backed by alpaca-py."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import math
import os
from typing import Any, Protocol

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, LimitOrderRequest, MarketOrderRequest

from core.risk_engine import OpenPosition, RecentOrder
from core.schemas import Action, AssetClass, OrderType, RiskDecision

logger = logging.getLogger(__name__)


class AlpacaClient(Protocol):
    """Everything the rest of the system is allowed to assume about Alpaca."""

    def get_open_positions(self) -> list[OpenPosition]: ...

    def get_recent_orders(self, lookback_seconds: int) -> list[RecentOrder]: ...

    def get_daily_pnl_pct(self) -> float: ...

    def submit_order(self, decision: RiskDecision) -> "ExecutionResult": ...
    """Must be called ONLY with an already-APPROVE/MODIFY RiskDecision.
    Must use decision.proposal.client_order_id as the idempotency key so a
    retried call can never create a duplicate order."""


class ExecutionResult(ABC):
    order_id: str
    status: str
    filled_qty: float | None
    raw: dict


@dataclass(frozen=True)
class AlpacaExecutionResult(ExecutionResult):
    """Stable execution result returned by AlpacaRestClient."""

    order_id: str
    status: str
    filled_qty: float | None
    raw: dict


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _positive_number(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Alpaca returned an invalid {field_name}") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"Alpaca returned a non-positive {field_name}")
    return number


class AlpacaRestClient(AlpacaClient):
    """Synchronous Alpaca Trading API adapter with no live-trading path."""

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        *,
        trading_client: Any | None = None,
    ) -> None:
        paper_setting = os.getenv("ALPACA_PAPER_TRADE", "true").strip().lower()
        if paper_setting != "true":
            raise ValueError("AlpacaRestClient requires ALPACA_PAPER_TRADE=true")
        if trading_client is not None:
            self._client = trading_client
            return
        resolved_api_key = api_key or os.getenv("ALPACA_API_KEY")
        resolved_secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY")
        if not resolved_api_key or not resolved_secret_key:
            raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")
        self._client = TradingClient(
            api_key=resolved_api_key,
            secret_key=resolved_secret_key,
            paper=True,
        )

    def get_open_positions(self) -> list[OpenPosition]:
        equity = _positive_number(self._client.get_account().equity, "account equity")
        positions: list[OpenPosition] = []
        for position in self._client.get_all_positions():
            try:
                market_value = abs(float(position.market_value))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Alpaca returned an invalid market value for {position.symbol}"
                ) from exc
            if not math.isfinite(market_value):
                raise ValueError(
                    f"Alpaca returned an invalid market value for {position.symbol}"
                )
            positions.append(
                OpenPosition(
                    symbol=str(position.symbol).strip().upper(),
                    exposure=market_value / equity,
                )
            )
        return positions

    def get_recent_orders(self, lookback_seconds: int) -> list[RecentOrder]:
        if (
            isinstance(lookback_seconds, bool)
            or not isinstance(lookback_seconds, int)
            or lookback_seconds < 0
        ):
            raise ValueError("lookback_seconds must be a non-negative integer")

        after = datetime.now(timezone.utc) - timedelta(seconds=lookback_seconds)
        request = GetOrdersRequest(status=QueryOrderStatus.ALL, after=after)
        recent: list[RecentOrder] = []
        for order in self._client.get_orders(filter=request):
            side = _enum_value(order.side).lower()
            if side == OrderSide.BUY.value:
                action = Action.BUY
            elif side == OrderSide.SELL.value:
                action = Action.SELL
            else:
                raise ValueError(f"Alpaca returned an unsupported order side: {side}")

            decided_at = getattr(order, "submitted_at", None) or getattr(
                order, "created_at", None
            )
            if not isinstance(decided_at, datetime):
                raise ValueError("Alpaca returned an order without a valid timestamp")
            if decided_at.tzinfo is None:
                decided_at = decided_at.replace(tzinfo=timezone.utc)
            if decided_at >= after:
                recent.append(
                    RecentOrder(
                        symbol=str(order.symbol).strip().upper(),
                        action=action,
                        decided_at=decided_at,
                    )
                )
        return recent

    def get_daily_pnl_pct(self) -> float:
        account = self._client.get_account()
        equity = _positive_number(account.equity, "account equity")
        last_equity = _positive_number(account.last_equity, "last equity")
        return (equity - last_equity) / last_equity

    def submit_order(self, decision: RiskDecision) -> ExecutionResult:
        if not isinstance(decision, RiskDecision):
            raise TypeError("submit_order requires a RiskDecision")
        if not decision.is_executable:
            raise ValueError("refusing to submit a non-executable RiskDecision")

        proposal = decision.proposal
        if proposal.action == Action.HOLD:
            raise ValueError("HOLD decisions do not create orders")
        if proposal.asset_class != AssetClass.US_EQUITY:
            raise ValueError("TASK-01 execution supports US equities only")
        if proposal.stop_loss is not None or proposal.take_profit is not None:
            raise ValueError("attached exit orders are not supported by TASK-01")

        position_size = decision.effective_position_size
        if not math.isfinite(position_size) or position_size <= 0:
            raise ValueError("effective_position_size must be positive")

        equity = _positive_number(self._client.get_account().equity, "account equity")
        notional = round(equity * position_size, 2)
        if notional <= 0:
            raise ValueError("effective_position_size produces a zero-dollar order")

        side = OrderSide.BUY if proposal.action == Action.BUY else OrderSide.SELL
        common: dict[str, Any] = {
            "symbol": proposal.symbol,
            "side": side,
            "time_in_force": TimeInForce.DAY,
            "client_order_id": proposal.client_order_id,
        }
        if proposal.order_type == OrderType.MARKET:
            order_request = MarketOrderRequest(notional=notional, **common)
        elif proposal.order_type == OrderType.LIMIT:
            if proposal.limit_price is None:
                raise ValueError("limit orders require limit_price")
            qty = round(notional / proposal.limit_price, 9)
            if qty <= 0:
                raise ValueError("effective_position_size produces a zero-quantity order")
            order_request = LimitOrderRequest(
                qty=qty,
                limit_price=proposal.limit_price,
                **common,
            )
        else:
            raise ValueError(f"unsupported order type: {proposal.order_type}")

        order = self._client.submit_order(order_data=order_request)
        raw = self._raw_order(order)
        filled_qty_value = raw.get("filled_qty", getattr(order, "filled_qty", None))
        filled_qty = float(filled_qty_value) if filled_qty_value not in (None, "") else None
        result = AlpacaExecutionResult(
            order_id=str(raw.get("id", getattr(order, "id", ""))),
            status=_enum_value(raw.get("status", getattr(order, "status", "unknown"))),
            filled_qty=filled_qty,
            raw=raw,
        )
        logger.info(
            "Alpaca paper order submitted proposal_id=%s client_order_id=%s order_id=%s status=%s",
            proposal.proposal_id,
            proposal.client_order_id,
            result.order_id,
            result.status,
        )
        return result

    @staticmethod
    def _raw_order(order: Any) -> dict:
        if isinstance(order, dict):
            return dict(order)
        if hasattr(order, "model_dump"):
            return order.model_dump(mode="json")
        return {
            "id": getattr(order, "id", ""),
            "status": _enum_value(getattr(order, "status", "unknown")),
            "filled_qty": getattr(order, "filled_qty", None),
        }
