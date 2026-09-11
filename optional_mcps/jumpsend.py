"""JumpCloud MCP — directory, SSO, and device management."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

JC_KEY = os.environ.get("JUMPCLOUD_API_KEY", "")


def _jc_headers() -> dict[str, str]:
    if not JC_KEY:
        raise ValueError("JUMPCLOUD_API_KEY must be set")
    return {
        "x-api-key": JC_KEY,
        "Content-Type": "application/json",
    }


@make_tool
def jumpcloud_list_users(limit: int = 50) -> str:
    """List JumpCloud users."""
    url = "https://console.jumpcloud.com/api/search/users"
    payload = {"searchList":{"fields": ["username", "email"], "render": "list"}}
    resp = httpx.post(url, headers=_jc_headers(), json=payload, timeout=15.0)
    resp.raise_for_status()
    users = [
        {"id": u["id"], "username": u.get("username"),
         "email": u.get("email"), "state": u.get("state")}
        for u in resp.json().get("results", [])
    ]
    return json.dumps({"users": users}, indent=2, ensure_ascii=False)


@make_tool
def jumpcloud_list_groups(limit: int = 50) -> str:
    """List JumpCloud user groups."""
    url = "https://console.jumpcloud.com/api/v2/usergroups"
    params = {"limit": min(limit, 100)}
    resp = httpx.get(url, headers=_jc_headers(), params=params, timeout=15.0)
    resp.raise_for_status()
    groups = [
        {"id": g["id"], "name": g["name"]}
        for g in resp.json()
    ]
    return json.dumps({"groups": groups}, indent=2, ensure_ascii=False)


@make_tool
def jumpcloud_list_systems(limit: int = 50) -> str:
    """List JumpCloud managed systems (devices)."""
    url = "https://console.jumpcloud.com/api/search/systems"
    payload = {"searchList":{"fields": ["hostname"], "render": "list"}}
    resp = httpx.post(url, headers=_jc_headers(), json=payload, timeout=15.0)
    resp.raise_for_status()
    systems = [
        {"id": s["id"], "hostname": s.get("hostname"),
         "os": s.get("os"), "state": s.get("state")}
        for s in resp.json().get("results", [])
    ]
    return json.dumps({"systems": systems}, indent=2, ensure_ascii=False)


@make_tool
def jumpcloud_list_applications() -> str:
    """List JumpCloud SSO applications."""
    url = "https://console.jumpcloud.com/api/v2/applications"
    resp = httpx.get(url, headers=_jc_headers(), timeout=15.0)
    resp.raise_for_status()
    apps = [
        {"id": a["id"], "name": a["name"],
         "description": a.get("description", "")}
        for a in resp.json()
    ]
    return json.dumps({"applications": apps}, indent=2, ensure_ascii=False)


@make_tool
def jumpcloud_list_policies() -> str:
    """List JumpCloud policies."""
    url = "https://console.jumpcloud.com/api/v2/policies"
    resp = httpx.get(url, headers=_jc_headers(), timeout=15.0)
    resp.raise_for_status()
    policies = [
        {"id": p["id"], "name": p["name"],
         "policyType": p.get("policyType")}
        for p in resp.json()
    ]
    return json.dumps({"policies": policies}, indent=2, ensure_ascii=False)


TOOLS = [
    jumpcloud_list_users,
    jumpcloud_list_groups,
    jumpcloud_list_systems,
    jumpcloud_list_applications,
    jumpcloud_list_policies,
]


class JumpCloudMCPServer(MCPServer):
    name = "jumpcloud"
    description = "JumpCloud directory, SSO, and device management"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["JumpCloudMCPServer", "TOOLS"]
