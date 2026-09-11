"""Wrike MCP — work management and project tracking."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

WRIKE_TOKEN = os.environ.get("WRIKE_API_TOKEN", "")
WRIKE_BASE_URL = "https://www.wrike.com/api/v4"


def _wrike_headers() -> dict[str, str]:
    if not WRIKE_TOKEN:
        raise ValueError("WRIKE_API_TOKEN must be set")
    return {
        "Authorization": f"Bearer {WRIKE_TOKEN}",
        "Content-Type": "application/json",
    }


@make_tool
def wrike_list_folders(limit: int = 50) -> str:
    """List Wrike folders."""
    url = f"{WRIKE_BASE_URL}/folders"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_wrike_headers(), params=params)
        resp.raise_for_status()
    folders = [
        {"id": f["id"], "title": f.get("title"),
         "permalink": f.get("permalink")}
        for f in resp.json().get("data", [])
    ]
    return json.dumps({"folders": folders}, indent=2, ensure_ascii=False)


@make_tool
def wrike_list_tasks(folder_id: str, limit: int = 50) -> str:
    """List tasks in Wrike folder."""
    url = f"{WRIKE_BASE_URL}/folders/{folder_id}/tasks"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_wrike_headers(), params=params)
        resp.raise_for_status()
    tasks = [
        {"id": t["id"], "title": t.get("title"),
         "status": t.get("status"), "importance": t.get("importance")}
        for t in resp.json().get("data", [])
    ]
    return json.dumps({"tasks": tasks}, indent=2, ensure_ascii=False)


@make_tool
def wrike_create_task(
    folder_id: str,
    title: str,
    description: str = "",
) -> str:
    """Create a new task in Wrike."""
    url = f"{WRIKE_BASE_URL}/folders/{folder_id}/tasks"
    payload = {
        "title": title,
        "description": description,
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_wrike_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def wrike_update_task(
    task_id: str,
    title: str = "",
    description: str = "",
    status: str = "",
) -> str:
    """Update an existing Wrike task."""
    url = f"{WRIKE_BASE_URL}/tasks/{task_id}"
    payload: dict[str, Any] = {}
    if title:
        payload["title"] = title
    if description:
        payload["description"] = description
    if status:
        payload["status"] = status
    with httpx.Client(timeout=15.0) as client:
        resp = client.put(url, headers=_wrike_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps({"status": "updated", "id": task_id})


@make_tool
def wrike_list_comments(task_id: str) -> str:
    """List comments on a Wrike task."""
    url = f"{WRIKE_BASE_URL}/tasks/{task_id}/comments"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_wrike_headers())
        resp.raise_for_status()
    comments = [
        {"id": c["id"], "text": c.get("text")}
        for c in resp.json().get("data", [])
    ]
    return json.dumps({"comments": comments}, indent=2, ensure_ascii=False)


TOOLS = [
    wrike_list_folders,
    wrike_list_tasks,
    wrike_create_task,
    wrike_update_task,
    wrike_list_comments,
]


class WrikeMCPServer(MCPServer):
    name = "wrike"
    description = "Wrike work management"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["WrikeMCPServer", "TOOLS"]