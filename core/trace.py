"""
core/trace.py

One JSON object per completed proposal lifecycle. Deliberately flat and
grep-able rather than routed through Python's logging module — this is a
demo/audit artifact ("why did the agent do that?"), not a debug log.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from adapters.alpaca_client import ExecutionResult
from core.schemas import RiskDecision


@dataclass
class TraceWriter:
    stream: TextIO

    @classmethod
    def to_file(cls, path: str | Path) -> "TraceWriter":
        return cls(stream=open(path, "a", encoding="utf-8"))

    def record(
        self,
        decision: RiskDecision,
        execution: ExecutionResult | None,
        error: str | None = None,
    ) -> dict:
        entry = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "proposal_id": decision.proposal.proposal_id,
            "client_order_id": decision.proposal.client_order_id,
            "symbol": decision.proposal.symbol,
            "action": decision.proposal.action.value,
            "confidence": decision.proposal.confidence,
            "reason": decision.proposal.reason,
            "risk_verdict": decision.verdict.value,
            "risk_rule_ids": decision.rule_ids,
            "risk_reasons": decision.reasons,
            "requested_position_size": decision.proposal.position_size,
            "effective_position_size": decision.effective_position_size,
            "execution": (
                {
                    "order_id": execution.order_id,
                    "status": execution.status,
                    "filled_qty": execution.filled_qty,
                }
                if execution is not None
                else None
            ),
            "error": error,
        }
        self.stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.stream.flush()
        return entry

    def close(self) -> None:
        self.stream.close()
