"""Amplitude MCP — product analytics platform."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

AMP_API_KEY = os.environ.get("AMPLITUDE_API_KEY", "")
AMP_SECRET = os.environ.get("AMPLITUDE_SECRET_KEY", "")
AMP_BASE_URL = "https://amplitude.com/api/2"


def _amp_headers() -> dict[str, str]:
    if not AMP_API_KEY or not AMP_SECRET:
        raise ValueError("AMPLITUDE_API_KEY and AMPLITUDE_SECRET_KEY must be set")
    import base64
    creds = base64.b64encode(
        f"{AMP_API_KEY}:{AMP_SECRET}".encode()
    ).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/json",
    }


@make_tool
def amplitude_track_event(
    user_id: str,
    event_type: str,
    properties: str = "{}",
) -> str:
    """Track an event to Amplitude."""
    url = f"{AMP_BASE_URL}/events"
    payload = [
        {
            "user_id": user_id,
            "event_type": event_type,
            "event_properties": json.loads(properties),
            "time": int(time.time() * 1000),
        }
    ]
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_amp_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps({"status": "tracked", "event": event_type})


@make_tool
def amplitude_get_events(
    start: str, end: str, event: str = ""
) -> str:
    """Query Amplitude events."""
    url = f"{AMP_BASE_URL}/events/segmentation"
    payload = {
        "start": start,
        "end": end,
        "event_type": event or None,
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=_amp_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def amplitude_funnel_analysis(
    start: str, end: str, funnel_events: str
) -> str:
    """Run Amplitude funnel analysis.

    Args:
        funnel_events: Comma-separated event names.
    """
    url = f"{AMP_BASE_URL}/funnels"
    events = json.loads(funnel_events)
    payload = {
        "start": start,
        "end": end,
        "events": [{"event_type": e} for e in events],
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=_amp_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def amplitude_user_search(
    user_id: str = "",
    amplitude_id: int = 0,
) -> str:
    """Search Amplitude user activity."""
    url = f"{AMP_BASE_URL}/useractivity"
    payload: dict[str, Any] = {}
    if user_id:
        payload["user_id"] = user_id
    if amplitude_id:
        payload["amplitude_id"] = amplitude_id
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_amp_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def amplitude_list_cohorts() -> str:
    """List Amplitude cohorts."""
    url = f"{AMP_BASE_URL}/cohorts"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_amp_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    amplitude_track_event,
    amplitude_get_events,
    amplitude_funnel_analysis,
    amplitude_user_search,
    amplitude_list_cohorts,
]


class AmplitudeMCPServer(MCPServer):
    name = "amplitude"
    description = "Amplitude product analytics"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["AmplitudeMCPServer", "TOOLS"]