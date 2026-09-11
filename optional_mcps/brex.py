"""Brex MCP — corporate cards and expenses."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

BREX_TOKEN = os.environ.get("BREX_API_TOKEN", "")
BREX_BASE_URL = "https://platform.brexapis.com/v1"


def _brex_headers() -> dict[str, str]:
    if not BREX_TOKEN:
        raise ValueError("BREX_API_TOKEN must be set")
    return {
        "Authorization": f"Bearer {BREX_TOKEN}",
        "Content-Type": "application/json",
    }


@make_tool
def brex_list_cards(limit: int = 50) -> str:
    """List Brex cards."""
    url = f"{BREX_BASE_URL}/cards"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_brex_headers(), params=params)
        resp.raise_for_status()
    cards = [
        {"id": c["id"], "last_four": c.get("last_four"),
         "status": c.get("status"), "type": c.get("card_type")}
        for c in resp.json().get("items", [])
    ]
    return json.dumps({"cards": cards}, indent=2, ensure_ascii=False)


@make_tool
def brex_get_card_transactions(
    card_id: str, limit: int = 50
) -> str:
    """Get transactions for a Brex card."""
    url = f"{BREX_BASE_URL}/cards/{card_id}/transactions"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_brex_headers(), params=params)
        resp.raise_for_status()
    transactions = [
        {"id": t["id"], "amount": t.get("amount"),
         "merchant": t.get("merchant"), "date": t.get("posted_at")}
        for t in resp.json().get("items", [])
    ]
    return json.dumps({"transactions": transactions}, indent=2, ensure_ascii=False)


@make_tool
def brex_list_expenses(limit: int = 50) -> str:
    """List Brex expenses."""
    url = f"{BREX_BASE_URL}/expenses"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_brex_headers(), params=params)
        resp.raise_for_status()
    expenses = [
        {"id": e["id"], "amount": e.get("amount"),
         "category": e.get("category"), "status": e.get("status")}
        for e in resp.json().get("items", [])
    ]
    return json.dumps({"expenses": expenses}, indent=2, ensure_ascii=False)


@make_tool
def brex_freeze_card(card_id: str) -> str:
    """Freeze a Brex card."""
    url = f"{BREX_BASE_URL}/cards/{card_id}/freeze"
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_brex_headers())
        resp.raise_for_status()
    return json.dumps({"status": "frozen"})


@make_tool
def brex_get_reimbursements(limit: int = 50) -> str:
    """List Brex reimbursements."""
    url = f"{BREX_BASE_URL}/reimbursements"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_brex_headers(), params=params)
        resp.raise_for_status()
    items = [
        {"id": i["id"], "amount": i.get("amount"),
         "status": i.get("status"), "user_id": i.get("user_id")}
        for i in resp.json().get("items", [])
    ]
    return json.dumps({"reimbursements": items}, indent=2, ensure_ascii=False)


TOOLS = [
    brex_list_cards,
    brex_get_card_transactions,
    brex_list_expenses,
    brex_freeze_card,
    brex_get_reimbursements,
]


class BrexMCPServer(MCPServer):
    name = "brex"
    description = "Brex corporate cards and expenses"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["BrexMCPServer", "TOOLS"]