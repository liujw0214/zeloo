"""Optional MCP server catalog.

Pre-configured MCP server definitions for the P1 priority servers.
"""

from __future__ import annotations

from optional_mcps.server_registry import (
    MCPServerDefinition,
    get_all_servers,
    get_server,
    list_servers,
)

__all__ = [
    "MCPServerDefinition",
    "get_all_servers",
    "get_server",
    "list_servers",
]
