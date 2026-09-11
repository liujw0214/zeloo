"""Shortcut MCP — project management for software teams."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

SHORTCUT_TOKEN = os.environ.get("SHORTCUT_API_TOKEN", "")
SHORTCUT_BASE_URL = "https://api.app.shortcut.com/api/v3"


def _shortcut_headers() -> dict[str, str]:
    if not SHORTCUT_TOKEN:
        raise ValueError("SHORTCUT_API_TOKEN must be set")
    return {
        "Shortcut-Token": SHORTCUT_TOKEN,
        "Content-Type": "application/json",
    }


@make_tool
def shortcut_list_stories(limit: int = 50) -> str:
    """List Shortcut stories (tickets)."""
    url = f"{SHORTCUT_BASE_URL}/stories"
    params = {"page_size": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_shortcut_headers(), params=params)
        resp.raise_for_status()
    stories = [
        {"id": s["id"], "name": s.get("name"),
         "type": s.get("story_type"),
         "workflow_state_id": s.get("workflow_state_id")}
        for s in resp.json()
    ]
    return json.dumps({"stories": stories}, indent=2, ensure_ascii=False)


@make_tool
def shortcut_create_story(
    name: str,
    description: str = "",
    story_type: str = "feature",
) -> str:
    """Create a new Shortcut story."""
    url = f"{SHORTCUT_BASE_URL}/stories"
    payload = {
        "name": name,
        "description": description,
        "story_type": story_type,
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_shortcut_headers(), json=payload)
        resp.raise_for_status()
    story = resp.json()
    return json.dumps({"id": story["id"], "name": story["name"]}, indent=2)


@make_tool
def shortcut_update_story(
    story_id: int,
    name: str = "",
    description: str = "",
    workflow_state_id: int = 0,
) -> str:
    """Update a Shortcut story."""
    url = f"{SHORTCUT_BASE_URL}/stories/{story_id}"
    payload: dict[str, Any] = {}
    if name:
        payload["name"] = name
    if description:
        payload["description"] = description
    if workflow_state_id:
        payload["workflow_state_id"] = workflow_state_id
    with httpx.Client(timeout=15.0) as client:
        resp = client.put(url, headers=_shortcut_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps({"status": "updated", "id": story_id})


@make_tool
def shortcut_list_workflows() -> str:
    """List Shortcut workflows (state machines)."""
    url = f"{SHORTCUT_BASE_URL}/workflows"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_shortcut_headers())
        resp.raise_for_status()
    workflows = [
        {"id": w["id"], "name": w.get("name"),
         "states": [{"id": s["id"], "name": s["name"]}
                    for s in w.get("states", [])]}
        for w in resp.json()
    ]
    return json.dumps({"workflows": workflows}, indent=2, ensure_ascii=False)


@make_tool
def shortcut_list_members() -> str:
    """List Shortcut workspace members."""
    url = f"{SHORTCUT_BASE_URL}/members"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_shortcut_headers())
        resp.raise_for_status()
    members = [
        {"id": m["id"], "name": m.get("name"),
         "role": m.get("role")}
        for m in resp.json()
    ]
    return json.dumps({"members": members}, indent=2, ensure_ascii=False)


TOOLS = [
    shortcut_list_stories,
    shortcut_create_story,
    shortcut_update_story,
    shortcut_list_workflows,
    shortcut_list_members,
]


class ShortcutMCPServer(MCPServer):
    name = "shortcut"
    description = "Shortcut project management for software teams"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["ShortcutMCPServer", "TOOLS"]