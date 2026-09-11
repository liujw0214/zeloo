"""Coda MCP — documents and tables."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

CODA_TOKEN = os.environ.get("CODA_API_TOKEN", "")
CODA_BASE_URL = "https://coda.io/apis/v1"


def _coda_headers() -> dict[str, str]:
    if not CODA_TOKEN:
        raise ValueError("CODA_API_TOKEN must be set")
    return {
        "Authorization": f"Bearer {CODA_TOKEN}",
        "Content-Type": "application/json",
    }


@make_tool
def coda_list_docs(limit: int = 50) -> str:
    """List Coda documents."""
    url = f"{CODA_BASE_URL}/docs"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_coda_headers(), params=params)
        resp.raise_for_status()
    docs = [
        {"id": d["id"], "name": d.get("name"),
         "owner": d.get("owner"),
         "browser_link": d.get("browserLink")}
        for d in resp.json().get("items", [])
    ]
    return json.dumps({"docs": docs}, indent=2, ensure_ascii=False)


@make_tool
def coda_list_tables(doc_id: str) -> str:
    """List tables in a Coda document."""
    url = f"{CODA_BASE_URL}/docs/{doc_id}/tables"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_coda_headers())
        resp.raise_for_status()
    tables = [
        {"id": t["id"], "name": t.get("name"),
         "row_count": t.get("rowCount")}
        for t in resp.json().get("items", [])
    ]
    return json.dumps({"tables": tables}, indent=2, ensure_ascii=False)


@make_tool
def coda_list_rows(
    doc_id: str, table_id: str, limit: int = 50
) -> str:
    """List rows from a Coda table."""
    url = f"{CODA_BASE_URL}/docs/{doc_id}/tables/{table_id}/rows"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_coda_headers(), params=params)
        resp.raise_for_status()
    rows = [
        {"id": r["id"], "values": r.get("values", [])}
        for r in resp.json().get("items", [])
    ]
    return json.dumps({"rows": rows}, indent=2, ensure_ascii=False)


@make_tool
def coda_get_page(doc_id: str, page_id: str) -> str:
    """Get a Coda page."""
    url = f"{CODA_BASE_URL}/docs/{doc_id}/pages/{page_id}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_coda_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def coda_search(query: str, limit: int = 20) -> str:
    """Search Coda docs and pages."""
    url = f"{CODA_BASE_URL}/search"
    params = {"query": query, "limit": min(limit, 50)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_coda_headers(), params=params)
        resp.raise_for_status()
    items = resp.json().get("items", [])
    return json.dumps({"results": items}, indent=2, ensure_ascii=False)


TOOLS = [
    coda_list_docs,
    coda_list_tables,
    coda_list_rows,
    coda_get_page,
    coda_search,
]


class CodaMCPServer(MCPServer):
    name = "coda"
    description = "Coda documents and tables"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["CodaMCPServer", "TOOLS"]