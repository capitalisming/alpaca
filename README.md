# trading-agent - foundation (pre-Track)

Track-agnostic scaffold for the Alpaca AI Trading Agents Hackathon (lablab.ai,
28 Aug - 4 Sep 2026). Nothing here assumes a specific strategy.

## State

- `core/schemas.py` - validated `TradingProposal` / `RiskDecision`
  contract between LLM reasoning and downstream code.
- `core/risk_engine.py` - deterministic, pure, network-free risk engine
  with kill switch, freshness, allowlist, confidence, duplicate-order,
  daily-loss, position-size, and portfolio-exposure rules.
- `adapters/alpaca_client.py` - implemented paper-only `AlpacaRestClient`
  for positions, recent orders, daily PnL, and risk-gated order submission.
- `adapters/mcp_gateway.py` - read-only Alpaca MCP gateway for account,
  position, and US-equity market data. Write-capable tools are not exposed.
- Automated suite: 43 tests pass; the real paper-order smoke test is opt-in
  and skipped by the normal test run.

## Run tests

```shell
pip install -r requirements.txt
python -m pytest -q
```

## Manual Alpaca Paper Trading verification

Configure `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, and
`ALPACA_PAPER_TRADE=true` outside the repository. Then explicitly enable
the non-CI smoke test:

```powershell
$env:RUN_ALPACA_PAPER_INTEGRATION = "1"
python -m pytest -q tests/test_alpaca_paper_integration.py
```

Never commit credentials or place them in tracked configuration files.

## DEC-01 (superseded numbering note)

MCP/CLI vs direct SDK: read-only market/account data may go through the
Alpaca MCP tool surface directly (agent-facing, matching the hackathon's MCP
focus). All writes (order placement) go through
`adapters.alpaca_client.AlpacaClient.submit_order`, which accepts only an
already-evaluated `RiskDecision` - never a raw `TradingProposal` and never
a raw LLM tool call.

Alpaca's MCP/CLI surface has no built-in confirmation step before execution.
The deterministic Risk Engine is this project's confirmation boundary, so
nothing may bypass it. Revisit only if an approved architecture decision
explicitly replaces DEC-01.

## COMPLETED_TASK: TASK-01

`AlpacaRestClient` and `AlpacaMcpGateway` are implemented and covered by
unit tests.

- Account, position, and order reads use `alpaca-py` REST.
- `submit_order` accepts `RiskDecision` only and refuses rejected or
  otherwise non-executable decisions.
- Alpaca's `client_order_id` receives
  `decision.proposal.client_order_id` for idempotency.
- Execution has no live-trading code path and rejects
  `ALPACA_PAPER_TRADE` values other than `true`.
- The LLM-facing MCP tool list is a fixed read-only allowlist.
- `alpaca-py` is pinned exactly in `requirements.txt`.
- Options, crypto-specific execution, strategy logic, and dashboard work
  remain out of scope.

## Vertical slice

Run the complete credential-free flow with the in-memory Alpaca client:

```shell
python run_vertical_slice.py --symbol AAPL
```

The runner creates a deterministic placeholder `TradingProposal`, evaluates
it through the Risk Engine, submits only an executable `RiskDecision`, and
appends the outcome to the gitignored `logs/trace.jsonl` audit trace. When
both Alpaca credentials are available, the same flow selects the existing
paper-only REST adapter; live trading remains unavailable.

## COMPLETED_TASK: TASK-03

The vertical slice, fake client, portfolio-state boundary, and lifecycle trace
are implemented with regression coverage. Real Alpaca execution remains
guarded by `ALPACA_PAPER_TRADE=true` and the opt-in integration test.
