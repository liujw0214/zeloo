"""FreshBooks MCP — invoicing and accounting."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

FB_CLIENT_ID = os.environ.get("FRESHBOOKS_CLIENT_ID", "")
FB_CLIENT_SECRET = os.environ.get("FRESHBOOKS_CLIENT_SECRET", "")
FB_REFRESH_TOKEN = os.environ.get("FRESHBOOKS_REFRESH_TOKEN", "")
FB_ACCOUNT_ID = os.environ.get("FRESHBOOKS_ACCOUNT_ID", "")
FB_BASE_URL = "https://api.freshbooks.com"


def _get_fb_token() -> str:
    if not FB_CLIENT_ID:
        raise ValueError("FRESHBOOKS_CLIENT_ID must be set")
    resp = httpx.post(
        "https://api.freshbooks.com/auth/oauth/token",
        json={
            "grant_type": "refresh_token",
            "client_id": FB_CLIENT_ID,
            "client_secret": FB_CLIENT_SECRET,
            "refresh_token": FB_REFRESH_TOKEN,
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _fb_headers() -> dict[str, str]:
    token = _get_fb_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


@make_tool
def freshbooks_list_clients(limit: int = 50) -> str:
    """List FreshBooks clients."""
    url = f"{FB_BASE_URL}/api/accounting/account/{FB_ACCOUNT_ID}/users/clients"
    params = {"per_page": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_fb_headers(), params=params)
        resp.raise_for_status()
    clients = [
        {"id": c["id"], "email": c.get("email"),
         "organization": c.get("organization")}
        for c in resp.json().get("response", {}).get("result", {}).get("clients", [])
    ]
    return json.dumps({"clients": clients}, indent=2, ensure_ascii=False)


@make_tool
def freshbooks_list_invoices(limit: int = 30) -> str:
    """List FreshBooks invoices."""
    url = f"{FB_BASE_URL}/api/accounting/account/{FB_ACCOUNT_ID}/invoices"
    params = {"per_page": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_fb_headers(), params=params)
        resp.raise_for_status()
    invoices = [
        {"id": i["id"], "number": i.get("invoice_number"),
         "amount": i.get("amount"), "status": i.get("status")}
        for i in resp.json().get("response", {}).get("result", {}).get("invoices", [])
    ]
    return json.dumps({"invoices": invoices}, indent=2, ensure_ascii=False)


@make_tool
def freshbooks_create_invoice(
    client_id: int,
    amount: float,
    description: str = "",
) -> str:
    """Create a FreshBooks invoice."""
    url = f"{FB_BASE_URL}/api/accounting/account/{FB_ACCOUNT_ID}/invoices"
    payload = {
        "client_id": client_id,
        "lines": [{
            "amount": amount,
            "description": description or "Service",
            "qty": 1,
            "unit_cost": amount,
        }],
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_fb_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def freshbooks_list_payments() -> str:
    """List FreshBooks payments."""
    url = f"{FB_BASE_URL}/api/accounting/account/{FB_ACCOUNT_ID}/payments"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_fb_headers())
        resp.raise_for_status()
    payments = [
        {"id": p["id"], "amount": p.get("amount"),
         "date": p.get("date"), "client_id": p.get("client_id")}
        for p in resp.json().get("response", {}).get("result", {}).get("payments", [])
    ]
    return json.dumps({"payments": payments}, indent=2, ensure_ascii=False)


@make_tool
def freshbooks_list_expenses() -> str:
    """List FreshBooks expenses."""
    url = f"{FB_BASE_URL}/api/accounting/account/{FB_ACCOUNT_ID}/expenses"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_fb_headers())
        resp.raise_for_status()
    expenses = [
        {"id": e["id"], "amount": e.get("amount"),
         "category": e.get("category"), "date": e.get("date")}
        for e in resp.json().get("response", {}).get("result", {}).get("expenses", [])
    ]
    return json.dumps({"expenses": expenses}, indent=2, ensure_ascii=False)


TOOLS = [
    freshbooks_list_clients,
    freshbooks_list_invoices,
    freshbooks_create_invoice,
    freshbooks_list_payments,
    freshbooks_list_expenses,
]


class FreshBooksMCPServer(MCPServer):
    name = "freshbooks"
    description = "FreshBooks invoicing and accounting"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["FreshBooksMCPServer", "TOOLS"]