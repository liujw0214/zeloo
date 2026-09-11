"""Zendesk MCP — support tickets and customer management."""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

ZD_SUBDOMAIN = os.environ.get("ZENDESK_SUBDOMAIN", "")
ZD_EMAIL = os.environ.get("ZENDESK_EMAIL", "")
ZD_API_TOKEN = os.environ.get("ZENDESK_API_TOKEN", "")


def _zd_headers() -> dict[str, str]:
    if not ZD_SUBDOMAIN or not ZD_EMAIL or not ZD_API_TOKEN:
        raise ValueError("ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN must be set")
    creds = base64.b64encode(
        f"{ZD_EMAIL}/token:{ZD_API_TOKEN}".encode()
    ).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/json",
    }


@make_tool
def zendesk_list_tickets(
    status: str = "open",
    limit: int = 25,
) -> str:
    """List Zendesk support tickets.

    Args:
        status: Ticket status (new, open, pending, hold, solved, closed).
        limit: Number of tickets to return.
    """
    url = f"https://{ZD_SUBDOMAIN}.zendesk.com/api/v2/tickets.json"
    params = {"status": status, "per_page": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_zd_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def zendesk_get_ticket(ticket_id: int) -> str:
    """Get a specific Zendesk ticket.

    Args:
        ticket_id: The ticket ID.
    """
    url = f"https://{ZD_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_zd_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def zendesk_create_ticket(
    subject: str,
    body: str,
    requester_email: str,
    priority: str = "normal",
    tags: str = "",
) -> str:
    """Create a new Zendesk support ticket.

    Args:
        subject: Ticket subject.
        body: Ticket description.
        requester_email: Requester's email address.
        priority: Priority (low, normal, high, urgent).
        tags: Comma-separated tags.
    """
    url = f"https://{ZD_SUBDOMAIN}.zendesk.com/api/v2/tickets.json"
    ticket_data: dict[str, Any] = {
        "ticket": {
            "subject": subject,
            "comment": {"body": body},
            "requester": {"email": requester_email},
            "priority": priority,
        }
    }
    if tags:
        ticket_data["ticket"]["tags"] = [t.strip() for t in tags.split(",")]
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_zd_headers(), json=ticket_data)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def zendesk_list_users(
    role: str = "",
    limit: int = 25,
) -> str:
    """List Zendesk users.

    Args:
        role: Filter by role (end-user, agent, admin).
        limit: Number of users to return.
    """
    url = f"https://{ZD_SUBDOMAIN}.zendesk.com/api/v2/users.json"
    params: dict[str, Any] = {"per_page": min(limit, 100)}
    if role:
        params["role"] = role
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_zd_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    zendesk_list_tickets,
    zendesk_get_ticket,
    zendesk_create_ticket,
    zendesk_list_users,
]


class ZendeskMCPServer(MCPServer):
    name = "zendesk"
    description = "Zendesk support tickets and customer management"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["ZendeskMCPServer", "TOOLS"]
