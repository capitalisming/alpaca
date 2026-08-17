"""
run_vertical_slice.py

dummy_signal() -> TradingProposal -> risk_engine.evaluate() -> RiskDecision
    -> (if executable) client.submit_order() -> ExecutionResult
    -> TraceWriter.record()

Client selection is the ONLY thing that changes between a dry run and a
real paper-trading run:
  - ALPACA_API_KEY / ALPACA_SECRET_KEY unset  -> FakeAlpacaClient (no network)
  - both set + ALPACA_PAPER_TRADE=true (default) -> real AlpacaRestClient

Usage:
    python run_vertical_slice.py                 # dry run, no credentials needed
    python run_vertical_slice.py --symbol MSFT
    ALPACA_API_KEY=... ALPACA_SECRET_KEY=... python run_vertical_slice.py   # real paper order
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from adapters.fake_client import FakeAlpacaClient
from agent.reasoning import dummy_signal
from core.config import RiskConfig
from core.portfolio_state import build_risk_context
from core.risk_engine import evaluate
from core.trace import TraceWriter

TRACE_PATH = Path("logs/trace.jsonl")


def _select_client():
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if api_key and secret_key:
        from adapters.alpaca_client import AlpacaRestClient  # deferred: needs alpaca-py + real creds
        return AlpacaRestClient(api_key=api_key, secret_key=secret_key), "real (Alpaca paper)"
    return FakeAlpacaClient(), "fake (dry run, no network)"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the foundation vertical slice.")
    parser.add_argument("--symbol", default="AAPL")
    args = parser.parse_args()

    client, mode = _select_client()
    print(f"[run_vertical_slice] client mode: {mode}")

    proposal = dummy_signal(symbol=args.symbol)
    ctx = build_risk_context(client)
    decision = evaluate(proposal, ctx, RiskConfig())

    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    writer = TraceWriter.to_file(TRACE_PATH)

    execution = None
    error = None
    if decision.is_executable:
        try:
            execution = client.submit_order(decision)
        except Exception as exc:  # noqa: BLE001 — deliberately wide: must still be traced, not swallowed
            error = f"{type(exc).__name__}: {exc}"
    else:
        error = "risk engine rejected proposal — no order submitted"

    entry = writer.record(decision, execution, error)
    writer.close()

    print(f"[run_vertical_slice] verdict={decision.verdict.value} "
          f"rules={decision.rule_ids} error={error!r}")
    if execution is not None:
        print(f"[run_vertical_slice] order_id={execution.order_id} status={execution.status}")
    print(f"[run_vertical_slice] trace written to {TRACE_PATH} -> {entry['proposal_id']}")

    return 0 if error is None or "rejected" in (error or "") else 1


if __name__ == "__main__":
    sys.exit(main())
