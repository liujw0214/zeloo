"""Strava MCP — athlete activities and segments."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

STRAVA_CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID", "")
STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET", "")
STRAVA_REFRESH_TOKEN = os.environ.get("STRAVA_REFRESH_TOKEN", "")


def _get_strava_token() -> str:
    if not STRAVA_CLIENT_ID:
        raise ValueError("STRAVA_CLIENT_ID not set")
    resp = httpx.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "refresh_token": STRAVA_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _strava_headers() -> dict[str, str]:
    token = _get_strava_token()
    return {"Authorization": f"Bearer {token}"}


@make_tool
def strava_list_activities(limit: int = 30) -> str:
    """List recent Strava activities."""
    url = "https://www.strava.com/api/v3/athlete/activities"
    params = {"per_page": min(limit, 200)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_strava_headers(), params=params)
        resp.raise_for_status()
    activities = [
        {"id": a["id"], "name": a["name"],
         "type": a["type"], "distance": a.get("distance"),
         "moving_time": a.get("moving_time"),
         "elapsed_time": a.get("elapsed_time")}
        for a in resp.json()
    ]
    return json.dumps({"activities": activities}, indent=2, ensure_ascii=False)


@make_tool
def strava_get_activity(activity_id: int) -> str:
    """Get Strava activity details."""
    url = f"https://www.strava.com/api/v3/activities/{activity_id}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_strava_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def strava_list_zones() -> str:
    """List activity power/heart rate zones."""
    url = "https://www.strava.com/api/v3/athlete/zones"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_strava_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def strava_list_clubs() -> str:
    """List athlete's clubs."""
    url = "https://www.strava.com/api/v3/athlete/clubs"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_strava_headers())
        resp.raise_for_status()
    clubs = [
        {"id": c["id"], "name": c["name"], "sport_type": c.get("sport_type")}
        for c in resp.json()
    ]
    return json.dumps({"clubs": clubs}, indent=2, ensure_ascii=False)


@make_tool
def strava_list_gear(gear_id: str) -> str:
    """Get gear (bike/running shoe) details."""
    url = f"https://www.strava.com/api/v3/gear/{gear_id}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_strava_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    strava_list_activities,
    strava_get_activity,
    strava_list_zones,
    strava_list_clubs,
    strava_list_gear,
]


class StravaMCPServer(MCPServer):
    name = "strava"
    description = "Strava athlete activities and segments"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["StravaMCPServer", "TOOLS"]
