"""PagerDuty MCP — on-call alerts and incident management."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

PAGERDUTY_TOKEN = os.environ.get("PAGERDUTY_TOKEN", "")
PAGERDUTY_BASE_URL = "https://api.pagerduty.com"


def _pd_headers() -> dict[str, str]:
    if not PAGERDUTY_TOKEN:
        raise ValueError("PAGERDUTY_TOKEN environment variable not set")
    return {
        "Authorization": f"Token token={PAGERDUTY_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.pagerduty+json;version=2",
    }


@make_tool
def pagerduty_list_incidents(
    limit: int = 25,
    status: str = "triggered",
) -> str:
    """List incidents in PagerDuty.

    Args:
        limit: Number of incidents to return.
        status: Filter by status (triggered, acknowledged, resolved).
    """
    url = f"{PAGERDUTY_BASE_URL}/incidents"
    params = {"limit": min(limit, 100), "statuses[]": status}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_pd_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def pagerduty_get_incident(incident_id: str) -> str:
    """Get a specific incident by ID.

    Args:
        incident_id: The incident ID.
    """
    url = f"{PAGERDUTY_BASE_URL}/incidents/{incident_id}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_pd_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def pagerduty_list_oncall() -> str:
    """List current on-call users and escalation policies."""
    url = f"{PAGERDUTY_BASE_URL}/oncalls"
    params = {"time_zone": "UTC", "include": ["users", "escalation_policies"]}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_pd_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def pagerduty_manage_incident(
    incident_id: str,
    action: str,
    user_id: str = "",
) -> str:
    """Manage an incident (acknowledge, escalate, resolve).

    Args:
        incident_id: The incident ID.
        action: Action to take (acknowledge, escalate, resolve).
        user_id: User ID to assign/notify.
    """
    url = f"{PAGERDUTY_BASE_URL}/incidents/{incident_id}"
    body: dict[str, Any] = {"incident": {"type": "incident_reference"}}
    if action == "acknowledge":
        body["incident"]["status"] = "acknowledged"
    elif action == "resolve":
        body["incident"]["status"] = "resolved"
    if user_id:
        body["incident"]["assigned_to_user"] = {"id": user_id, "type": "user_reference"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.put(url, headers=_pd_headers(), json=body)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def pagerduty_list_services() -> str:
    """List all services in PagerDuty."""
    url = f"{PAGERDUTY_BASE_URL}/services"
    params = {"limit": 100}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_pd_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    pagerduty_list_incidents,
    pagerduty_get_incident,
    pagerduty_list_oncall,
    pagerduty_manage_incident,
    pagerduty_list_services,
]


class PagerDutyMCPServer(MCPServer):
    name = "pagerduty"
    description = "PagerDuty on-call alerts and incident management"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["PagerDutyMCPServer", "TOOLS"]
