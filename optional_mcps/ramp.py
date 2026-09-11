"""Ramp MCP — corporate cards and spend management."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

RAMP_TOKEN = os.environ.get("RAMP_API_KEY", "")
RAMP_BASE_URL = "https://api.ramp.com/v1"


def _ramp_headers() -> dict[str, str]:
    if not RAMP_TOKEN:
        raise ValueError("RAMP_API_KEY must be set")
    return {
        "Authorization": f"Bearer {RAMP_TOKEN}",
        "Content-Type": "application/json",
    }


@make_tool
def ramp_list_cards(limit: int = 50) -> str:
    """List Ramp cards."""
    url = f"{RAMP_BASE_URL}/cards"
    params = {"page_size": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_ramp_headers(), params=params)
        resp.raise_for_status()
    cards = [
        {"id": c["id"], "last_four": c.get("last_four"),
         "holder_id": c.get("card_holder_id"), "state": c.get("state")}
        for c in resp.json().get("data", [])
    ]
    return json.dumps({"cards": cards}, indent=2, ensure_ascii=False)


@make_tool
def ramp_list_transactions(
    card_id: str = "",
    limit: int = 50,
) -> str:
    """List Ramp transactions."""
    url = f"{RAMP_BASE_URL}/transactions"
    params = {"page_size": min(limit, 100)}
    if card_id:
        params["card_id"] = card_id
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_ramp_headers(), params=params)
        resp.raise_for_status()
    transactions = [
        {"id": t["id"], "amount": t.get("amount"),
         "merchant": t.get("merchant_name"),
         "date": t.get("posted_at")}
        for t in resp.json().get("data", [])
    ]
    return json.dumps({"transactions": transactions}, indent=2, ensure_ascii=False)


@make_tool
def ramp_list_reimbursements(limit: int = 50) -> str:
    """List Ramp reimbursements."""
    url = f"{RAMP_BASE_URL}/reimbursements"
    params = {"page_size": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_ramp_headers(), params=params)
        resp.raise_for_status()
    reimbursements = [
        {"id": r["id"], "amount": r.get("amount"),
         "state": r.get("state"), "user_id": r.get("user_id")}
        for r in resp.json().get("data", [])
    ]
    return json.dumps({"reimbursements": reimbursements}, indent=2, ensure_ascii=False)


@make_tool
def ramp_list_bills(limit: int = 50) -> str:
    """List Ramp bills (AP)."""
    url = f"{RAMP_BASE_URL}/bills"
    params = {"page_size": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_ramp_headers(), params=params)
        resp.raise_for_status()
    bills = [
        {"id": b["id"], "amount": b.get("amount"),
         "vendor": b.get("vendor_name"), "state": b.get("state")}
        for b in resp.json().get("data", [])
    ]
    return json.dumps({"bills": bills}, indent=2, ensure_ascii=False)


@make_tool
def ramp_list_departments() -> str:
    """List Ramp departments."""
    url = f"{RAMP_BASE_URL}/departments"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_ramp_headers())
        resp.raise_for_status()
    departments = [
        {"id": d["id"], "name": d.get("name")}
        for d in resp.json().get("data", [])
    ]
    return json.dumps({"departments": departments}, indent=2, ensure_ascii=False)


TOOLS = [
    ramp_list_cards,
    ramp_list_transactions,
    ramp_list_reimbursements,
    ramp_list_bills,
    ramp_list_departments,
]


class RampMCPServer(MCPServer):
    name = "ramp"
    description = "Ramp corporate cards and spend management"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["RampMCPServer", "TOOLS"]