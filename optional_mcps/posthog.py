"""PostHog MCP — product analytics and feature flags."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

POSTHOG_API_KEY = os.environ.get("POSTHOG_API_KEY", "")
POSTHOG_HOST = os.environ.get("POSTHOG_HOST", "https://app.posthog.com")
POSTHOG_PROJECT_ID = os.environ.get("POSTHOG_PROJECT_ID", "")


def _ph_headers() -> dict[str, str]:
    if not POSTHOG_API_KEY:
        raise ValueError("POSTHOG_API_KEY must be set")
    return {
        "Authorization": f"Bearer {POSTHOG_API_KEY}",
        "Content-Type": "application/json",
    }


@make_tool
def posthog_capture(
    distinct_id: str,
    event: str,
    properties: str = "{}",
) -> str:
    """Capture an event to PostHog."""
    url = f"{POSTHOG_HOST}/capture/"
    payload = {
        "api_key": POSTHOG_API_KEY,
        "event": event,
        "distinct_id": distinct_id,
        "properties": json.loads(properties),
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
    return json.dumps({"status": "captured", "event": event})


@make_tool
def posthog_list_feature_flags() -> str:
    """List all feature flags in PostHog project."""
    url = f"{POSTHOG_HOST}/api/projects/{POSTHOG_PROJECT_ID}/feature_flags/"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_ph_headers())
        resp.raise_for_status()
    flags = [
        {"id": f["id"], "key": f["key"],
         "name": f.get("name"), "active": f.get("active", False)}
        for f in resp.json().get("results", [])
    ]
    return json.dumps({"feature_flags": flags}, indent=2, ensure_ascii=False)


@make_tool
def posthog_toggle_feature_flag(
    flag_key: str, active: bool = True
) -> str:
    """Enable or disable a feature flag."""
    url = (
        f"{POSTHOG_HOST}/api/projects/{POSTHOG_PROJECT_ID}"
        f"/feature_flags/{flag_key}/"
    )
    payload = {"active": active}
    with httpx.Client(timeout=15.0) as client:
        resp = client.patch(url, headers=_ph_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps({"flag": flag_key, "active": active})


@make_tool
def posthog_run_query(query: str) -> str:
    """Run a HogQL query against PostHog."""
    url = f"{POSTHOG_HOST}/api/projects/{POSTHOG_PROJECT_ID}/query/"
    payload = {
        "query": {
            "kind": "HogQLQuery",
            "query": query,
        }
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=_ph_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def posthog_list_projects() -> str:
    """List all PostHog projects in the organization."""
    url = f"{POSTHOG_HOST}/api/projects/"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_ph_headers())
        resp.raise_for_status()
    projects = [
        {"id": p["id"], "name": p.get("name")}
        for p in resp.json().get("results", [])
    ]
    return json.dumps({"projects": projects}, indent=2, ensure_ascii=False)


TOOLS = [
    posthog_capture,
    posthog_list_feature_flags,
    posthog_toggle_feature_flag,
    posthog_run_query,
    posthog_list_projects,
]


class PostHogMCPServer(MCPServer):
    name = "posthog"
    description = "PostHog product analytics and feature flags"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["PostHogMCPServer", "TOOLS"]