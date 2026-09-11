"""QuickBooks MCP — accounting, invoicing, and reporting."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

QB_CLIENT_ID = os.environ.get("QUICKBOOKS_CLIENT_ID", "")
QB_CLIENT_SECRET = os.environ.get("QUICKBOOKS_CLIENT_SECRET", "")
QB_REFRESH_TOKEN = os.environ.get("QUICKBOOKS_REFRESH_TOKEN", "")
QB_REALM_ID = os.environ.get("QUICKBOOKS_REALM_ID", "")


def _get_qb_token() -> str:
    if not QB_CLIENT_ID:
        raise ValueError("QUICKBOOKS_CLIENT_ID must be set")
    resp = httpx.post(
        "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        auth=(QB_CLIENT_ID, QB_CLIENT_SECRET),
        headers={"Accept": "application/json"},
        data={
            "grant_type": "refresh_token",
            "refresh_token": QB_REFRESH_TOKEN,
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _qb_headers() -> dict[str, str]:
    token = _get_qb_token()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


@make_tool
def quickbooks_list_customers(limit: int = 50) -> str:
    """List QuickBooks customers."""
    url = (
        f"https://quickbooks.api.intuit.com/v3/company/{QB_REALM_ID}"
        "/query?query=select * from Customer maxresults 100"
    )
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_qb_headers())
        resp.raise_for_status()
    customers = [
        {"id": c["Id"], "name": c.get("DisplayName"),
         "email": c.get("PrimaryEmailAddr", {}).get("Address")}
        for c in resp.json().get("QueryResponse", {}).get("Customer", [])
    ]
    return json.dumps({"customers": customers}, indent=2, ensure_ascii=False)


@make_tool
def quickbooks_list_invoices(limit: int = 50) -> str:
    """List QuickBooks invoices."""
    url = (
        f"https://quickbooks.api.intuit.com/v3/company/{QB_REALM_ID}"
        f"/query?query=select * from Invoice maxresults {min(limit, 100)}"
    )
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_qb_headers())
        resp.raise_for_status()
    invoices = [
        {"id": i["Id"], "doc_number": i.get("DocNumber"),
         "total": i.get("TotalAmt"), "balance": i.get("Balance")}
        for i in resp.json().get("QueryResponse", {}).get("Invoice", [])
    ]
    return json.dumps({"invoices": invoices}, indent=2, ensure_ascii=False)


@make_tool
def quickbooks_create_invoice(
    customer_id: str,
    amount: float,
    description: str = "",
) -> str:
    """Create a QuickBooks invoice."""
    url = (
        f"https://quickbooks.api.intuit.com/v3/company/{QB_REALM_ID}/invoice"
    )
    payload = {
        "Line": [{
            "Amount": amount,
            "DetailType": "SalesItemLineDetail",
            "Description": description or "Service",
            "SalesItemLineDetail": {
                "ItemRef": {"value": "1", "name": "Services"},
            },
        }],
        "CustomerRef": {"value": customer_id},
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_qb_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def quickbooks_list_accounts() -> str:
    """List QuickBooks chart of accounts."""
    url = (
        f"https://quickbooks.api.intuit.com/v3/company/{QB_REALM_ID}"
        "/query?query=select * from Account maxresults 100"
    )
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_qb_headers())
        resp.raise_for_status()
    accounts = [
        {"id": a["Id"], "name": a.get("Name"),
         "type": a.get("AccountType"), "balance": a.get("CurrentBalance")}
        for a in resp.json().get("QueryResponse", {}).get("Account", [])
    ]
    return json.dumps({"accounts": accounts}, indent=2, ensure_ascii=False)


@make_tool
def quickbooks_profit_loss_report(
    start_date: str, end_date: str
) -> str:
    """Generate Profit & Loss report."""
    url = (
        f"https://quickbooks.api.intuit.com/v3/company/{QB_REALM_ID}"
        f"/reports/ProfitAndLoss?start_date={start_date}&end_date={end_date}"
        "&summarize_column_by=Total"
    )
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_qb_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    quickbooks_list_customers,
    quickbooks_list_invoices,
    quickbooks_create_invoice,
    quickbooks_list_accounts,
    quickbooks_profit_loss_report,
]


class QuickBooksMCPServer(MCPServer):
    name = "quickbooks"
    description = "QuickBooks accounting and reporting"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["QuickBooksMCPServer", "TOOLS"]