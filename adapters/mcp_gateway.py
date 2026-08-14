"""Read-only gateway for the official Alpaca MCP server tool surface."""

from __future__ import annotations

from collections.abc import Mapping
import os
from typing import Any, Protocol


# Fixed allowlisting is deliberate: alpaca-mcp-server's broad toolsets mix
# reads and writes, so server-side toolset filtering alone is insufficient.
READ_ONLY_TOOL_NAMES = frozenset(
    {
        # Account
        "get_account_info",
        "get_account_config",
        "get_portfolio_history",
        "get_account_activities",
        "get_account_activities_by_type",
        # Positions
        "get_all_positions",
        "get_open_position",
        # US equity market data
        "get_stock_bars",
        "get_stock_quotes",
        "get_stock_trades",
        "get_stock_latest_bar",
        "get_stock_latest_quote",
        "get_stock_latest_trade",
        "get_stock_snapshot",
        "get_most_active_stocks",
        "get_market_movers",
    }
)


class McpSession(Protocol):
    """Minimal async surface supplied by an MCP client session."""

    async def list_tools(self) -> Any: ...

    async def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None = None
    ) -> Any: ...


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, Mapping):
        name = tool.get("name")
    else:
        name = getattr(tool, "name", None)
    return name if isinstance(name, str) else None


class AlpacaMcpGateway:
    """Expose only approved read operations from an Alpaca MCP session.

    The wrapped session remains responsible for transport and authentication.
    Callers must give the LLM only the output of :meth:`list_tools` and route
    tool calls back through :meth:`call_tool`.
    """

    def __init__(self, session: McpSession) -> None:
        paper_setting = os.getenv("ALPACA_PAPER_TRADE", "true").strip().lower()
        if paper_setting != "true":
            raise ValueError("AlpacaMcpGateway requires ALPACA_PAPER_TRADE=true")
        self._session = session

    async def list_tools(self) -> list[Any]:
        response = await self._session.list_tools()
        tools = getattr(response, "tools", response)
        if isinstance(tools, (str, bytes)) or not hasattr(tools, "__iter__"):
            raise TypeError("MCP list_tools returned an invalid tool collection")
        return [tool for tool in tools if _tool_name(tool) in READ_ONLY_TOOL_NAMES]

    async def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None = None
    ) -> Any:
        if name not in READ_ONLY_TOOL_NAMES:
            raise PermissionError(f"MCP tool is not approved for read-only use: {name}")
        if arguments is not None and not isinstance(arguments, Mapping):
            raise TypeError("MCP tool arguments must be a mapping")
        return await self._session.call_tool(name, dict(arguments or {}))
