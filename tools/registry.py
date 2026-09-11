"""Tool registry — re-exports from tools.base for discoverability.

Use this module for direct registry access::

    from tools.registry import get_registry, ToolRegistry, Tool, discover_builtin_tools

Or import the registry singleton directly::

    from tools.base import _registry
"""

from tools.base import (
    BaseTool,
    Tool,
    ToolRegistry,
    discover_builtin_tools,
    get_registry,
    tool,
)

__all__ = [
    "BaseTool",
    "Tool",
    "ToolRegistry",
    "discover_builtin_tools",
    "get_registry",
    "tool",
]
