"""Pipedrive CRM MCP — deals, contacts, and pipeline management."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

PIPEDRIVE_TOKEN = os.environ.get("PIPEDRIVE_API_TOKEN", "")
PIPEDRIVE_DOMAIN = os.environ.get("PIPEDRIVE_DOMAIN", "api.pipedrive.com/v1")


def _pd_headers() -> dict[str, str]:
    if not PIPEDRIVE_TOKEN:
        raise ValueError("PIPEDRIVE_API_TOKEN must be set")
    return {"Authorization": f"Bearer {PIPEDRIVE_TOKEN}"}


@make_tool
def pipedrive_list_deals(
    stage_id: int = 0,
    status: str = "open",
    limit: int = 50,
) -> str:
    """List Pipedrive deals.

    Args:
        stage_id: Filter by pipeline stage (0 = all).
        status: open, won, lost, all.
        limit: Number of deals.
    """
    url = f"https://{PIPEDRIVE_DOMAIN}/deals"
    params = {
        "limit": min(limit, 500),
        "status": status,
    }
    if stage_id:
        params["stage_id"] = stage_id
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_pd_headers(), params=params)
        resp.raise_for_status()
    data = resp.json()
    deals = [
        {"id": d["id"], "title": d["title"],
         "value": d.get("value"), "status": d.get("status")}
        for d in data.get("data", [])
    ]
    return json.dumps({"deals": deals, "count": data.get("additional_data", {}).get("pagination", {}).get("total", 0)}, indent=2, ensure_ascii=False)


@make_tool
def pipedrive_get_deal(deal_id: int) -> str:
    """Get Pipedrive deal details."""
    url = f"https://{PIPEDRIVE_DOMAIN}/deals/{deal_id}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_pd_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def pipedrive_list_persons(limit: int = 50) -> str:
    """List Pipedrive contacts (persons)."""
    url = f"https://{PIPEDRIVE_DOMAIN}/persons"
    params = {"limit": min(limit, 500)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_pd_headers(), params=params)
        resp.raise_for_status()
    data = resp.json()
    persons = [
        {"id": p["id"], "name": p.get("name"),
         "email": p.get("emails", [{}])[0].get("value", "")}
        for p in data.get("data", [])
    ]
    return json.dumps({"persons": persons}, indent=2, ensure_ascii=False)


@make_tool
def pipedrive_create_deal(
    title: str,
    person_name: str = "",
    value: float = 0.0,
    stage_id: int = 1,
) -> str:
    """Create a Pipedrive deal.

    Args:
        title: Deal title.
        person_name: Contact person name.
        value: Deal value.
        stage_id: Pipeline stage.
    """
    url = f"https://{PIPEDRIVE_DOMAIN}/deals"
    payload: dict[str, Any] = {"title": title, "stage_id": stage_id}
    if person_name:
        payload["person_name"] = person_name
    if value:
        payload["value"] = value
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_pd_headers(), json=payload)
        resp.raise_for_status()
    deal = resp.json().get("data", {})
    return json.dumps({"id": deal.get("id"), "title": deal.get("title")}, indent=2)


@make_tool
def pipedrive_list_pipelines() -> str:
    """List Pipedrive pipelines and stages."""
    url = f"https://{PIPEDRIVE_DOMAIN}/pipelines"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_pd_headers())
        resp.raise_for_status()
    pipelines = [
        {"id": p["id"], "name": p["name"],
         "stages": [
             {"id": s["id"], "name": s["name"]}
             for s in p.get("stages", [])
         ]}
        for p in resp.json().get("data", [])
    ]
    return json.dumps({"pipelines": pipelines}, indent=2, ensure_ascii=False)


TOOLS = [
    pipedrive_list_deals,
    pipedrive_get_deal,
    pipedrive_list_persons,
    pipedrive_create_deal,
    pipedrive_list_pipelines,
]


class PipedriveMCPServer(MCPServer):
    name = "pipedrive"
    description = "Pipedrive CRM deals, contacts, and pipelines"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["PipedriveMCPServer", "TOOLS"]
