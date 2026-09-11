"""Mixpanel MCP — product analytics platform."""

from __future__ import annotations

import json
import os
import time

import httpx

from optional_mcps.base import MCPServer, make_tool

MIXPANEL_TOKEN = os.environ.get("MIXPANEL_API_TOKEN", "")
MIXPANEL_PROJECT = os.environ.get("MIXPANEL_PROJECT_ID", "")
MIXPANEL_BASE_URL = "https://mixpanel.com/api/2.0"


def _mp_headers() -> dict[str, str]:
    if not MIXPANEL_TOKEN:
        raise ValueError("MIXPANEL_API_TOKEN must be set")
    return {
        "Authorization": f"Bearer {MIXPANEL_TOKEN}",
        "Accept": "application/json",
    }


@make_tool
def mixpanel_track_event(
    event: str,
    distinct_id: str,
    properties: str = "{}",
) -> str:
    """Track an event to Mixpanel."""
    url = f"{MIXPANEL_BASE_URL}/track"
    payload = {
        "event": event,
        "properties": {
            "token": MIXPANEL_TOKEN,
            "distinct_id": distinct_id,
            "time": int(time.time()),
            **json.loads(properties),
        },
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_mp_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps({"status": "tracked", "event": event}, indent=2)


@make_tool
def mixpanel_segment_query(
    event: str,
    from_date: str,
    to_date: str,
    unit: str = "day",
) -> str:
    """Run a segmentation query on Mixpanel."""
    url = f"{MIXPANEL_BASE_URL}/segmentation"
    payload = {
        "event": event,
        "from_date": from_date,
        "to_date": to_date,
        "unit": unit,
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=_mp_headers(), params=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def mixpanel_funnel_query(
    events: str,
    from_date: str,
    to_date: str,
) -> str:
    """Run funnel analysis on Mixpanel.

    Args:
        events: Comma-separated event names in funnel order.
        from_date: Start date (YYYY-MM-DD).
        to_date: End date (YYYY-MM-DD).
    """
    url = f"{MIXPANEL_BASE_URL}/funnels"
    payload = {
        "funnel_id": None,
        "events": json.loads(events),
        "from_date": from_date,
        "to_date": to_date,
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=_mp_headers(), params=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def mixpanel_retention_query(
    event: str,
    born_event: str = "$born",
    from_date: str = "",
    to_date: str = "",
) -> str:
    """Run retention analysis on Mixpanel."""
    url = f"{MIXPANEL_BASE_URL}/retention"
    payload = {
        "event": event,
        "born_event": born_event,
    }
    if from_date:
        payload["from_date"] = from_date
    if to_date:
        payload["to_date"] = to_date
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=_mp_headers(), params=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def mixpanel_list_cohorts() -> str:
    """List all Mixpanel cohorts."""
    url = f"{MIXPANEL_BASE_URL}/cohorts/list"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_mp_headers())
        resp.raise_for_status()
    cohorts = resp.json()
    return json.dumps({"cohorts": cohorts}, indent=2, ensure_ascii=False)


TOOLS = [
    mixpanel_track_event,
    mixpanel_segment_query,
    mixpanel_funnel_query,
    mixpanel_retention_query,
    mixpanel_list_cohorts,
]


class MixpanelMCPServer(MCPServer):
    name = "mixpanel"
    description = "Mixpanel product analytics"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["MixpanelMCPServer", "TOOLS"]