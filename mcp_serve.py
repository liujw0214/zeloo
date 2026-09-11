"""MCP Server — expose Zeloo tools via the Model Context Protocol.

This module implements a minimal MCP (Model Context Protocol) server
that exposes all registered Zeloo tools to external MCP clients (e.g.,
Claude Desktop, Cursor, other AI agents).

Supports the stdio transport (JSON-RPC over stdin/stdout).

Run as a standalone process::

    python -m mcp_serve

Or embed in another process::

    from mcp_serve import MCPServer
    server = MCPServer()
    server.run_stdio()
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"


class MCPServer:
    """A minimal MCP server exposing Zeloo tools.

    Handles the MCP JSON-RPC protocol over stdio. Supports:
    - initialize / notifications/initialized
    - tools/list
    - tools/call
    - ping
    """

    def __init__(self, toolset_filter: set[str] | None = None) -> None:
        self._toolset_filter = toolset_filter
        self._initialized = False

    # ------------------------------------------------------------------
    # Tool discovery
    # ------------------------------------------------------------------
    def _get_tools(self) -> dict[str, Any]:
        """Return filtered tools from the global registry."""
        from tools.base import get_registry

        registry = get_registry()
        tools = registry.get_all()
        if self._toolset_filter:
            tools = {
                name: t
                for name, t in tools.items()
                if t.toolset in self._toolset_filter
            }
        return tools

    def _list_tools(self) -> list[dict[str, Any]]:
        """Return MCP tool descriptors."""
        result = []
        for name, tool in self._get_tools().items():
            result.append(
                {
                    "name": name,
                    "description": tool.description,
                    "inputSchema": tool.parameters,
                }
            )
        return result

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------
    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Handle a single JSON-RPC request. Returns the response or None."""
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        # Notifications have no id
        is_notification = "id" not in request

        if method == "initialize":
            return self._handle_initialize(req_id, params)
        if method == "notifications/initialized":
            self._initialized = True
            return None
        if method == "ping":
            return self._result(req_id, {})
        if method == "tools/list":
            return self._result(req_id, {"tools": self._list_tools()})
        if method == "tools/call":
            return self._handle_tool_call(req_id, params)

        if is_notification:
            return None
        return self._error(req_id, -32601, f"Method not found: {method}")

    def _handle_initialize(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the initialize handshake."""
        capabilities = {
            "tools": {"listChanged": False},
        }
        server_info = {"name": "Zeloo", "version": "0.1.0"}
        return self._result(
            req_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": capabilities,
                "serverInfo": server_info,
            },
        )

    def _handle_tool_call(
        self, req_id: Any, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle a tools/call request."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        tool = self._get_tools().get(tool_name)
        if tool is None:
            return self._error(req_id, -32602, f"Unknown tool: {tool_name}")

        try:
            result = tool.execute(**arguments)
            # MCP expects content as a list of content blocks
            content_text = result if isinstance(result, str) else json.dumps(
                result, ensure_ascii=False, default=str
            )
            return self._result(
                req_id,
                {
                    "content": [{"type": "text", "text": content_text}],
                    "isError": False,
                },
            )
        except Exception as e:
            logger.exception("Tool %s failed", tool_name)
            return self._result(
                req_id,
                {
                    "content": [
                        {"type": "text", "text": f"Error: {e}"}
                    ],
                    "isError": True,
                },
            )

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _result(req_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    @staticmethod
    def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }

    # ------------------------------------------------------------------
    # Stdio transport
    # ------------------------------------------------------------------
    def run_stdio(self) -> None:
        """Run the MCP server reading JSON-RPC messages from stdin."""
        logger.info("Zeloo MCP server starting (stdio transport)")

        # Discover tools first
        from tools.base import discover_builtin_tools

        discover_builtin_tools()
        logger.info("Discovered %d tools", len(self._get_tools()))

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON: %s", line[:100])
                continue

            response = self.handle_request(request)
            if response is not None:
                print(json.dumps(response), flush=True)


def main() -> None:
    """Entry point for ``python -m mcp_serve``."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    server = MCPServer()
    server.run_stdio()


if __name__ == "__main__":
    main()
