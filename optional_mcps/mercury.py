"""Mercury MCP — startup banking API."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

MERCURY_TOKEN = os.environ.get("MERCURY_API_TOKEN", "")
MERCURY_BASE_URL = "https://api.mercury.com/api/v1"


def _mercury_headers() -> dict[str, str]:
    if not MERCURY_TOKEN:
        raise ValueError("MERCURY_API_TOKEN must be set")
    return {
        "Authorization": f"Bearer {MERCURY_TOKEN}",
        "Content-Type": "application/json",
    }


@make_tool
def mercury_list_accounts() -> str:
    """List Mercury accounts."""
    url = f"{MERCURY_BASE_URL}/accounts"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_mercury_headers())
        resp.raise_for_status()
    accounts = [
        {"id": a["id"], "name": a.get("name"),
         "type": a.get("type"), "balance": a.get("currentBalance")}
        for a in resp.json().get("accounts", [])
    ]
    return json.dumps({"accounts": accounts}, indent=2, ensure_ascii=False)


@make_tool
def mercury_list_transactions(
    account_id: str, limit: int = 50
) -> str:
    """List Mercury transactions."""
    url = f"{MERCURY_BASE_URL}/account/{account_id}/transactions"
    params = {"limit": min(limit, 500)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_mercury_headers(), params=params)
        resp.raise_for_status()
    transactions = [
        {"id": t["id"], "amount": t.get("amount"),
         "description": t.get("description"),
         "posted_at": t.get("postedAt")}
        for t in resp.json().get("transactions", [])
    ]
    return json.dumps({"transactions": transactions}, indent=2, ensure_ascii=False)


@make_tool
def mercury_get_balance(account_id: str) -> str:
    """Get current balance for Mercury account."""
    url = f"{MERCURY_BASE_URL}/account/{account_id}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_mercury_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def mercury_create_recipient(
    account_id: str,
    name: str,
    routing_number: str,
    account_number: str,
    account_type: str = "businessChecking",
) -> str:
    """Create a recipient for outgoing payments."""
    url = f"{MERCURY_BASE_URL}/account/{account_id}/recipients"
    payload = {
        "name": name,
        "routingNumber": routing_number,
        "accountNumber": account_number,
        "type": account_type,
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_mercury_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def mercury_list_recipients(account_id: str) -> str:
    """List Mercury recipients."""
    url = f"{MERCURY_BASE_URL}/account/{account_id}/recipients"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_mercury_headers())
        resp.raise_for_status()
    recipients = [
        {"id": r["id"], "name": r.get("name"),
         "routing_number": r.get("routingNumber")}
        for r in resp.json().get("recipients", [])
    ]
    return json.dumps({"recipients": recipients}, indent=2, ensure_ascii=False)


TOOLS = [
    mercury_list_accounts,
    mercury_list_transactions,
    mercury_get_balance,
    mercury_create_recipient,
    mercury_list_recipients,
]


class MercuryMCPServer(MCPServer):
    name = "mercury"
    description = "Mercury startup banking API"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["MercuryMCPServer", "TOOLS"]