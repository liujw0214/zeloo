"""MCP server manager — start configured servers and register their tools.

Reads MCP server definitions from config.yaml (``mcp.servers``) or the
``zeloo_MCP_SERVERS`` env var, launches each server (stdio or HTTP),
and registers every exposed tool into the global tool registry so the
agent can call it like any built-in tool.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.tool_filter import filter_tools_from_config
from tools.base import Tool, get_registry

logger = logging.getLogger(__name__)


class MCPServerManager:
    """Lifecycle manager for a set of MCP servers and their tools."""

    def __init__(self) -> None:
        self._clients: list[Any] = []
        self._registered_names: list[str] = []

    def load_and_register(self, config: dict[str, Any] | None = None) -> int:
        """Start configured MCP servers and register their tools.

        Args:
            config: The loaded config.yaml dict. Reads ``mcp.servers``.
                    If None, falls back to the ``zeloo_MCP_SERVERS`` env var
                    (comma-separated ``name=transport://target`` entries).

        Returns:
            The number of MCP tools registered.
        """
        servers = self._parse_servers(config)
        if not servers:
            return 0

        total = 0
        for server in servers:
            try:
                total += self._register_server(server)
            except Exception:
                logger.exception("Failed to start MCP server: %s", server.get("name"))
        return total

    def shutdown(self) -> None:
        """Stop all MCP servers and unregister their tools."""
        registry = get_registry()
        for name in self._registered_names:
            registry._tools.pop(name, None)  # noqa: SLF001
        self._registered_names.clear()

        for client in self._clients:
            try:
                client.stop()
            except Exception:
                logger.exception("Failed to stop MCP client")
        self._clients.clear()

    def reload(self, config: dict[str, Any] | None = None) -> int:
        """Hot-reload MCP servers: stop existing ones, then re-register.

        This allows adding/removing/updating MCP servers at runtime without
        restarting the agent process.

        Args:
            config: The (possibly updated) config dict. If None, re-reads
                    from the env var fallback.

        Returns:
            The number of MCP tools registered after reload.
        """
        logger.info("Hot-reloading MCP servers...")
        self.shutdown()
        count = self.load_and_register(config)
        logger.info("MCP reload complete: %d tool(s) registered", count)
        return count

    # ── Internal ────────────────────────────────────────────────────

    @staticmethod
    def _parse_servers(config: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Extract MCP server definitions from config or env var."""
        servers: list[dict[str, Any]] = []

        if config:
            mcp_cfg = config.get("mcp", {}) if isinstance(config, dict) else {}
            if isinstance(mcp_cfg, dict):
                servers = list(mcp_cfg.get("servers", []))

        if not servers:
            import os

            env_val = os.environ.get("zeloo_MCP_SERVERS", "")
            if env_val:
                for entry in env_val.split(","):
                    entry = entry.strip()
                    if not entry or "=" not in entry:
                        continue
                    name, target = entry.split("=", 1)
                    if target.startswith("http://") or target.startswith("https://"):
                        servers.append({"name": name, "transport": "http", "url": target})
                    else:
                        parts = target.split()
                        servers.append({
                            "name": name,
                            "transport": "stdio",
                            "command": parts[0],
                            "args": parts[1:],
                        })
        return servers

    def _register_server(self, server: dict[str, Any]) -> int:
        """Start one MCP server and register all its tools."""
        transport = server.get("transport", "stdio")

        if transport == "http":
            from mcp.http_client import HttpMCPClient

            client = HttpMCPClient(
                url=server["url"],
                headers=server.get("headers"),
                timeout=float(server.get("timeout", 30)),
            )
        else:
            from mcp.stdio_client import StdioMCPClient

            client = StdioMCPClient(
                command=server["command"],
                args=list(server.get("args", [])),
                env=server.get("env"),
                timeout=float(server.get("timeout", 30)),
            )

        client.start()
        self._clients.append(client)

        registry = get_registry()
        all_tools = client.list_tools()

        # Apply per-server tool filtering (include/exclude patterns)
        tool_filter_cfg = server.get("tool_filter") or {}
        if isinstance(tool_filter_cfg, dict) and (
            tool_filter_cfg.get("include") or tool_filter_cfg.get("exclude")
        ):
            all_tools = filter_tools_from_config(all_tools, tool_filter_cfg)
            logger.info(
                "MCP server '%s': %d tool(s) after filtering",
                server.get("name"),
                len(all_tools),
            )

        count = 0
        for mcp_tool in all_tools:
            tool_name = mcp_tool.get("name", "")
            if not tool_name:
                continue
            # Prefix to avoid collisions with built-in tools
            prefixed_name = f"mcp_{tool_name}"

            def _make_executor(tn: str, cl: Any):
                return lambda **kw: cl.call_tool(tn, kw)

            tool_obj = Tool(
                name=prefixed_name,
                description=mcp_tool.get("description", ""),
                parameters=mcp_tool.get("inputSchema", {"type": "object", "properties": {}}),
                execute=_make_executor(tool_name, client),
                dangerous=bool(server.get("dangerous", False)),
                toolset="mcp",
            )
            registry.register(tool_obj)
            self._registered_names.append(prefixed_name)
            count += 1

        logger.info("Registered %d tool(s) from MCP server '%s'", count, server.get("name"))
        return count
