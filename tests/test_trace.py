import json

from adapters.fake_client import FakeAlpacaClient
from core.schemas import Action, RiskDecision, RiskVerdict, TradingProposal
from core.trace import TraceWriter


def _decision(verdict=RiskVerdict.APPROVE) -> RiskDecision:
    p = TradingProposal(action=Action.BUY, symbol="AAPL", confidence=0.7,
                         reason="t", position_size=0.02)
    return RiskDecision(proposal=p, verdict=verdict, rule_ids=["RISK-OK"], reasons=[])


def test_trace_writer_writes_one_json_line(tmp_path):
    path = tmp_path / "trace.jsonl"
    w = TraceWriter.to_file(path)
    decision = _decision()
    execution = FakeAlpacaClient().submit_order(decision)
    w.record(decision, execution)
    w.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["symbol"] == "AAPL"
    assert entry["risk_verdict"] == "APPROVE"
    assert entry["execution"]["status"] == "filled"


def test_trace_writer_records_rejection_without_execution(tmp_path):
    path = tmp_path / "trace.jsonl"
    w = TraceWriter.to_file(path)
    decision = _decision(verdict=RiskVerdict.REJECT)
    w.record(decision, execution=None, error="risk engine rejected proposal — no order submitted")
    w.close()

    entry = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["execution"] is None
    assert "rejected" in entry["error"]


def test_trace_writer_appends_across_multiple_records(tmp_path):
    path = tmp_path / "trace.jsonl"
    w = TraceWriter.to_file(path)
    w.record(_decision(), execution=None, error="x")
    w.close()
    w2 = TraceWriter.to_file(path)
    w2.record(_decision(), execution=None, error="y")
    w2.close()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
