"""Notion MCP server — exposes Notion API as MCP tools over stdio JSON-RPC."""

from __future__ import annotations

import os

from optional_mcps.base import MCPServer, make_tool

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _get_headers() -> dict[str, str]:
    token = os.environ.get("NOTION_API_KEY", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _notion_get(path: str, params: dict | None = None) -> dict | list:
    url = f"{NOTION_API_BASE}/{path.lstrip('/')}"
    headers = _get_headers()
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()


def _notion_post(path: str, payload: dict) -> dict:
    url = f"{NOTION_API_BASE}/{path.lstrip('/')}"
    headers = _get_headers()
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


def _notion_patch(path: str, payload: dict) -> dict:
    url = f"{NOTION_API_BASE}/{path.lstrip('/')}"
    headers = _get_headers()
    with httpx.Client(timeout=15.0) as client:
        resp = client.patch(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


def _extract_text(content: list[dict]) -> str:
    parts: list[str] = []
    for block in content:
        btype = block.get("type", "")
        rich_text = block.get(btype, {}).get("rich_text", [])
        text = "".join(t.get("plain_text", "") for t in rich_text)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _format_page(page: dict) -> str:
    title = ""
    for _prop_name, prop_val in page.get("properties", {}).items():
        if prop_val.get("type") == "title":
            title_parts = prop_val.get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_parts) or "(untitled)"
            break
    pid = page.get("id", "?")
    url = page.get("url", "")
    last_edited = page.get("last_edited_time", "?")
    return f"Page: {title}\nID: {pid}\nURL: {url}\nLast edited: {last_edited}"


if _HTTPX_AVAILABLE:

    @make_tool(
        name="notion_search",
        description="Search all pages and databases accessible to the integration",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text"},
                "filter_type": {
                    "type": "string",
                    "description": "Filter by type: 'page' or 'database' (optional)",
                    "enum": ["page", "database"],
                },
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    )
    def notion_search(query: str, filter_type: str | None = None, max_results: int = 10) -> str:
        payload: dict[str, object] = {"query": query, "page_size": max_results}
        if filter_type:
            payload["filter"] = {"property": "object", "value": filter_type}
        data = _notion_post("search", payload)
        results = data.get("results", [])
        if not results:
            return "No results found."
        lines: list[str] = []
        for item in results:
            if item.get("object") == "page":
                lines.append(_format_page(item))
            else:
                db_title = "".join(
                    t.get("plain_text", "")
                    for t in item.get("title", [])
                ) or "(untitled database)"
                lines.append(
                    f"Database: {db_title}\nID: {item.get('id', '?')}\n"
                    f"URL: {item.get('url', '?')}"
                )
        return "\n\n---\n\n".join(lines)

    @make_tool(
        name="notion_get_page",
        description="Retrieve a page and its block content",
        input_schema={
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "Notion page ID (32-char hex string)"},
                "max_blocks": {
                    "type": "integer",
                    "default": 50,
                    "description": "Max blocks to fetch",
                },
            },
            "required": ["page_id"],
        },
    )
    def notion_get_page(page_id: str, max_blocks: int = 50) -> str:
        page = _notion_get(f"pages/{page_id}")
        blocks = _notion_get(f"blocks/{page_id}/children", {"page_size": max_blocks})
        block_text = _extract_text(blocks.get("results", []))
        header = _format_page(page)
        return f"{header}\n\nContent:\n{block_text}" if block_text else header

    @make_tool(
        name="notion_create_page",
        description="Create a new page as a child of a parent page or database",
        input_schema={
            "type": "object",
            "properties": {
                "parent_id": {
                    "type": "string",
                    "description": "Parent page ID or database ID",
                },
                "title": {"type": "string", "description": "Page title"},
                "content": {
                    "type": "string",
                    "description": "Initial page content (plain text)",
                    "default": "",
                },
                "as_database_item": {
                    "type": "boolean",
                    "description": "If True, parent_id is a database ID",
                    "default": False,
                },
            },
            "required": ["parent_id", "title"],
        },
    )
    def notion_create_page(
        parent_id: str,
        title: str,
        content: str = "",
        as_database_item: bool = False,
    ) -> str:
        parent: dict[str, object] = (
            {"database_id": parent_id} if as_database_item else {"page_id": parent_id}
        )
        payload: dict[str, object] = {
            "parent": parent,
            "properties": {
                "title": {
                    "title": [{"text": {"content": title}}],
                },
            },
        }
        if content:
            payload["children"] = [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": content[:2000]}}],
                    },
                },
            ]
        page = _notion_post("pages", payload)
        return f"Page created: {title}\nID: {page.get('id', '?')}\nURL: {page.get('url', '?')}"

    @make_tool(
        name="notion_append_block",
        description="Append a block (paragraph) to a page",
        input_schema={
            "type": "object",
            "properties": {
                "block_id": {"type": "string", "description": "Page or block ID to append to"},
                "content": {"type": "string", "description": "Text content to append"},
                "block_type": {
                    "type": "string",
                    "description": "Block type",
                    "default": "paragraph",
                    "enum": ["paragraph", "heading_1", "heading_2", "heading_3", "quote", "code"],
                },
            },
            "required": ["block_id", "content"],
        },
    )
    def notion_append_block(block_id: str, content: str, block_type: str = "paragraph") -> str:
        truncated = content[:2000]
        block_payload = {
            block_type: {
                "rich_text": [{"type": "text", "text": {"content": truncated}}],
            },
        }
        payload = {"children": [{"object": "block", "type": block_type, **block_payload}]}
        result = _notion_post(f"blocks/{block_id}/children", payload)
        created = result.get("results", [])
        if created:
            return f"Block appended to {block_id}: {created[0].get('id', '?')}"
        return f"Block appended to {block_id}"

    @make_tool(
        name="notion_query_database",
        description="Query a Notion database with optional filters and sorts",
        input_schema={
            "type": "object",
            "properties": {
                "database_id": {"type": "string", "description": "Notion database ID"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["database_id"],
        },
    )
    def notion_query_database(database_id: str, max_results: int = 10) -> str:
        payload = {"page_size": max_results}
        data = _notion_post(f"databases/{database_id}/query", payload)
        results = data.get("results", [])
        if not results:
            return "No results found in database."
        lines: list[str] = []
        for page in results:
            title = ""
            for prop_val in page.get("properties", {}).values():
                if prop_val.get("type") == "title":
                    title_parts = prop_val.get("title", [])
                    title = "".join(t.get("plain_text", "") for t in title_parts) or "(untitled)"
                    break
            lines.append(f"- {title} | {page.get('id', '?')}")
        return f"Found {len(results)} item(s):\n" + "\n".join(lines)

    TOOLS: list = [
        notion_search,
        notion_get_page,
        notion_create_page,
        notion_append_block,
        notion_query_database,
    ]

else:
    TOOLS = []


def main() -> None:
    server = MCPServer(name="notion", version="1.0.0", tools=TOOLS)
    server.run()


if __name__ == "__main__":
    main()
