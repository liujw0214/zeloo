"""Confluence MCP — wiki pages and spaces."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

CONF_DOMAIN = os.environ.get("CONFLUENCE_DOMAIN", "")
CONF_EMAIL = os.environ.get("CONFLUENCE_EMAIL", "")
CONF_TOKEN = os.environ.get("CONFLUENCE_API_TOKEN", "")
CONF_BASE_URL = f"https://{CONF_DOMAIN}.atlassian.net/wiki/api/v2"


def _conf_headers() -> dict[str, str]:
    import base64
    if not CONF_TOKEN:
        raise ValueError("CONFLUENCE_API_TOKEN must be set")
    creds = base64.b64encode(
        f"{CONF_EMAIL}:{CONF_TOKEN}".encode()
    ).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/json",
    }


@make_tool
def confluence_list_spaces(limit: int = 50) -> str:
    """List Confluence spaces."""
    url = f"{CONF_BASE_URL}/spaces"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_conf_headers(), params=params)
        resp.raise_for_status()
    spaces = [
        {"id": s["id"], "key": s["key"], "name": s.get("name")}
        for s in resp.json().get("results", [])
    ]
    return json.dumps({"spaces": spaces}, indent=2, ensure_ascii=False)


@make_tool
def confluence_search_pages(query: str, limit: int = 25) -> str:
    """Search Confluence pages by text."""
    url = f"{CONF_BASE_URL}/pages/search"
    payload = {
        "query": query,
        "limit": min(limit, 100),
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_conf_headers(), json=payload)
        resp.raise_for_status()
    pages = [
        {"id": p["id"], "title": p.get("title"),
         "space_id": p.get("spaceId"),
         "updated_at": p.get("version", {}).get("createdAt", "")}
        for p in resp.json().get("results", [])
    ]
    return json.dumps({"pages": pages}, indent=2, ensure_ascii=False)


@make_tool
def confluence_get_page(page_id: str) -> str:
    """Get a Confluence page by ID."""
    url = f"{CONF_BASE_URL}/pages/{page_id}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_conf_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def confluence_create_page(
    space_id: str,
    title: str,
    content: str = "",
) -> str:
    """Create a Confluence page."""
    url = f"{CONF_BASE_URL}/pages"
    payload = {
        "spaceId": space_id,
        "status": "current",
        "title": title,
        "body": {
            "representation": "storage",
            "value": content or f"<p>{title}</p>",
        },
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_conf_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def confluence_list_page_comments(page_id: str) -> str:
    """List comments on a page."""
    url = f"{CONF_BASE_URL}/pages/{page_id}/footer-comments"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_conf_headers())
        resp.raise_for_status()
    comments = [
        {"id": c["id"], "body": c.get("body", {}).get("value", "")}
        for c in resp.json().get("results", [])
    ]
    return json.dumps({"comments": comments}, indent=2, ensure_ascii=False)


TOOLS = [
    confluence_list_spaces,
    confluence_search_pages,
    confluence_get_page,
    confluence_create_page,
    confluence_list_page_comments,
]


class ConfluenceMCPServer(MCPServer):
    name = "confluence"
    description = "Confluence wiki pages and spaces"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["ConfluenceMCPServer", "TOOLS"]