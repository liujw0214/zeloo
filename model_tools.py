"""Tool orchestration — discover, filter, and expose tools to the agent."""

from __future__ import annotations

import logging
import os
from typing import Any

from tools.base import get_registry
from toolsets import get_toolset_for_tool, get_toolsets_for_platform

logger = logging.getLogger(__name__)

# Dangerous-tool policy. Controlled by zeloo_DANGEROUS_POLICY env var:
#   "allow"   (default) — dangerous tools run normally
#   "deny"    — dangerous tools are rejected with an error message
#   "confirm" — first call returns a confirmation prompt; the agent must
#               re-invoke the tool with __confirm=true in the arguments
_DANGEROUS_POLICY = os.environ.get("zeloo_DANGEROUS_POLICY", "allow").lower().strip()

# Internal flag used by the "confirm" policy.
_CONFIRM_FLAG = "__confirm"


def get_dangerous_tool_names() -> list[str]:
    """Return the names of all registered tools marked as dangerous."""
    registry = get_registry()
    return [name for name, tool in registry.get_all().items() if tool.dangerous]


def discover_and_filter_tools(platform: str = "cli") -> dict[str, Any]:
    """Discover all built-in tools and filter by platform.

    Returns a dict with:
    - valid_tool_names: set of enabled tool names
    - available_toolsets: set of enabled toolset names
    - tool_schemas: list of OpenAI tool schemas
    """
    from tools.base import discover_builtin_tools

    discover_builtin_tools()

    registry = get_registry()
    enabled_toolsets = set(get_toolsets_for_platform(platform))

    valid_tool_names: set[str] = set()
    for name in registry.get_names():
        toolset = get_toolset_for_tool(name)
        if toolset is None or toolset in enabled_toolsets:
            valid_tool_names.add(name)

    tool_schemas = [
        registry.get(name).to_openai_schema()
        for name in valid_tool_names
        if registry.get(name)
    ]

    return {
        "valid_tool_names": valid_tool_names,
        "available_toolsets": enabled_toolsets,
        "tool_schemas": tool_schemas,
    }


def execute_tool(name: str, args: dict[str, Any]) -> Any:
    """Execute a tool by name with the given arguments.

    Dangerous tools are subject to the policy set by ``zeloo_DANGEROUS_POLICY``:
    allow (default), deny, or confirm (re-invoke with ``__confirm=true``).
    """
    registry = get_registry()
    tool = registry.get(name)
    if tool is None:
        return {"error": f"Unknown tool: {name}"}

    # --- Dangerous tool policy ---
    if tool.dangerous and _DANGEROUS_POLICY != "allow":
        confirmed = bool(args.pop(_CONFIRM_FLAG, False))
        if _DANGEROUS_POLICY == "deny":
            return {
                "error": (
                    f"Tool '{name}' is dangerous and execution is denied "
                    "(zeloo_DANGEROUS_POLICY=deny)."
                )
            }
        if _DANGEROUS_POLICY == "confirm" and not confirmed:
            return {
                "error": (
                    f"Tool '{name}' is dangerous. To confirm, re-invoke it "
                    f"with the argument '{_CONFIRM_FLAG}': true."
                )
            }

    # --- Per-tool confirmation_required (overrides global allow policy) ---
    if tool.confirmation_required:
        confirmed = bool(args.pop(_CONFIRM_FLAG, False))
        if not confirmed:
            return {
                "error": (
                    f"Tool '{name}' requires explicit confirmation. "
                    f"Re-invoke it with the argument '{_CONFIRM_FLAG}': true."
                )
            }

    try:
        return tool.execute(**args)
    except TypeError:
        # If the function expects 'self', try without it
        try:
            return tool.execute(args)
        except Exception as e:
            logger.exception("Tool %s failed", name)
            return {"error": str(e)}
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return {"error": str(e)}
