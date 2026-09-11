"""Bamboo MCP — Atlassian CI/CD server."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

BAMBOO_URL = os.environ.get("BAMBOO_URL", "")
BAMBOO_USER = os.environ.get("BAMBOO_USER", "")
BAMBOO_TOKEN = os.environ.get("BAMBOO_API_TOKEN", "")
BAMBOO_BASE_URL = ""


def _bamboo_url(path: str) -> str:
    if not BAMBOO_URL:
        raise ValueError("BAMBOO_URL must be set")
    return f"{BAMBOO_URL}/rest/api/latest/{path.lstrip('/')}"


def _bamboo_headers() -> dict[str, str]:
    if not BAMBOO_USER or not BAMBOO_TOKEN:
        raise ValueError("BAMBOO_USER and BAMBOO_API_TOKEN must be set")
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _bamboo_auth() -> tuple[str, str]:
    return (BAMBOO_USER, BAMBOO_TOKEN)


@make_tool
def bamboo_list_plans(limit: int = 50) -> str:
    """List all Bamboo build plans."""
    url = _bamboo_url("plans")
    params = {"max-result": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_bamboo_headers(),
                          params=params, auth=_bamboo_auth())
        resp.raise_for_status()
    plans = [
        {"key": p["key"], "name": p.get("name"),
         "enabled": p.get("enabled", False)}
        for p in resp.json().get("plans", {}).get("plan", [])
    ]
    return json.dumps({"plans": plans}, indent=2, ensure_ascii=False)


@make_tool
def bamboo_get_plan(plan_key: str) -> str:
    """Get Bamboo plan details."""
    url = _bamboo_url(f"plan/{plan_key}")
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_bamboo_headers(), auth=_bamboo_auth())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def bamboo_list_plan_branches(plan_key: str) -> str:
    """List Bamboo plan branches."""
    url = _bamboo_url(f"plan/{plan_key}/branch")
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_bamboo_headers(), auth=_bamboo_auth())
        resp.raise_for_status()
    branches = [
        {"key": b["key"], "name": b.get("name"),
         "enabled": b.get("enabled", False)}
        for b in resp.json().get("branches", {}).get("branch", [])
    ]
    return json.dumps({"branches": branches}, indent=2, ensure_ascii=False)


@make_tool
def bamboo_trigger_build(plan_key: str) -> str:
    """Trigger a Bamboo build."""
    url = _bamboo_url(f"queue/{plan_key}")
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=_bamboo_headers(), auth=_bamboo_auth())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def bamboo_list_results(plan_key: str, limit: int = 25) -> str:
    """List recent build results for a Bamboo plan."""
    url = _bamboo_url(f"result/{plan_key}")
    params = {"max-result": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_bamboo_headers(),
                          params=params, auth=_bamboo_auth())
        resp.raise_for_status()
    results = [
        {"number": r["buildNumber"], "state": r.get("state"),
         "build_date": r.get("buildDateTime")}
        for r in resp.json().get("results", {}).get("result", [])
    ]
    return json.dumps({"results": results}, indent=2, ensure_ascii=False)


TOOLS = [
    bamboo_list_plans,
    bamboo_get_plan,
    bamboo_list_plan_branches,
    bamboo_trigger_build,
    bamboo_list_results,
]


class BambooMCPServer(MCPServer):
    name = "bamboo"
    description = "Atlassian Bamboo CI/CD server"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["BambooMCPServer", "TOOLS"]