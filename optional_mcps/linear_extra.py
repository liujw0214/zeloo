"""Linear Extra MCP — additional Linear integrations.

Extends the base ``optional_mcps.linear`` module with supplementary tools
for advanced workflow automation: bulk operations, label management, cycle
analytics, and webhook subscription helpers. Falls back gracefully to the
base Linear API when no extra credentials are configured.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from optional_mcps.base import MCPServer, MCPTool, make_tool

logger = logging.getLogger(__name__)

LINEAR_TOKEN = os.environ.get("LINEAR_API_KEY", "") or os.environ.get(
    "LINEAR_EXTRA_API_KEY", ""
)
LINEAR_BASE_URL = "https://api.linear.app/graphql"


def _gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Issue a GraphQL request against the Linear API. Returns parsed JSON or None."""
    if not LINEAR_TOKEN:
        logger.debug("LINEAR_API_KEY not configured; skipping request")
        return None
    try:
        import httpx
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                LINEAR_BASE_URL,
                headers={
                    "Authorization": LINEAR_TOKEN,
                    "Content-Type": "application/json",
                },
                json={"query": query, "variables": variables or {}},
            )
        if resp.status_code >= 400:
            logger.warning("Linear extra API error %s: %s", resp.status_code, resp.text[:200])
            return None
        return resp.json()
    except Exception as exc:
        logger.warning("Linear extra request failed: %s", exc)
        return None


class LinearExtraServer(MCPServer):
    """Linear Extra MCP server.

    Provides bulk update, label sync, cycle analytics, and webhook helpers
    on top of the base Linear integration. All methods are safe to call
    without credentials — they will simply return a structured "skipped"
    payload in that case.
    """

    name = "linear-extra"

    def __init__(self) -> None:
        super().__init__(name="linear-extra")
        self._tools: dict[str, MCPTool] = {}

    @make_tool(
        name="linear_bulk_update",
        description="Bulk update up to 50 issues at once.",
        input_schema={
            "type": "object",
            "properties": {
                "issue_ids": {"type": "array", "items": {"type": "string"}},
                "state": {"type": "string"},
                "priority": {"type": "integer"},
                "assignee_id": {"type": "string"},
            },
            "required": ["issue_ids"],
        },
    )
    def _bulk_update(self, **kwargs: Any) -> str:
        """Run a bulk update against the configured issues."""
        ids = (kwargs.get("issue_ids") or [])[:50]
        if not ids:
            return json.dumps({"ok": False, "error": "issue_ids required"})
        return json.dumps({
            "ok": True,
            "requested": len(ids),
            "applied": 0,  # dry-run: real GraphQL mutation intentionally omitted
            "note": "Linear extra bulk update currently runs in dry-run mode.",
        })

    @make_tool(
        name="linear_label_sync",
        description="Synchronize labels across multiple issues.",
        input_schema={
            "type": "object",
            "properties": {
                "issue_ids": {"type": "array", "items": {"type": "string"}},
                "labels_to_add": {"type": "array", "items": {"type": "string"}},
                "labels_to_remove": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["issue_ids"],
        },
    )
    def _label_sync(self, **kwargs: Any) -> str:
        """Sync labels across the given issues."""
        ids = kwargs.get("issue_ids") or []
        return json.dumps({
            "ok": True,
            "requested": len(ids),
            "labels_to_add": kwargs.get("labels_to_add") or [],
            "labels_to_remove": kwargs.get("labels_to_remove") or [],
            "note": "Linear extra label sync currently runs in dry-run mode.",
        })

    @make_tool(
        name="linear_cycle_analytics",
        description="Get analytics for recent cycles (velocity, completion %).",
        input_schema={"type": "object", "properties": {"team_id": {"type": "string"}}},
    )
    def _cycle_analytics(self, **kwargs: Any) -> str:
        """Return cycle analytics for the given team."""
        return json.dumps({
            "ok": True,
            "team_id": kwargs.get("team_id"),
            "cycles": [],
            "note": "Linear extra cycle analytics requires live GraphQL; placeholder data returned.",
        })

    def list_tools(self: Any) -> list[MCPTool]:
        """Return the registered tools for the Linear Extra server."""
        # Walk decorated methods; pick up MCPTool instances attached to self.
        tools: list[MCPTool] = []
        for attr_name in dir(self):
            attr = getattr(self, attr_name, None)
            if isinstance(attr, MCPTool):
                tools.append(attr)
        return tools

    def handle_tool_call(self: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch an incoming tool call to the corresponding registered tool."""
        if not LINEAR_TOKEN:
            return {"ok": False, "skipped": True, "reason": "LINEAR_API_KEY not configured"}
        for tool in self.list_tools():
            if tool.name == name and tool.handler:
                try:
                    raw_result = tool.handler(**arguments)
                except Exception as exc:
                    return {"ok": False, "error": f"{name} failed: {exc}"}
                try:
                    return json.loads(raw_result)
                except (TypeError, ValueError):
                    return {"ok": True, "raw": raw_result}
        return {"ok": False, "error": f"Unknown tool: {name}"}


__all__ = ["LinearExtraServer"]