"""Resend MCP — email sending and management via Resend API."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_BASE_URL = "https://api.resend.com"


def _resend_headers() -> dict[str, str]:
    if not RESEND_API_KEY:
        raise ValueError("RESEND_API_KEY environment variable not set")
    return {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }


@make_tool
def resend_send_email(
    from_address: str,
    to_address: str,
    subject: str,
    html: str | None = None,
    text: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    reply_to: str | None = None,
) -> str:
    """Send an email via Resend.

    Args:
        from_address: Sender email address (must be verified).
        to_address: Recipient email address.
        subject: Email subject line.
        html: Optional HTML body.
        text: Optional plain text body.
        cc: Optional CC recipient(s), comma-separated.
        bcc: Optional BCC recipient(s), comma-separated.
        reply_to: Optional Reply-To address.
    """
    url = f"{RESEND_BASE_URL}/emails"
    payload: dict[str, Any] = {
        "from": from_address,
        "to": [to_address],
        "subject": subject,
    }
    if html:
        payload["html"] = html
    if text:
        payload["text"] = text
    if cc:
        payload["cc"] = [x.strip() for x in cc.split(",")]
    if bcc:
        payload["bcc"] = [x.strip() for x in bcc.split(",")]
    if reply_to:
        payload["reply_to"] = reply_to

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=_resend_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def resend_list_domains() -> str:
    """List all verified domains in your Resend account."""
    url = f"{RESEND_BASE_URL}/domains"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_resend_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def resend_get_audit_logs(
    limit: int = 50,
    start_date: str | None = None,
) -> str:
    """Get Resend audit logs.

    Args:
        limit: Maximum number of log entries to return.
        start_date: Optional ISO date string to filter from.
    """
    url = f"{RESEND_BASE_URL}/audit_logs"
    params: dict[str, Any] = {"limit": limit}
    if start_date:
        params["start_date"] = start_date
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_resend_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    resend_send_email,
    resend_list_domains,
    resend_get_audit_logs,
]


class ResendMCPServer(MCPServer):
    name = "resend"
    description = "Resend email API integration"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["ResendMCPServer", "TOOLS"]
