"""Notion MCP native — pages, databases, and blocks via Notion API."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

NOTION_TOKEN = os.environ.get("NOTION_API_KEY", "")
NOTION_BASE_URL = "https://api.notion.com/v1"


def _notion_headers() -> dict[str, str]:
    if not NOTION_TOKEN:
        raise ValueError("NOTION_API_KEY environment variable not set")
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


@make_tool
def notion_search(query: str, filter_type: str = "", limit: int = 10) -> str:
    """Search Notion pages and databases.

    Args:
        query: Search query text.
        filter_type: Filter by type ("page" or "database").
        limit: Number of results.
    """
    url = f"{NOTION_BASE_URL}/search"
    payload: dict[str, Any] = {"query": query, "page_size": min(limit, 100)}
    if filter_type:
        payload["filter"] = {"property": "object", "value": filter_type}
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_notion_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def notion_get_page(page_id: str) -> str:
    """Get a Notion page's content.

    Args:
        page_id: The page ID (32-char hex string).
    """
    url = f"{NOTION_BASE_URL}/pages/{page_id}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_notion_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def notion_get_block_children(block_id: str, limit: int = 50) -> str:
    """Get children blocks of a Notion page or block.

    Args:
        block_id: Page or block ID.
        limit: Number of children.
    """
    url = f"{NOTION_BASE_URL}/blocks/{block_id}/children"
    params = {"page_size": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_notion_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def notion_create_page(
    parent_id: str,
    title: str,
    content: str = "",
) -> str:
    """Create a new Notion page.

    Args:
        parent_id: Parent page or database ID.
        title: Page title.
        content: Optional initial paragraph content.
    """
    url = f"{NOTION_BASE_URL}/pages"
    page_props: dict[str, Any] = {
        "title": [{"text": {"content": title}}]
    }
    children: list[dict[str, Any]] = []
    if content:
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]},
        })
    payload: dict[str, Any] = {
        "parent": {"page_id": parent_id},
        "properties": {"title": page_props},
    }
    if children:
        payload["children"] = children
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_notion_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def notion_database_query(
    database_id: str,
    filter_json: str = "",
    limit: int = 100,
) -> str:
    """Query a Notion database.

    Args:
        database_id: The database ID.
        filter_json: Optional JSON filter string.
        limit: Number of results.
    """
    url = f"{NOTION_BASE_URL}/databases/{database_id}/query"
    payload: dict[str, Any] = {"page_size": min(limit, 100)}
    if filter_json:
        try:
            payload["filter"] = json.loads(filter_json)
        except json.JSONDecodeError:
            pass
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_notion_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    notion_search,
    notion_get_page,
    notion_get_block_children,
    notion_create_page,
    notion_database_query,
]


class NotionMCPServer(MCPServer):
    name = "notion-native"
    description = "Notion pages, databases, and blocks via native API"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["NotionMCPServer", "TOOLS"]
