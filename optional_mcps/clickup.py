"""ClickUp MCP — workspace, space, folder, and task management."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

CLICKUP_TOKEN = os.environ.get("CLICKUP_API_KEY", "")
CLICKUP_BASE_URL = "https://api.clickup.com/api/v2"


def _clickup_headers() -> dict[str, str]:
    if not CLICKUP_TOKEN:
        raise ValueError("CLICKUP_API_KEY environment variable not set")
    return {
        "Authorization": CLICKUP_TOKEN,
        "Content-Type": "application/json",
    }


@make_tool
def clickup_list_tasks(
    list_id: str,
    status: str = "",
    limit: int = 100,
) -> str:
    """List tasks from a ClickUp list.

    Args:
        list_id: The ClickUp list ID.
        status: Filter by status name.
        limit: Maximum number of tasks.
    """
    url = f"{CLICKUP_BASE_URL}/list/{list_id}/task"
    params: dict[str, Any] = {"limit": min(limit, 500)}
    if status:
        params["status__name"] = status
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_clickup_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def clickup_create_task(
    name: str,
    list_id: str,
    content: str = "",
    priority: int = 3,
    due_date: str = "",
    assignees: str = "",
) -> str:
    """Create a new task in a ClickUp list.

    Args:
        name: Task name.
        list_id: The list ID.
        content: Task description.
        priority: 1=urgent, 2=high, 3=normal, 4=low.
        due_date: Due date in milliseconds timestamp.
        assignees: Comma-separated user IDs.
    """
    url = f"{CLICKUP_BASE_URL}/list/{list_id}/task"
    payload: dict[str, Any] = {"name": name, "priority": priority}
    if content:
        payload["content"] = content
    if due_date:
        payload["due_date"] = due_date
    if assignees:
        payload["assignees"] = [int(a.strip()) for a in assignees.split(",") if a.strip()]
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_clickup_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def clickup_get_task(task_id: str) -> str:
    """Get a specific task by ID.

    Args:
        task_id: The task ID.
    """
    url = f"{CLICKUP_BASE_URL}/task/{task_id}"
    params = {"include_subtasks": "true"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_clickup_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def clickup_update_task_status(
    task_id: str,
    status: str,
) -> str:
    """Update a task's status.

    Args:
        task_id: The task ID.
        status: New status name.
    """
    url = f"{CLICKUP_BASE_URL}/task/{task_id}"
    payload = {"status": status}
    with httpx.Client(timeout=15.0) as client:
        resp = client.put(url, headers=_clickup_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps({"message": "Status updated"})


@make_tool
def clickup_list_spaces(team_id: str) -> str:
    """List all spaces in a ClickUp workspace.

    Args:
        team_id: The team/workspace ID.
    """
    url = f"{CLICKUP_BASE_URL}/team/{team_id}/space"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_clickup_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    clickup_list_tasks,
    clickup_create_task,
    clickup_get_task,
    clickup_update_task_status,
    clickup_list_spaces,
]


class ClickUpMCPServer(MCPServer):
    name = "clickup"
    description = "ClickUp workspace, space, and task management"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["ClickUpMCPServer", "TOOLS"]
