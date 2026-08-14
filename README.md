# trading-agent — foundation (pre-Track)

Track-agnostic scaffold for the Alpaca AI Trading Agents Hackathon (lablab.ai,
28 Aug – 4 Sep 2026). Nothing here assumes a specific asset class or strategy.

## State

- `core/schemas.py` — `TradingProposal` / `RiskDecision`, the only contract
  allowed between LLM reasoning and everything downstream.
- `core/risk_engine.py` — deterministic, pure, network-free. 8 rules:
  kill switch, stale data, allowlist, min confidence, duplicate-order
  cooldown, daily loss limit, max position size (clamp), max portfolio
  exposure (clamp). 20/20 tests passing.
- `adapters/alpaca_client.py` — interface only. Real implementation needs
  live paper credentials this environment doesn't have — see TASK-01 below.

## Run tests

```
pip install -r requirements.txt
pytest -q
```

## DEC-01 (superseded numbering note)

MCP/CLI vs direct SDK: read-only market/account data may go through the
Alpaca MCP tool surface directly (agent-facing, matches the hackathon's own
stated MCP focus). All writes (order placement) go through
`adapters.alpaca_client.AlpacaClient.submit_order`, which only accepts an
already-evaluated `RiskDecision` — never a raw `TradingProposal`, never a
raw LLM tool-call. Rationale: Alpaca's own MCP/CLI docs state there is no
built-in confirmation step before execution; the deterministic Risk Engine
is the only confirmation step this project has, so nothing may bypass it.
Revisit if official Tracks require raw agent-to-MCP execution as a judging
requirement (unlikely per current judging categories: Application of
Technology / Presentation / Business Value / Originality — none reward
removing the safety layer).

## APPROVED_TASK: TASK-01

```
Objective: Implement AlpacaRestClient(AlpacaClient) against paper trading.
Context: adapters/alpaca_client.py defines the Protocol; core/ is done and tested.
Files/components: adapters/alpaca_client.py (add concrete class), adapters/mcp_gateway.py (new)
Required behavior:
  - get_open_positions / get_recent_orders / get_daily_pnl_pct read from
    live Alpaca paper account via alpaca-py REST.
  - submit_order accepts RiskDecision only; raises TypeError on anything
    else; uses proposal.client_order_id as Alpaca's client_order_id param
    for idempotency; refuses to call if decision.is_executable is False.
  - mcp_gateway.py: read-only passthrough for market data / account /
    positions via alpaca-mcp-server tools. No write-capable tool exposed
    to the LLM's tool list.
Interfaces: must satisfy the existing AlpacaClient Protocol unchanged.
Constraints: paper trading only (ALPACA_PAPER_TRADE=true), no live-trading
  code path, pin alpaca-py exact version in requirements.txt (both MCP
  server and CLI are pre-1.0/Alpha — do not float versions).
Acceptance criteria: vertical slice runs end-to-end — dummy signal ->
  TradingProposal -> risk_engine.evaluate -> submit_order -> real paper
  order visible in Alpaca dashboard -> trace logged.
Tests required: unit tests with a fake HTTP layer for the REST client;
  one manual/integration run against real paper account (not CI).
Out of scope: options/crypto-specific handling, strategy logic, dashboard.
```
