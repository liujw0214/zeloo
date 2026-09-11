"""Freshdesk MCP — customer support and helpdesk."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

FRESHDESK_DOMAIN = os.environ.get("FRESHDESK_DOMAIN", "")
FRESHDESK_KEY = os.environ.get("FRESHDESK_API_KEY", "")


def _fd_headers() -> dict[str, str]:
    if not FRESHDESK_DOMAIN or not FRESHDESK_KEY:
        raise ValueError("FRESHDESK_DOMAIN and FRESHDESK_API_KEY must be set")
    return {
        "Content-Type": "application/json",
    }


@make_tool
def freshdesk_list_tickets(
    status_id: int = 2,
    limit: int = 30,
) -> str:
    """List Freshdesk tickets.

    Args:
        status_id: 1=Open, 2=Pend, 3=resolved, 4=closed.
        limit: Number of tickets.
    """
    url = (
        f"https://{FRESHDESK_DOMAIN}.freshdesk.com/api/v2/tickets"
    )
    params = {"per_page": min(limit, 100), "status_id": status_id}
    auth = (FRESHDESK_KEY, "X")
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, auth=auth, params=params)
        resp.raise_for_status()
    tickets = [
        {"id": t["id"], "subject": t["subject"],
         "status": t["status"], "priority": t["priority"]}
        for t in resp.json()
    ]
    return json.dumps({"tickets": tickets, "count": len(tickets)}, indent=2)


@make_tool
def freshdesk_create_ticket(
    subject: str,
    description: str,
    email: str,
    priority: int = 2,
    status: int = 2,
) -> str:
    """Create a Freshdesk ticket.

    Args:
        subject: Ticket subject.
        description: Ticket body.
        email: Requester email.
        priority: 1=low, 2=medium, 3=high, 4=urgent.
        status: 2=open.
    """
    url = (
        f"https://{FRESHDESK_DOMAIN}.freshdesk.com/api/v2/tickets"
    )
    payload = {
        "subject": subject,
        "description": description,
        "email": email,
        "priority": priority,
        "status": status,
    }
    auth = (FRESHDESK_KEY, "X")
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, auth=auth, json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@make_tool
def freshdesk_get_ticket(ticket_id: int) -> str:
    """Get Freshdesk ticket details."""
    url = (
        f"https://{FRESHDESK_DOMAIN}.freshdesk.com/api/v2/tickets/{ticket_id}"
    )
    auth = (FRESHDESK_KEY, "X")
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, auth=auth)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@make_tool
def freshdesk_list_groups() -> str:
    """List Freshdesk support groups."""
    url = (
        f"https://{FRESHDESK_DOMAIN}.freshdesk.com/api/v2/groups"
    )
    auth = (FRESHDESK_KEY, "X")
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, auth=auth)
        resp.raise_for_status()
    groups = [
        {"id": g["id"], "name": g["name"]}
        for g in resp.json()
    ]
    return json.dumps({"groups": groups}, indent=2)


@make_tool
def freshdesk_list_agents(limit: int = 50) -> str:
    """List Freshdesk agents."""
    url = (
        f"https://{FRESHDESK_DOMAIN}.freshdesk.com/api/v2/agents"
    )
    params = {"per_page": min(limit, 100)}
    auth = (FRESHDESK_KEY, "X")
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, auth=auth, params=params)
        resp.raise_for_status()
    agents = [
        {"id": a["id"], "name": a["contact"]["name"], "email": a["contact"]["email"]}
        for a in resp.json()
    ]
    return json.dumps({"agents": agents}, indent=2)


TOOLS = [
    freshdesk_list_tickets,
    freshdesk_create_ticket,
    freshdesk_get_ticket,
    freshdesk_list_groups,
    freshdesk_list_agents,
]


class FreshdeskMCPServer(MCPServer):
    name = "freshdesk"
    description = "Freshdesk customer support and helpdesk"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["FreshdeskMCPServer", "TOOLS"]
