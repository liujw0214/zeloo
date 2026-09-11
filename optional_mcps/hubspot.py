"""HubSpot MCP — CRM contacts, deals, and tickets."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

HUBSPOT_TOKEN = os.environ.get("HUBSPOT_ACCESS_TOKEN", "")
HUBSPOT_BASE_URL = "https://api.hubapi.com"


def _hubspot_headers() -> dict[str, str]:
    if not HUBSPOT_TOKEN:
        raise ValueError("HUBSPOT_ACCESS_TOKEN environment variable not set")
    return {
        "Authorization": f"Bearer {HUBSPOT_TOKEN}",
        "Content-Type": "application/json",
    }


@make_tool
def hubspot_list_contacts(
    limit: int = 100,
    after: str = "",
) -> str:
    """List contacts from HubSpot CRM.

    Args:
        limit: Number of contacts to return (max 100).
        after: Pagination cursor for next page.
    """
    url = f"{HUBSPOT_BASE_URL}/crm/v3/objects/contacts"
    params: dict[str, Any] = {"limit": min(limit, 100)}
    if after:
        params["after"] = after
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_hubspot_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def hubspot_create_contact(properties: str) -> str:
    """Create a new contact in HubSpot.

    Args:
        properties: JSON string with contact properties
            (e.g. '{"email":"user@example.com","firstname":"John"}').
    """
    url = f"{HUBSPOT_BASE_URL}/crm/v3/objects/contacts"
    props = json.loads(properties)
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            url,
            headers=_hubspot_headers(),
            json={"properties": props},
        )
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def hubspot_list_deals(
    limit: int = 100,
) -> str:
    """List deals from HubSpot CRM.

    Args:
        limit: Number of deals to return (max 100).
    """
    url = f"{HUBSPOT_BASE_URL}/crm/v3/objects/deals"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_hubspot_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def hubspot_create_ticket(
    subject: str,
    body: str,
    pipeline: str = "default",
    status: str = "OPEN",
) -> str:
    """Create a support ticket in HubSpot.

    Args:
        subject: Ticket subject.
        body: Ticket description.
        pipeline: Pipeline ID.
        status: Ticket status (OPEN, CLOSED).
    """
    url = f"{HUBSPOT_BASE_URL}/crm/v3/objects/tickets"
    properties = {
        "subject": subject,
        "content": body,
        "hs_pipeline": pipeline,
        "hs_ticket_priority": "MEDIUM",
        "hs_pipeline_stage": status,
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            url,
            headers=_hubspot_headers(),
            json={"properties": properties},
        )
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def hubspot_search_contacts(query: str) -> str:
    """Search contacts by name or email.

    Args:
        query: Search query string.
    """
    url = f"{HUBSPOT_BASE_URL}/crm/v3/objects/contacts/search"
    body = {
        "query": query,
        "limit": 20,
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_hubspot_headers(), json=body)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    hubspot_list_contacts,
    hubspot_create_contact,
    hubspot_list_deals,
    hubspot_create_ticket,
    hubspot_search_contacts,
]


class HubSpotMCPServer(MCPServer):
    name = "hubspot"
    description = "HubSpot CRM contacts, deals, and tickets"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["HubSpotMCPServer", "TOOLS"]
