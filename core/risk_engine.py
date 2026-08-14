"""
core/risk_engine.py

Deterministic Risk Engine. Every rule here is a pure function of
(TradingProposal, RiskContext, RiskConfig) -> partial verdict.

No rule ever calls the network, reads a clock beyond what's passed in, or
mutates external state. This is what makes it unit-testable without mocks
and auditable in a demo ("why did the agent's order get rejected/clamped?").

Rule evaluation order matters: kill switch and stale data short-circuit
everything else. Otherwise rules accumulate; REJECT wins over MODIFY wins
over APPROVE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.config import RiskConfig
from core.schemas import Action, RiskDecision, RiskVerdict, TradingProposal


@dataclass
class OpenPosition:
    symbol: str
    exposure: float  # fraction of portfolio equity currently allocated


@dataclass
class RecentOrder:
    symbol: str
    action: Action
    decided_at: datetime


@dataclass
class RiskContext:
    """Snapshot the risk engine needs to make a decision. Built by
    portfolio_state.py from live Alpaca account data (or by tests, by hand)."""

    now: datetime
    open_positions: list[OpenPosition] = field(default_factory=list)
    recent_orders: list[RecentOrder] = field(default_factory=list)
    daily_pnl_pct: float = 0.0  # negative == loss, as fraction of equity

    def current_exposure(self) -> float:
        return sum(p.exposure for p in self.open_positions)

    def exposure_for(self, symbol: str) -> float:
        return sum(p.exposure for p in self.open_positions if p.symbol == symbol)


RuleResult = tuple[RiskVerdict, list[str], list[str], float | None]
# (verdict, rule_ids, reasons, adjusted_position_size)


def _rule_kill_switch(p: TradingProposal, ctx: RiskContext, cfg: RiskConfig) -> RuleResult | None:
    if cfg.kill_switch:
        return RiskVerdict.REJECT, ["RISK-KILL-SWITCH"], ["Kill switch is active"], None
    return None


def _rule_stale_data(p: TradingProposal, ctx: RiskContext, cfg: RiskConfig) -> RuleResult | None:
    age = (ctx.now - p.timestamp).total_seconds()
    if age > cfg.max_data_age_seconds:
        return (
            RiskVerdict.REJECT,
            ["RISK-STALE-DATA"],
            [f"Proposal is {age:.0f}s old, max allowed is {cfg.max_data_age_seconds}s"],
            None,
        )
    return None


def _rule_allowlist(p: TradingProposal, ctx: RiskContext, cfg: RiskConfig) -> RuleResult | None:
    if cfg.symbol_allowlist is not None and p.symbol not in cfg.symbol_allowlist:
        return (
            RiskVerdict.REJECT,
            ["RISK-ALLOWLIST"],
            [f"{p.symbol} is not in the configured allowlist"],
            None,
        )
    return None


def _rule_confidence(p: TradingProposal, ctx: RiskContext, cfg: RiskConfig) -> RuleResult | None:
    if p.action != Action.HOLD and p.confidence < cfg.min_confidence:
        return (
            RiskVerdict.REJECT,
            ["RISK-CONFIDENCE"],
            [f"confidence {p.confidence:.2f} < min {cfg.min_confidence:.2f}"],
            None,
        )
    return None


def _rule_duplicate(p: TradingProposal, ctx: RiskContext, cfg: RiskConfig) -> RuleResult | None:
    for o in ctx.recent_orders:
        if o.symbol == p.symbol and o.action == p.action:
            gap = (ctx.now - o.decided_at).total_seconds()
            if gap < cfg.duplicate_cooldown_seconds:
                return (
                    RiskVerdict.REJECT,
                    ["RISK-DUPLICATE"],
                    [f"Same {p.action} on {p.symbol} decided {gap:.0f}s ago "
                     f"(cooldown {cfg.duplicate_cooldown_seconds}s)"],
                    None,
                )
    return None


def _rule_daily_loss_limit(p: TradingProposal, ctx: RiskContext, cfg: RiskConfig) -> RuleResult | None:
    if p.action == Action.BUY and ctx.daily_pnl_pct <= -cfg.daily_loss_limit_pct:
        return (
            RiskVerdict.REJECT,
            ["RISK-DAILY-LOSS"],
            [f"Daily PnL {ctx.daily_pnl_pct:.2%} breached -{cfg.daily_loss_limit_pct:.2%} limit"],
            None,
        )
    return None


def _rule_position_size(p: TradingProposal, ctx: RiskContext, cfg: RiskConfig) -> RuleResult | None:
    if p.position_size > cfg.max_position_size:
        return (
            RiskVerdict.MODIFY,
            ["RISK-MAX-POSITION"],
            [f"position_size {p.position_size:.3f} clamped to {cfg.max_position_size:.3f}"],
            cfg.max_position_size,
        )
    return None


def _rule_portfolio_exposure(p: TradingProposal, ctx: RiskContext, cfg: RiskConfig) -> RuleResult | None:
    if p.action != Action.BUY:
        return None
    _EPS = 1e-9
    projected = ctx.current_exposure() + p.position_size
    if projected > cfg.max_portfolio_exposure + _EPS:
        room = max(0.0, cfg.max_portfolio_exposure - ctx.current_exposure())
        if room <= _EPS:
            return (
                RiskVerdict.REJECT,
                ["RISK-MAX-EXPOSURE"],
                [f"Portfolio exposure already at {ctx.current_exposure():.3f}, "
                 f"limit {cfg.max_portfolio_exposure:.3f}"],
                None,
            )
        return (
            RiskVerdict.MODIFY,
            ["RISK-MAX-EXPOSURE"],
            [f"position_size clamped from {p.position_size:.3f} to {room:.3f} "
             f"to respect portfolio exposure limit"],
            room,
        )
    return None


# Order matters: hard-stop rules first, then clamping rules.
_REJECT_ONLY_RULES = (
    _rule_kill_switch,
    _rule_stale_data,
    _rule_allowlist,
    _rule_confidence,
    _rule_duplicate,
    _rule_daily_loss_limit,
)
_CLAMPING_RULES = (
    _rule_position_size,
    _rule_portfolio_exposure,
)


def evaluate(proposal: TradingProposal, ctx: RiskContext, cfg: RiskConfig) -> RiskDecision:
    """Entry point. Never raises on a bad proposal — that's what REJECT is for."""

    for rule in _REJECT_ONLY_RULES:
        result = rule(proposal, ctx, cfg)
        if result is not None:
            verdict, rule_ids, reasons, _ = result
            return RiskDecision(
                proposal=proposal, verdict=verdict,
                rule_ids=rule_ids, reasons=reasons,
            )

    if proposal.action == Action.HOLD:
        return RiskDecision(
            proposal=proposal, verdict=RiskVerdict.APPROVE,
            rule_ids=["RISK-HOLD-NOOP"], reasons=["HOLD requires no risk gating"],
        )

    fired_ids: list[str] = []
    fired_reasons: list[str] = []
    smallest_size = proposal.position_size

    for rule in _CLAMPING_RULES:
        result = rule(proposal, ctx, cfg)
        if result is not None:
            verdict, rule_ids, reasons, adjusted = result
            fired_ids.extend(rule_ids)
            fired_reasons.extend(reasons)
            if verdict == RiskVerdict.REJECT:
                return RiskDecision(
                    proposal=proposal, verdict=RiskVerdict.REJECT,
                    rule_ids=fired_ids, reasons=fired_reasons,
                )
            if adjusted is not None:
                smallest_size = min(smallest_size, adjusted)
            if smallest_size <= 0.0:
                return RiskDecision(
                    proposal=proposal, verdict=RiskVerdict.REJECT,
                    rule_ids=fired_ids, reasons=fired_reasons + ["Clamped size reached 0"],
                )

    if fired_ids:
        return RiskDecision(
            proposal=proposal, verdict=RiskVerdict.MODIFY,
            adjusted_position_size=smallest_size,
            rule_ids=fired_ids, reasons=fired_reasons,
        )

    return RiskDecision(
        proposal=proposal, verdict=RiskVerdict.APPROVE,
        rule_ids=["RISK-OK"], reasons=["All checks passed"],
    )
