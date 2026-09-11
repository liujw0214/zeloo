"""MCP tool filtering — include/exclude by name or glob pattern.

Used to restrict which tools from an MCP server are exposed to the agent.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from typing import Any


def filter_tools(
    tools: list[dict[str, Any]],
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Filter MCP tools by name patterns.

    Args:
        tools: List of tool dicts (each must have a "name" key).
        include: Glob patterns for tool names to keep. If empty/None, all
                 tools are candidates.
        exclude: Glob patterns for tool names to drop. Exclusions take
                 precedence over inclusions.

    Returns:
        The filtered list of tools.
    """
    if not tools:
        return []

    include = include or []
    exclude = exclude or []

    result: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("name", "")

        # Exclude takes precedence
        if _matches_any(name, exclude):
            continue

        # If include patterns are specified, the name must match at least one
        if include and not _matches_any(name, include):
            continue

        result.append(tool)

    return result


def _matches_any(name: str, patterns: Iterable[str]) -> bool:
    """Return True if *name* matches any of the glob *patterns*."""
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def filter_tools_from_config(
    tools: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Filter tools using a config dict with ``include``/``exclude`` keys."""
    return filter_tools(
        tools,
        include=config.get("include"),
        exclude=config.get("exclude"),
    )
