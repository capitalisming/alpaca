import asyncio
from types import SimpleNamespace

import pytest

from adapters.mcp_gateway import AlpacaMcpGateway, READ_ONLY_TOOL_NAMES


class FakeMcpSession:
    def __init__(self):
        self.tools = [
            SimpleNamespace(name="get_account_info"),
            SimpleNamespace(name="get_all_positions"),
            SimpleNamespace(name="get_stock_latest_quote"),
            SimpleNamespace(name="place_stock_order"),
            SimpleNamespace(name="cancel_all_orders"),
            SimpleNamespace(name="close_position"),
            SimpleNamespace(name="update_account_config"),
        ]
        self.calls = []

    async def list_tools(self):
        return SimpleNamespace(tools=self.tools)

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        return {"tool": name, "arguments": arguments}


def test_list_tools_exposes_only_fixed_read_only_allowlist():
    session = FakeMcpSession()
    gateway = AlpacaMcpGateway(session)

    exposed = asyncio.run(gateway.list_tools())
    exposed_names = {tool.name for tool in exposed}

    assert exposed_names == {
        "get_account_info",
        "get_all_positions",
        "get_stock_latest_quote",
    }
    assert exposed_names <= READ_ONLY_TOOL_NAMES
    assert not exposed_names & {
        "place_stock_order",
        "cancel_all_orders",
        "close_position",
        "update_account_config",
    }


def test_read_only_call_is_forwarded():
    session = FakeMcpSession()
    gateway = AlpacaMcpGateway(session)

    result = asyncio.run(gateway.call_tool("get_stock_latest_quote", {"symbol": "AAPL"}))

    assert result == {
        "tool": "get_stock_latest_quote",
        "arguments": {"symbol": "AAPL"},
    }
    assert session.calls == [("get_stock_latest_quote", {"symbol": "AAPL"})]


@pytest.mark.parametrize(
    "tool_name",
    ["place_stock_order", "cancel_all_orders", "close_position", "unknown_tool"],
)
def test_write_or_unknown_call_is_blocked_before_session(tool_name):
    session = FakeMcpSession()
    gateway = AlpacaMcpGateway(session)

    with pytest.raises(PermissionError, match="not approved"):
        asyncio.run(gateway.call_tool(tool_name, {}))

    assert session.calls == []


def test_gateway_rejects_live_mode(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_TRADE", "false")
    with pytest.raises(ValueError, match="ALPACA_PAPER_TRADE=true"):
        AlpacaMcpGateway(FakeMcpSession())


def test_gateway_rejects_non_mapping_arguments():
    gateway = AlpacaMcpGateway(FakeMcpSession())
    with pytest.raises(TypeError, match="mapping"):
        asyncio.run(gateway.call_tool("get_account_info", ["not", "a", "mapping"]))
