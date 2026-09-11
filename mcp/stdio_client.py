"""MCP stdio client — spawn a local MCP server as a subprocess.

Implements the JSON-RPC 2.0 protocol over the child process's stdin/stdout
without requiring the ``mcp`` SDK. Each client manages a single server
process and exposes its tools as callables.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class StdioMCPClient:
    """Client for an MCP server running as a local subprocess."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._command = command
        self._args = args or []
        self._env = env
        self._timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._started = False

    # ── Lifecycle ───────────────────────────────────────────────────

    def start(self) -> None:
        """Spawn the MCP server subprocess and initialize the session."""
        if self._started:
            return

        self._proc = subprocess.Popen(
            [self._command, *self._args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env,
            text=True,
            bufsize=1,
        )
        self._started = True
        logger.info("MCP stdio server started: %s %s", self._command, " ".join(self._args))

        # MCP initialize handshake
        self._send_request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
        self._send_notification("notifications/initialized")

    def stop(self) -> None:
        """Terminate the MCP server subprocess."""
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            except Exception:
                logger.exception("Failed to stop MCP server")
            self._proc = None
            self._started = False
            logger.info("MCP stdio server stopped")

    # ── Tool discovery ──────────────────────────────────────────────

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the list of tools exposed by the server."""
        resp = self._send_request("tools/list", {})
        return resp.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a tool by name and return its result."""
        resp = self._send_request("tools/call", {"name": name, "arguments": arguments})
        result = resp.get("result", {})
        # MCP returns content blocks; extract text
        content = result.get("content", [])
        if isinstance(content, list):
            return "\n".join(
                block.get("text", "") for block in content if block.get("type") == "text"
            )
        return content

    # ── JSON-RPC transport ──────────────────────────────────────────

    def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for the response."""
        with self._lock:
            self._request_id += 1
            req_id = self._request_id

        message = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        self._write(message)

        return self._read_response(req_id)

    def _send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        message = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}})
        self._write(message)

    def _write(self, message: str) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("MCP server is not running")
        self._proc.stdin.write(message + "\n")
        self._proc.stdin.flush()

    def _read_response(self, req_id: int) -> dict[str, Any]:
        """Read lines from stdout until a response matching req_id arrives."""
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("MCP server is not running")

        deadline = time.time() + self._timeout
        while time.time() < deadline:
            line = self._proc.stdout.readline()
            if not line:
                # Process may have exited
                if self._proc.poll() is not None:
                    stderr = self._proc.stderr.read() if self._proc.stderr else ""
                    raise RuntimeError(f"MCP server exited unexpectedly: {stderr}")
                continue
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                # Some servers send non-JSON log lines; skip
                continue
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise RuntimeError(f"MCP error: {msg['error']}")
                return msg
        raise TimeoutError(f"MCP response timeout for request {req_id}")


def load_tools_from_stdio(
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> tuple[StdioMCPClient, list[dict[str, Any]]]:
    """Start an MCP stdio server and return (client, tool_schemas).

    Each tool schema is a dict with ``name``, ``description``, and
    ``inputSchema`` (JSON Schema for arguments).
    """
    client = StdioMCPClient(command, args=args, env=env)
    client.start()
    tools = client.list_tools()
    return client, tools
