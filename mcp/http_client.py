"""MCP HTTP client — connect to a remote MCP server over HTTP/SSE.

Uses the Streamable HTTP transport (JSON-RPC over HTTP with SSE for
server-sent messages). ``httpx`` is used for the HTTP layer.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class HttpMCPClient:
    """Client for an MCP server reachable over HTTP."""

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._url = url
        self._headers = headers or {}
        self._timeout = timeout
        self._client: httpx.Client | None = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._started = False

    # ── Lifecycle ───────────────────────────────────────────────────

    def start(self) -> None:
        """Initialize the HTTP client and perform the MCP handshake."""
        if self._started:
            return
        self._client = httpx.Client(timeout=self._timeout, headers=self._headers)
        self._started = True
        self._send_request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
        self._send_notification("notifications/initialized")
        logger.info("MCP HTTP client connected to %s", self._url)

    def stop(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._started = False
            logger.info("MCP HTTP client disconnected")

    # ── Tool discovery ──────────────────────────────────────────────

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the list of tools exposed by the server."""
        resp = self._send_request("tools/list", {})
        return resp.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a tool by name and return its result."""
        resp = self._send_request("tools/call", {"name": name, "arguments": arguments})
        result = resp.get("result", {})
        content = result.get("content", [])
        if isinstance(content, list):
            return "\n".join(
                block.get("text", "") for block in content if block.get("type") == "text"
            )
        return content

    # ── JSON-RPC over HTTP ──────────────────────────────────────────

    def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request via POST and return the parsed response."""
        if self._client is None:
            raise RuntimeError("MCP HTTP client is not started")

        with self._lock:
            self._request_id += 1
            req_id = self._request_id

        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        resp = self._client.post(self._url, json=payload)
        resp.raise_for_status()

        data = resp.json()
        if data.get("id") != req_id:
            raise RuntimeError("MCP response id mismatch")
        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")
        return data

    def _send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if self._client is None:
            return
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        try:
            self._client.post(self._url, json=payload)
        except Exception:
            logger.exception("MCP notification failed: %s", method)


def load_tools_from_http(
    url: str,
    headers: dict[str, str] | None = None,
) -> tuple[HttpMCPClient, list[dict[str, Any]]]:
    """Connect to an MCP HTTP server and return (client, tool_schemas)."""
    client = HttpMCPClient(url, headers=headers)
    client.start()
    tools = client.list_tools()
    return client, tools
