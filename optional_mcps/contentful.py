"""Contentful MCP — headless CMS for content delivery."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

CTF_SPACE_ID = os.environ.get("CONTENTFUL_SPACE_ID", "")
CTF_ACCESS_TOKEN = os.environ.get("CONTENTFUL_ACCESS_TOKEN", "")
CTF_ENVIRONMENT = os.environ.get("CONTENTFUL_ENVIRONMENT", "master")
CTF_BASE_URL = "https://api.contentful.com"


def _ctf_headers() -> dict[str, str]:
    if not CTF_SPACE_ID or not CTF_ACCESS_TOKEN:
        raise ValueError("CONTENTFUL_SPACE_ID and CONTENTFUL_ACCESS_TOKEN must be set")
    return {
        "Authorization": f"Bearer {CTF_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _ctf_url(path: str) -> str:
    return f"{CTF_BASE_URL}/spaces/{CTF_SPACE_ID}/environments/{CTF_ENVIRONMENT}{path}"


@make_tool
def contentful_list_content_types() -> str:
    """List all Contentful content types."""
    url = _ctf_url("/content_types")
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_ctf_headers())
        resp.raise_for_status()
    types = [
        {"id": t["sys"]["id"], "name": t.get("name"),
         "display_field": t.get("displayField")}
        for t in resp.json().get("items", [])
    ]
    return json.dumps({"content_types": types}, indent=2, ensure_ascii=False)


@make_tool
def contentful_get_entries(
    content_type: str = "", limit: int = 50
) -> str:
    """List entries from Contentful."""
    url = _ctf_url("/entries")
    params: dict[str, Any] = {"limit": min(limit, 100)}
    if content_type:
        params["content_type"] = content_type
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_ctf_headers(), params=params)
        resp.raise_for_status()
    entries = [
        {"id": e["sys"]["id"],
         "content_type": e["sys"]["contentType"]["sys"]["id"],
         "fields": e.get("fields", {}),
         "updated_at": e["sys"].get("updatedAt", "")}
        for e in resp.json().get("items", [])
    ]
    return json.dumps({"entries": entries}, indent=2, ensure_ascii=False)


@make_tool
def contentful_get_entry(entry_id: str) -> str:
    """Get a single entry by ID."""
    url = _ctf_url(f"/entries/{entry_id}")
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_ctf_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def contentful_list_assets(limit: int = 50) -> str:
    """List assets in Contentful."""
    url = _ctf_url("/assets")
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_ctf_headers(), params=params)
        resp.raise_for_status()
    assets = [
        {"id": a["sys"]["id"],
         "title": a.get("fields", {}).get("title"),
         "url": a.get("fields", {}).get("file", {}).get("url")}
        for a in resp.json().get("items", [])
    ]
    return json.dumps({"assets": assets}, indent=2, ensure_ascii=False)


@make_tool
def contentful_query_entries(query: str) -> str:
    """Search entries with Contentful query string."""
    url = _ctf_url("/entries")
    params = {"query": query}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_ctf_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    contentful_list_content_types,
    contentful_get_entries,
    contentful_get_entry,
    contentful_list_assets,
    contentful_query_entries,
]


class ContentfulMCPServer(MCPServer):
    name = "contentful"
    description = "Contentful headless CMS"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["ContentfulMCPServer", "TOOLS"]