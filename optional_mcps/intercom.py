"""Intercom MCP — customer messaging and support."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

INTERCOM_TOKEN = os.environ.get("INTERCOM_ACCESS_TOKEN", "")
INTERCOM_BASE_URL = "https://api.intercom.io"


def _intercom_headers() -> dict[str, str]:
    if not INTERCOM_TOKEN:
        raise ValueError("INTERCOM_ACCESS_TOKEN environment variable not set")
    return {
        "Authorization": f"Bearer {INTERCOM_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@make_tool
def intercom_list_conversations(
    limit: int = 25,
    state: str = "open",
) -> str:
    """List conversations in Intercom.

    Args:
        limit: Number of conversations to return.
        state: Filter by state (open, closed, snoozed).
    """
    url = f"{INTERCOM_BASE_URL}/conversations"
    params = {"per_page": min(limit, 150), "state": state}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_intercom_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def intercom_get_conversation(conversation_id: int) -> str:
    """Get a specific conversation by ID.

    Args:
        conversation_id: The conversation ID.
    """
    url = f"{INTERCOM_BASE_URL}/conversations/{conversation_id}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_intercom_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def intercom_list_contacts(
    limit: int = 25,
) -> str:
    """List contacts in Intercom.

    Args:
        limit: Number of contacts to return.
    """
    url = f"{INTERCOM_BASE_URL}/contacts"
    params = {"per_page": min(limit, 150)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_intercom_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def intercom_send_message(
    message_type: str,
    body: str,
    to_email: str | None = None,
    to_user_id: str | None = None,
    subject: str = "",
) -> str:
    """Send a message via Intercom.

    Args:
        message_type: Message type (chat, email, in_app, twitter).
        body: Message body content.
        to_email: Recipient email address.
        to_user_id: Recipient user ID.
        subject: Subject line (for email type).
    """
    url = f"{INTERCOM_BASE_URL}/messages"
    payload: dict[str, Any] = {
        "message_type": message_type,
        "body": body,
    }
    if to_email:
        payload["to"] = {"type": "user", "email": to_email}
    elif to_user_id:
        payload["to"] = {"type": "user", "id": to_user_id}
    if message_type == "email" and subject:
        payload["subject"] = subject
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_intercom_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def intercom_list_admins() -> str:
    """List all admins in Intercom workspace."""
    url = f"{INTERCOM_BASE_URL}/admins"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_intercom_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    intercom_list_conversations,
    intercom_get_conversation,
    intercom_list_contacts,
    intercom_send_message,
    intercom_list_admins,
]


class IntercomMCPServer(MCPServer):
    name = "intercom"
    description = "Intercom customer messaging and support"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["IntercomMCPServer", "TOOLS"]
