"""Plaid MCP — banking and financial data."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

PLAID_CLIENT_ID = os.environ.get("PLAID_CLIENT_ID", "")
PLAID_SECRET = os.environ.get("PLAID_SECRET", "")
PLAID_ENV = os.environ.get("PLAID_ENV", "sandbox")


def _plaid_url() -> str:
    if PLAID_ENV == "production":
        return "https://production.plaid.com"
    if PLAID_ENV == "development":
        return "https://development.plaid.com"
    return "https://sandbox.plaid.com"


def _plaid_post(path: str, body: dict) -> dict:
    if not PLAID_CLIENT_ID:
        raise ValueError("PLAID_CLIENT_ID must be set")
    payload = {
        "client_id": PLAID_CLIENT_ID,
        "secret": PLAID_SECRET,
        **body,
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            f"{_plaid_url()}{path}",
            json=payload,
        )
        resp.raise_for_status()
    return resp.json()


@make_tool
def plaid_create_link_token(user_id: str) -> str:
    """Create a Plaid Link token for user."""
    data = _plaid_post(
        "/link/token/create",
        {
            "user": {"client_user_id": user_id},
            "client_name": "Zeloo Agent",
            "products": ["transactions"],
            "country_codes": ["US"],
            "language": "en",
        },
    )
    return json.dumps({"link_token": data.get("link_token")}, indent=2)


@make_tool
def plaid_get_accounts(access_token: str) -> str:
    """Get accounts for a Plaid item."""
    data = _plaid_post(
        "/accounts/get",
        {"access_token": access_token},
    )
    accounts = [
        {
            "account_id": a["account_id"],
            "name": a["name"],
            "type": a["type"],
            "subtype": a["subtype"],
            "balance": a["balances"].get("current"),
        }
        for a in data.get("accounts", [])
    ]
    return json.dumps({"accounts": accounts}, indent=2, ensure_ascii=False)


@make_tool
def plaid_get_transactions(
    access_token: str,
    start_date: str,
    end_date: str,
) -> str:
    """Get transactions for date range."""
    data = _plaid_post(
        "/transactions/get",
        {
            "access_token": access_token,
            "start_date": start_date,
            "end_date": end_date,
            "options": {"count": 100},
        },
    )
    transactions = [
        {
            "id": t["transaction_id"],
            "amount": t["amount"],
            "date": t["date"],
            "name": t["name"],
            "category": t.get("category", []),
            "account_id": t["account_id"],
        }
        for t in data.get("transactions", [])
    ]
    return json.dumps(
        {"transactions": transactions, "total": data.get("total_transactions", 0)},
        indent=2,
        ensure_ascii=False,
    )


@make_tool
def plaid_get_balance(access_token: str) -> str:
    """Get real-time balance for all accounts."""
    data = _plaid_post(
        "/accounts/balance/get",
        {"access_token": access_token},
    )
    balances = [
        {
            "account_id": a["account_id"],
            "name": a["name"],
            "current": a["balances"].get("current"),
            "available": a["balances"].get("available"),
        }
        for a in data.get("accounts", [])
    ]
    return json.dumps({"balances": balances}, indent=2, ensure_ascii=False)


@make_tool
def plaid_create_transfer(
    access_token: str,
    account_id: str,
    amount: float,
    description: str = "",
) -> str:
    """Initiate an ACH transfer."""
    data = _plaid_post(
        "/transfer/authorization/create",
        {
            "access_token": access_token,
            "account_id": account_id,
            "type": "debit",
            "network": "ach",
            "amount": str(amount),
            "ach_class": "web",
            "user": {"legal_name": "Zeloo User"},
            "description": description or "Zeloo transfer",
        },
    )
    return json.dumps(data, indent=2, ensure_ascii=False)


TOOLS = [
    plaid_create_link_token,
    plaid_get_accounts,
    plaid_get_transactions,
    plaid_get_balance,
    plaid_create_transfer,
]


class PlaidMCPServer(MCPServer):
    name = "plaid"
    description = "Plaid banking and financial data"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["PlaidMCPServer", "TOOLS"]