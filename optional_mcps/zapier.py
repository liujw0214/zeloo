"""Zapier MCP — workflow automation platform."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

ZAPIER_API_KEY = os.environ.get("ZAPIER_API_KEY", "")
ZAPIER_BASE_URL = "https://api.zapier.com/v1"


def _zapier_headers() -> dict[str, str]:
    if not ZAPIER_API_KEY:
        raise ValueError("ZAPIER_API_KEY must be set")
    return {
        "Authorization": f"Bearer {ZAPIER_API_KEY}",
        "Content-Type": "application/json",
    }


@make_tool
def zapier_list_zaps(limit: int = 50) -> str:
    """List Zapier zaps (workflows)."""
    url = f"{ZAPIER_BASE_URL}/zaps"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_zapier_headers(), params=params)
        resp.raise_for_status()
    zaps = [
        {"id": z["id"], "title": z.get("title"),
         "enabled": z.get("enabled", False),
         "app_pair": z.get("app_pair")}
        for z in resp.json().get("zaps", [])
    ]
    return json.dumps({"zaps": zaps}, indent=2, ensure_ascii=False)


@make_tool
def zapier_get_zap(zap_id: str) -> str:
    """Get Zap details."""
    url = f"{ZAPIER_BASE_URL}/zaps/{zap_id}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_zapier_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def zapier_toggle_zap(zap_id: str, enabled: bool) -> str:
    """Enable or disable a Zap."""
    url = f"{ZAPIER_BASE_URL}/zaps/{zap_id}"
    payload = {"enabled": enabled}
    with httpx.Client(timeout=15.0) as client:
        resp = client.patch(url, headers=_zapier_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps({"id": zap_id, "enabled": enabled})


@make_tool
def zapier_list_actions(zap_id: str) -> str:
    """List Zap actions."""
    url = f"{ZAPIER_BASE_URL}/zaps/{zap_id}/actions"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_zapier_headers())
        resp.raise_for_status()
    actions = [
        {"id": a["id"], "app": a.get("app"),
         "type": a.get("action_type")}
        for a in resp.json().get("actions", [])
    ]
    return json.dumps({"actions": actions}, indent=2, ensure_ascii=False)


@make_tool
def zapier_list_zap_history(
    zap_id: str, limit: int = 50
) -> str:
    """List Zap execution history."""
    url = f"{ZAPIER_BASE_URL}/zaps/{zap_id}/history"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_zapier_headers(), params=params)
        resp.raise_for_status()
    history = [
        {"id": h["id"], "status": h.get("status"),
         "timestamp": h.get("timestamp"),
         "data": h.get("data")}
        for h in resp.json().get("history", [])
    ]
    return json.dumps({"history": history}, indent=2, ensure_ascii=False)


TOOLS = [
    zapier_list_zaps,
    zapier_get_zap,
    zapier_toggle_zap,
    zapier_list_actions,
    zapier_list_zap_history,
]


class ZapierMCPServer(MCPServer):
    name = "zapier"
    description = "Zapier workflow automation platform"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["ZapierMCPServer", "TOOLS"]