"""Todoist MCP — task and project management."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

TODOIST_TOKEN = os.environ.get("TODOIST_API_TOKEN", "")
TODOIST_BASE_URL = "https://api.todoist.com/rest/v2"


def _todoist_headers() -> dict[str, str]:
    if not TODOIST_TOKEN:
        raise ValueError("TODOIST_API_TOKEN environment variable not set")
    return {
        "Authorization": f"Bearer {TODOIST_TOKEN}",
        "Content-Type": "application/json",
    }


@make_tool
def todoist_list_tasks(
    project_id: str = "",
    filter_str: str = "",
    limit: int = 50,
) -> str:
    """List tasks from Todoist.

    Args:
        project_id: Filter by project ID.
        filter_str: Todoist filter string (e.g. "today | overdue").
        limit: Maximum number of tasks.
    """
    url = f"{TODOIST_BASE_URL}/tasks"
    params: dict[str, Any] = {"limit": min(limit, 100)}
    if project_id:
        params["project_id"] = project_id
    if filter_str:
        params["filter"] = filter_str
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_todoist_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def todoist_create_task(
    content: str,
    project_id: str = "",
    due_string: str = "",
    priority: int = 1,
    description: str = "",
) -> str:
    """Create a new task in Todoist.

    Args:
        content: Task title.
        project_id: Project ID to add task to.
        due_string: Natural language due date (e.g. "tomorrow", "next monday").
        priority: 1=normal, 2=high, 3=urgent.
        description: Task description.
    """
    url = f"{TODOIST_BASE_URL}/tasks"
    payload: dict[str, Any] = {"content": content}
    if project_id:
        payload["project_id"] = project_id
    if due_string:
        payload["due_string"] = due_string
    if priority:
        payload["priority"] = min(max(priority, 1), 4)
    if description:
        payload["description"] = description
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_todoist_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def todoist_close_task(task_id: int) -> str:
    """Close (complete) a Todoist task.

    Args:
        task_id: The task ID.
    """
    url = f"{TODOIST_BASE_URL}/tasks/{task_id}/close"
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_todoist_headers())
        resp.raise_for_status()
    return json.dumps({"message": "Task closed successfully"})


@make_tool
def todoist_delete_task(task_id: int) -> str:
    """Delete a Todoist task permanently.

    Args:
        task_id: The task ID.
    """
    url = f"{TODOIST_BASE_URL}/tasks/{task_id}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.delete(url, headers=_todoist_headers())
        resp.raise_for_status()
    return json.dumps({"message": "Task deleted successfully"})


@make_tool
def todoist_list_projects() -> str:
    """List all Todoist projects."""
    url = f"{TODOIST_BASE_URL}/projects"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_todoist_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    todoist_list_tasks,
    todoist_create_task,
    todoist_close_task,
    todoist_delete_task,
    todoist_list_projects,
]


class TodoistMCPServer(MCPServer):
    name = "todoist"
    description = "Todoist task and project management"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["TodoistMCPServer", "TOOLS"]
