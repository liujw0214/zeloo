"""Make.com (Integromat) MCP — no-code automation."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

MAKE_API_KEY = os.environ.get("MAKE_API_KEY", "")
MAKE_ZONE = os.environ.get("MAKE_ZONE", "us1")
MAKE_BASE_URL = f"https://{MAKE_ZONE}.make.com/api/v2"


def _make_headers() -> dict[str, str]:
    if not MAKE_API_KEY:
        raise ValueError("MAKE_API_KEY must be set")
    return {
        "Authorization": f"Token {MAKE_API_KEY}",
        "Content-Type": "application/json",
    }


@make_tool
def make_list_scenarios(limit: int = 50) -> str:
    """List Make.com scenarios (workflows)."""
    url = f"{MAKE_BASE_URL}/scenarios"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_make_headers(), params=params)
        resp.raise_for_status()
    scenarios = [
        {"id": s["id"], "name": s.get("name"),
         "active": s.get("scheduling", {}).get("enabled", False),
         "folder": s.get("folderName")}
        for s in resp.json().get("scenarios", [])
    ]
    return json.dumps({"scenarios": scenarios}, indent=2, ensure_ascii=False)


@make_tool
def make_get_scenario(scenario_id: int) -> str:
    """Get scenario details."""
    url = f"{MAKE_BASE_URL}/scenarios/{scenario_id}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_make_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def make_run_scenario(scenario_id: int) -> str:
    """Run a Make.com scenario."""
    url = f"{MAKE_BASE_URL}/scenarios/{scenario_id}/run"
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=_make_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def make_list_organizations() -> str:
    """List Make.com organizations."""
    url = f"{MAKE_BASE_URL}/organizations"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_make_headers())
        resp.raise_for_status()
    orgs = [
        {"id": o["id"], "name": o.get("name"),
         "zone": o.get("zone")}
        for o in resp.json().get("organizations", [])
    ]
    return json.dumps({"organizations": orgs}, indent=2, ensure_ascii=False)


@make_tool
def make_list_apps() -> str:
    """List Make.com apps."""
    url = f"{MAKE_BASE_URL}/apps"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_make_headers())
        resp.raise_for_status()
    apps = [
        {"id": a["id"], "name": a.get("name"),
         "label": a.get("label")}
        for a in resp.json().get("apps", [])
    ]
    return json.dumps({"apps": apps}, indent=2, ensure_ascii=False)


TOOLS = [
    make_list_scenarios,
    make_get_scenario,
    make_run_scenario,
    make_list_organizations,
    make_list_apps,
]


class MakeMCPServer(MCPServer):
    name = "make"
    description = "Make.com (Integromat) no-code automation"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["MakeMCPServer", "TOOLS"]