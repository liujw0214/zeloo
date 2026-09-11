"""Linear MCP — issue tracking and project management."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

LINEAR_TOKEN = os.environ.get("LINEAR_API_KEY", "")
LINEAR_BASE_URL = "https://api.linear.app/graphql"

# Human-readable priority labels
_PRIORITY_LABELS: dict[int, str] = {
    0: "No priority",
    1: "Urgent",
    2: "High",
    3: "Medium",
    4: "Low",
}


def _format_issue(issue: dict[str, Any]) -> str:
    """Render a Linear issue dict into a human-readable summary string.

    Fields used: ``title``, ``identifier``, ``state``, ``assignee``,
    ``priority``, ``url``, ``estimate``.
    """
    title = issue.get("title", "")
    identifier = issue.get("identifier", "")
    state_obj = issue.get("state") or {}
    state_name = (
        state_obj.get("name", "Unknown")
        if isinstance(state_obj, dict)
        else str(state_obj)
    )
    assignee_obj = issue.get("assignee")
    if isinstance(assignee_obj, dict):
        assignee_name = assignee_obj.get("name") or "unassigned"
    elif assignee_obj:
        assignee_name = str(assignee_obj)
    else:
        assignee_name = "unassigned"
    priority_raw = issue.get("priority", 0)
    priority = _PRIORITY_LABELS.get(int(priority_raw or 0), str(priority_raw))
    url = issue.get("url", "")
    estimate = issue.get("estimate")

    lines = [
        f"[{identifier}] {title}",
        f"State: {state_name}",
        f"Assignee: {assignee_name}",
        f"Priority: {priority}",
    ]
    if url:
        lines.append(f"URL: {url}")
    if estimate is not None:
        lines.append(f"Estimate: {estimate}")
    return "\n".join(lines)


def _linear_headers() -> dict[str, str]:
    if not LINEAR_TOKEN:
        raise ValueError("LINEAR_API_KEY environment variable not set")
    return {
        "Authorization": f"Bearer {LINEAR_TOKEN}",
        "Content-Type": "application/json",
    }


def _linear_query(query: str, variables: dict | None = None) -> dict:
    body: dict[str, Any] = {"query": query}
    if variables:
        body["variables"] = variables
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(LINEAR_BASE_URL, headers=_linear_headers(), json=body)
        resp.raise_for_status()
    return resp.json()


@make_tool
def linear_list_issues(
    limit: int = 25,
    state: str = "",
) -> str:
    """List issues from Linear.

    Args:
        limit: Number of issues to return.
        state: Filter by state name (e.g. 'In Progress', 'Done').
    """
    query = """
    query ListIssues($limit: Int, $filter: IssueFilter) {
        issues(limit: $limit, filter: $filter) {
            nodes {
                id identifier title state { name } priority
                assignee { name } createdAt updatedAt
            }
        }
    }
    """
    variables: dict[str, Any] = {"limit": min(limit, 100)}
    if state:
        variables["filter"] = {"state": {"name": {"eq": state}}}
    data = _linear_query(query, variables)
    return json.dumps(data, indent=2, ensure_ascii=False)


@make_tool
def linear_create_issue(
    title: str,
    description: str = "",
    team_id: str = "",
    priority: int = 0,
) -> str:
    """Create a new issue in Linear.

    Args:
        title: Issue title.
        description: Issue description.
        team_id: Team GID.
        priority: Priority (0=None, 1=Urgent, 2=High, 3=Medium, 4=Low).
    """
    query = """
    mutation CreateIssue($input: IssueCreateInput!) {
        issueCreate(input: $input) {
            success issue { id identifier title }
        }
    }
    """
    input_data: dict[str, Any] = {"title": title}
    if description:
        input_data["description"] = description
    if team_id:
        input_data["teamId"] = team_id
    if priority:
        input_data["priority"] = priority
    data = _linear_query(query, {"input": input_data})
    return json.dumps(data, indent=2, ensure_ascii=False)


@make_tool
def linear_list_teams() -> str:
    """List all teams in Linear workspace."""
    query = """
    query ListTeams {
        teams {
            nodes { id name key }
        }
    }
    """
    data = _linear_query(query)
    return json.dumps(data, indent=2, ensure_ascii=False)


@make_tool
def linear_get_issue(issue_id: str) -> str:
    """Get a specific issue by ID.

    Args:
        issue_id: The issue ID (e.g. 'SYS-123').
    """
    query = """
    query GetIssue($id: String!) {
        issue(id: $id) {
            id identifier title description state { name }
            priority assignee { name } createdAt updatedAt
        }
    }
    """
    data = _linear_query(query, {"id": issue_id})
    return json.dumps(data, indent=2, ensure_ascii=False)


@make_tool
def linear_update_issue(
    issue_id: str,
    state_name: str,
) -> str:
    """Update an issue's state (status).

    Args:
        issue_id: The issue ID (e.g. 'SYS-123').
        state_name: Target state name (e.g. 'In Progress', 'Done').
    """
    query = """
    mutation UpdateIssue($id: String!, $stateName: String!) {
        issueUpdate(id: $id, input: {}) {
            success
        }
    }
    """
    data = _linear_query(query, {"id": issue_id, "stateName": state_name})
    return json.dumps(data, indent=2, ensure_ascii=False)


TOOLS = [
    linear_list_issues,
    linear_create_issue,
    linear_list_teams,
    linear_get_issue,
    linear_update_issue,
]


class LinearMCPServer(MCPServer):
    name = "linear"
    description = "Linear issue tracking and project management"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["LinearMCPServer", "TOOLS"]
