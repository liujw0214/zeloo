"""Linear MCP — Linear issue tracking via official GraphQL API."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

LN_API_KEY = os.environ.get("LINEAR_API_KEY", "")


def _linear_headers() -> dict[str, str]:
    if not LN_API_KEY:
        raise ValueError("LINEAR_API_KEY must be set")
    return {
        "Authorization": LN_API_KEY,
        "Content-Type": "application/json",
    }


def _linear_query(q: str, variables: dict | None = None) -> dict:
    body: dict[str, Any] = {"query": q}
    if variables:
        body["variables"] = variables
    with httpx.Client(timeout=20.0) as client:
        resp = client.post(
            "https://api.linear.app/graphql",
            headers=_linear_headers(),
            json=body,
            timeout=30.0,
        )
        resp.raise_for_status()
    return resp.json()


@make_tool
def linear_list_workflows(limit: int = 50) -> str:
    """List Linear workflow states and transitions."""
    q = "{ workflows { nodes { id name states { id name type } } }"
    data = _linear_query(q)
    return json.dumps(data.get("data", {}).get("workflows", {}).get("nodes", []), indent=2)


@make_tool
def linear_list_labels(limit: int = 50) -> str:
    """List Linear team labels."""
    q = "query($limit: Int) { labels(limit: $limit) { nodes { id name color description } } }"
    data = _linear_query(q, {"limit": min(limit, 100)})
    labels = data.get("data", {}).get("labels", {}).get("nodes", [])
    return json.dumps({"labels": labels}, indent=2, ensure_ascii=False)


@make_tool
def linear_list_cycles(limit: int = 25) -> str:
    """List Linear cycles (sprints)."""
    q = "query($limit: Int) { cycles(limit: $limit) { nodes { id identifier name status startDate targetDate } } }"
    data = _linear_query(q, {"limit": min(limit, 50)})
    cycles = data.get("data", {}).get("cycles", {}).get("nodes", [])
    return json.dumps({"cycles": cycles}, indent=2, ensure_ascii=False)


@make_tool
def linear_list_projects(limit: int = 50) -> str:
    """List Linear projects."""
    q = "query($limit: Int) { projects(limit: $limit) { nodes { id name color state color } } }"
    data = _linear_query(q, {"limit": min(limit, 100)})
    projects = data.get("data", {}).get("projects", {}).get("nodes", [])
    return json.dumps({"projects": projects}, indent=2, ensure_ascii=False)


@make_tool
def linear_bulk_issues(issue_ids: str) -> str:
    """Get multiple Linear issues by IDs.

    Args:
        issue_ids: Comma-separated issue IDs (e.g. 'SYS-123,ENG-456').
    """
    ids = [i.strip() for i in issue_ids.split(",")]
    q = "query($ids: [String!]) { issuesFilter(ids: $ids) { nodes { id identifier title state { name } priority assignee { name } createdAt updatedAt } } }"
    data = _linear_query(q, {"ids": ids})
    issues = data.get("data", {}).get("issuesFilter", {}).get("nodes", [])
    return json.dumps({"issues": issues}, indent=2, ensure_ascii=False)


TOOLS = [
    linear_list_workflows,
    linear_list_labels,
    linear_list_cycles,
    linear_list_projects,
    linear_bulk_issues,
]


class LinearExtraMCPServer(MCPServer):
    name = "linear-extra"
    description = "Linear workflows, projects, cycles, labels via GraphQL"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["LinearExtraMCPServer", "TOOLS"]
