from datetime import datetime, timedelta, timezone

from core.config import RiskConfig
from core.risk_engine import OpenPosition, RecentOrder, RiskContext, evaluate
from core.schemas import Action, RiskVerdict, TradingProposal

NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)


def proposal(**overrides) -> TradingProposal:
    data = dict(
        action=Action.BUY,
        symbol="AAPL",
        confidence=0.8,
        reason="test",
        position_size=0.05,
        timestamp=NOW,
    )
    data.update(overrides)
    return TradingProposal(**data)


def ctx(**overrides) -> RiskContext:
    data = dict(now=NOW)
    data.update(overrides)
    return RiskContext(**data)


def test_clean_proposal_is_approved():
    d = evaluate(proposal(), ctx(), RiskConfig())
    assert d.verdict == RiskVerdict.APPROVE
    assert d.is_executable
    assert d.effective_position_size == 0.05


def test_kill_switch_rejects_everything():
    d = evaluate(proposal(), ctx(), RiskConfig(kill_switch=True))
    assert d.verdict == RiskVerdict.REJECT
    assert "RISK-KILL-SWITCH" in d.rule_ids
    assert not d.is_executable


def test_stale_data_is_rejected():
    old = proposal(timestamp=NOW - timedelta(seconds=120))
    d = evaluate(old, ctx(), RiskConfig(max_data_age_seconds=60))
    assert d.verdict == RiskVerdict.REJECT
    assert "RISK-STALE-DATA" in d.rule_ids


def test_allowlist_blocks_unknown_symbol():
    cfg = RiskConfig(symbol_allowlist=frozenset({"AAPL", "MSFT"}))
    d = evaluate(proposal(symbol="TSLA"), ctx(), cfg)
    assert d.verdict == RiskVerdict.REJECT
    assert "RISK-ALLOWLIST" in d.rule_ids


def test_low_confidence_is_rejected():
    cfg = RiskConfig(min_confidence=0.9)
    d = evaluate(proposal(confidence=0.6), ctx(), cfg)
    assert d.verdict == RiskVerdict.REJECT
    assert "RISK-CONFIDENCE" in d.rule_ids


def test_hold_bypasses_confidence_and_size_rules():
    cfg = RiskConfig(min_confidence=0.99)
    p = proposal(action=Action.HOLD, position_size=0.0, confidence=0.1)
    d = evaluate(p, ctx(), cfg)
    assert d.verdict == RiskVerdict.APPROVE


def test_duplicate_order_within_cooldown_is_rejected():
    recent = [RecentOrder(symbol="AAPL", action=Action.BUY, decided_at=NOW - timedelta(seconds=5))]
    d = evaluate(proposal(), ctx(recent_orders=recent), RiskConfig(duplicate_cooldown_seconds=30))
    assert d.verdict == RiskVerdict.REJECT
    assert "RISK-DUPLICATE" in d.rule_ids


def test_duplicate_order_after_cooldown_is_allowed():
    recent = [RecentOrder(symbol="AAPL", action=Action.BUY, decided_at=NOW - timedelta(seconds=60))]
    d = evaluate(proposal(), ctx(recent_orders=recent), RiskConfig(duplicate_cooldown_seconds=30))
    assert d.verdict == RiskVerdict.APPROVE


def test_daily_loss_limit_blocks_new_buys():
    cfg = RiskConfig(daily_loss_limit_pct=0.03)
    d = evaluate(proposal(action=Action.BUY), ctx(daily_pnl_pct=-0.04), cfg)
    assert d.verdict == RiskVerdict.REJECT
    assert "RISK-DAILY-LOSS" in d.rule_ids


def test_daily_loss_limit_does_not_block_sells():
    cfg = RiskConfig(daily_loss_limit_pct=0.03)
    d = evaluate(proposal(action=Action.SELL, position_size=0.05), ctx(daily_pnl_pct=-0.10), cfg)
    assert d.verdict != RiskVerdict.REJECT or "RISK-DAILY-LOSS" not in d.rule_ids


def test_position_size_is_clamped_not_rejected():
    cfg = RiskConfig(max_position_size=0.02)
    d = evaluate(proposal(position_size=0.10), ctx(), cfg)
    assert d.verdict == RiskVerdict.MODIFY
    assert d.effective_position_size == 0.02
    assert "RISK-MAX-POSITION" in d.rule_ids


def test_portfolio_exposure_clamps_to_remaining_room():
    cfg = RiskConfig(max_portfolio_exposure=0.30, max_position_size=1.0)
    existing = [OpenPosition(symbol="MSFT", exposure=0.27)]
    d = evaluate(proposal(position_size=0.10), ctx(open_positions=existing), cfg)
    assert d.verdict == RiskVerdict.MODIFY
    assert round(d.effective_position_size, 4) == 0.03


def test_portfolio_exposure_rejects_when_no_room_left():
    cfg = RiskConfig(max_portfolio_exposure=0.30, max_position_size=1.0)
    existing = [OpenPosition(symbol="MSFT", exposure=0.30)]
    d = evaluate(proposal(position_size=0.05), ctx(open_positions=existing), cfg)
    assert d.verdict == RiskVerdict.REJECT
    assert "RISK-MAX-EXPOSURE" in d.rule_ids


def test_sell_is_not_gated_by_exposure_rule():
    cfg = RiskConfig(max_portfolio_exposure=0.10, max_position_size=1.0)
    existing = [OpenPosition(symbol="AAPL", exposure=0.10)]
    d = evaluate(proposal(action=Action.SELL, position_size=0.10), ctx(open_positions=existing), cfg)
    assert d.verdict == RiskVerdict.APPROVE
