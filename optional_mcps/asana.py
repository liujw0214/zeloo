"""Asana MCP — project and task management."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

ASANA_TOKEN = os.environ.get("ASANA_ACCESS_TOKEN", "")
ASANA_WORKSPACE = os.environ.get("ASANA_WORKSPACE_GID", "")
ASANA_BASE_URL = "https://app.asana.com/api/1.0"


def _asana_headers() -> dict[str, str]:
    if not ASANA_TOKEN:
        raise ValueError("ASANA_ACCESS_TOKEN environment variable not set")
    return {
        "Authorization": f"Bearer {ASANA_TOKEN}",
        "Content-Type": "application/json",
    }


@make_tool
def asana_list_projects(
    workspace: str = "",
    limit: int = 50,
) -> str:
    """List projects in an Asana workspace.

    Args:
        workspace: Workspace GID (defaults to ASANA_WORKSPACE_GID env var).
        limit: Number of projects to return.
    """
    workspace = workspace or ASANA_WORKSPACE
    if not workspace:
        return json.dumps({"error": "ASANA_WORKSPACE_GID not set"})
    url = f"{ASANA_BASE_URL}/workspaces/{workspace}/projects"
    params = {"limit": min(limit, 100), "opt_fields": "name,notes,completed"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_asana_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def asana_list_tasks(
    project_gid: str,
    limit: int = 50,
    completed: bool | None = None,
) -> str:
    """List tasks in an Asana project.

    Args:
        project_gid: The project GID.
        limit: Number of tasks to return.
        completed: Filter by completion status (None = all).
    """
    url = f"{ASANA_BASE_URL}/projects/{project_gid}/tasks"
    params: dict[str, Any] = {"limit": min(limit, 100)}
    if completed is not None:
        params["completed"] = completed
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_asana_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def asana_create_task(
    name: str,
    project_gid: str,
    notes: str = "",
    due_date: str = "",
    assignee: str = "",
) -> str:
    """Create a new task in an Asana project.

    Args:
        name: Task name.
        project_gid: The project GID.
        notes: Task description.
        due_date: Due date (YYYY-MM-DD format).
        assignee: Assignee email or user GID.
    """
    url = f"{ASANA_BASE_URL}/tasks"
    payload: dict[str, Any] = {
        "data": {
            "name": name,
            "projects": [project_gid],
            "notes": notes,
        }
    }
    if due_date:
        payload["data"]["due_on"] = due_date
    if assignee:
        payload["data"]["assignee"] = assignee
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_asana_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def asana_update_task(
    task_gid: str,
    name: str = "",
    notes: str = "",
    completed: bool | None = None,
) -> str:
    """Update an existing Asana task.

    Args:
        task_gid: The task GID.
        name: New task name.
        notes: New task description.
        completed: Mark as completed/incomplete.
    """
    url = f"{ASANA_BASE_URL}/tasks/{task_gid}"
    data: dict[str, Any] = {}
    if name:
        data["name"] = name
    if notes:
        data["notes"] = notes
    if completed is not None:
        data["completed"] = completed
    with httpx.Client(timeout=15.0) as client:
        resp = client.put(url, headers=_asana_headers(), json={"data": data})
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def asana_get_task(task_gid: str) -> str:
    """Get a specific task by GID.

    Args:
        task_gid: The task GID.
    """
    url = f"{ASANA_BASE_URL}/tasks/{task_gid}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_asana_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    asana_list_projects,
    asana_list_tasks,
    asana_create_task,
    asana_update_task,
    asana_get_task,
]


class AsanaMCPServer(MCPServer):
    name = "asana"
    description = "Asana project and task management"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["AsanaMCPServer", "TOOLS"]
