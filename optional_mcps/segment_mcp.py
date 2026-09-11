"""Segment MCP — customer data platform."""

from __future__ import annotations

import json
import os
import time

import httpx

from optional_mcps.base import MCPServer, make_tool

SEGMENT_WRITE_KEY = os.environ.get("SEGMENT_WRITE_KEY", "")
SEGMENT_BASE_URL = "https://api.segment.io/v1"


def _segment_headers() -> dict[str, str]:
    import base64
    if not SEGMENT_WRITE_KEY:
        raise ValueError("SEGMENT_WRITE_KEY must be set")
    creds = base64.b64encode(
        f"{SEGMENT_WRITE_KEY}:".encode()
    ).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/json",
    }


@make_tool
def segment_track(
    user_id: str,
    event: str,
    properties: str = "{}",
) -> str:
    """Track an event to Segment."""
    url = f"{SEGMENT_BASE_URL}/track"
    payload = {
        "userId": user_id,
        "event": event,
        "properties": json.loads(properties),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.%fZ", time.gmtime()),
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_segment_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps({"status": "tracked", "event": event})


@make_tool
def segment_identify(
    user_id: str,
    traits: str = "{}",
) -> str:
    """Identify a user in Segment."""
    url = f"{SEGMENT_BASE_URL}/identify"
    payload = {
        "userId": user_id,
        "traits": json.loads(traits),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.%fZ", time.gmtime()),
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_segment_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps({"status": "identified", "userId": user_id})


@make_tool
def segment_group(
    user_id: str,
    group_id: str,
    traits: str = "{}",
) -> str:
    """Associate user with a group."""
    url = f"{SEGMENT_BASE_URL}/group"
    payload = {
        "userId": user_id,
        "groupId": group_id,
        "traits": json.loads(traits),
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_segment_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps({"status": "grouped"})


@make_tool
def segment_alias(user_id: str, previous_id: str) -> str:
    """Alias anonymous user with identified user."""
    url = f"{SEGMENT_BASE_URL}/alias"
    payload = {
        "userId": user_id,
        "previousId": previous_id,
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_segment_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps({"status": "aliased"})


@make_tool
def segment_batch(events: str) -> str:
    """Send batch of events to Segment."""
    url = f"{SEGMENT_BASE_URL}/batch"
    payload = {"batch": json.loads(events), "sentAt": time.strftime("%Y-%m-%dT%H:%M:%S.%fZ", time.gmtime())}
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=_segment_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps({"status": "batch_sent"})


TOOLS = [
    segment_track,
    segment_identify,
    segment_group,
    segment_alias,
    segment_batch,
]


class SegmentMCPServer(MCPServer):
    name = "segment"
    description = "Segment customer data platform"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["SegmentMCPServer", "TOOLS"]