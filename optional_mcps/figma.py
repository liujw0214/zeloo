"""Figma MCP server — exposes Figma API as MCP tools over stdio JSON-RPC."""

from __future__ import annotations

import os

from optional_mcps.base import MCPServer, make_tool

try:
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


Figma_API_BASE = "https://api.figma.com/v1"


def _get_headers() -> dict[str, str]:
    token = os.environ.get("FIGMA_ACCESS_TOKEN", "")
    return {
        "X-Figma-Token": token,
    }


def _figma_get(path: str, params: dict | None = None) -> dict | list:
    url = f"{Figma_API_BASE}/{path.lstrip('/')}"
    headers = _get_headers()
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()


def _format_file(file: dict) -> str:
    name = file.get("name", "?")
    last_modified = file.get("lastModified", "?")
    thumbnail_url = file.get("thumbnailUrl", "")
    document = file.get("document", {})
    node_count = _count_nodes(document) if document else 0
    lines = [
        f"File: {name}",
        f"Last Modified: {last_modified}",
        f"Thumbnail: {thumbnail_url}" if thumbnail_url else "Thumbnail: N/A",
        f"Node Count: {node_count}",
    ]
    return "\n".join(lines)


def _count_nodes(node: dict) -> int:
    count = 1
    children = node.get("children", [])
    for child in children:
        count += _count_nodes(child)
    return count


def _format_comment(c: dict) -> str:
    msg = c.get("message", "")
    author = c.get("user", {}).get("handle", c.get("user", {}).get("email", "?"))
    timestamp = c.get("created_at", "?")
    resolved = c.get("resolved", False)
    resolved_str = "Resolved" if resolved else "Open"
    return f"[{resolved_str}] {author} at {timestamp}: {msg}"


if _HTTPX_AVAILABLE:

    @make_tool(
        name="figma_get_file",
        description="Get Figma file metadata and structure",
        input_schema={
            "type": "object",
            "properties": {
                "file_key": {"type": "string", "description": "Figma file key (from URL)"},
                "node_ids": {
                    "type": "string",
                    "description": "Comma-separated node IDs to fetch (optional)",
                },
                "depth": {
                    "type": "integer",
                    "description": "Maximum depth to traverse (optional, default 1)",
                    "default": 1,
                },
            },
            "required": ["file_key"],
        },
    )
    def figma_get_file(
        file_key: str,
        node_ids: str | None = None,
        depth: int = 1,
    ) -> str:
        params: dict[str, object] = {"depth": depth}
        if node_ids:
            params["ids"] = node_ids
        data = _figma_get(f"files/{file_key}", params)
        return _format_file(data)

    @make_tool(
        name="figma_get_comments",
        description="Get all comments on a Figma file",
        input_schema={
            "type": "object",
            "properties": {
                "file_key": {"type": "string", "description": "Figma file key (from URL)"},
            },
            "required": ["file_key"],
        },
    )
    def figma_get_comments(file_key: str) -> str:
        data = _figma_get(f"files/{file_key}/comments")
        comments = data.get("comments", [])
        if not comments:
            return "No comments found."
        return "\n".join(_format_comment(c) for c in comments)

    @make_tool(
        name="figma_list_components",
        description="Get all components in a Figma file",
        input_schema={
            "type": "object",
            "properties": {
                "file_key": {"type": "string", "description": "Figma file key (from URL)"},
            },
            "required": ["file_key"],
        },
    )
    def figma_list_components(file_key: str) -> str:
        data = _figma_get(f"files/{file_key}/components")
        components = data.get("components", {})
        if not components:
            return "No components found."
        lines: list[str] = []
        for key, comp in components.items():
            name = comp.get("name", "?")
            description = comp.get("description", "")
            lines.append(f"- {name} ({key})")
            if description:
                lines.append(f"  {description}")
        return "\n".join(lines)

    @make_tool(
        name="figma_get_styles",
        description="Get all styles in a Figma file",
        input_schema={
            "type": "object",
            "properties": {
                "file_key": {"type": "string", "description": "Figma file key (from URL)"},
            },
            "required": ["file_key"],
        },
    )
    def figma_get_styles(file_key: str) -> str:
        data = _figma_get(f"files/{file_key}/styles")
        styles = data.get("meta", {}).get("styles", [])
        if not styles:
            return "No styles found."
        lines: list[str] = []
        for style in styles:
            name = style.get("name", "?")
            style_type = style.get("style_type", "?")
            key = style.get("key", "?")
            lines.append(f"- {name} [{style_type}] ({key})")
        return "\n".join(lines)

    @make_tool(
        name="figma_get_images",
        description="Export images from Figma nodes",
        input_schema={
            "type": "object",
            "properties": {
                "file_key": {"type": "string", "description": "Figma file key (from URL)"},
                "node_ids": {
                    "type": "string",
                    "description": "Comma-separated node IDs to export",
                },
                "format": {
                    "type": "string",
                    "description": "Image format (png, svg, jpg, pdf)",
                    "default": "png",
                },
                "scale": {
                    "type": "number",
                    "description": "Export scale factor",
                    "default": 2.0,
                },
            },
            "required": ["file_key", "node_ids"],
        },
    )
    def figma_get_images(
        file_key: str,
        node_ids: str,
        format: str = "png",
        scale: float = 2.0,
    ) -> str:
        params = {
            "ids": node_ids,
            "format": format,
            "scale": scale,
        }
        data = _figma_get(f"images/{file_key}", params)
        images = data.get("images", {})
        if not images:
            return "No images found."
        lines: list[str] = []
        for node_id, url in images.items():
            lines.append(f"{node_id}: {url}")
        return "\n".join(lines)

    TOOLS: list = [
        figma_get_file,
        figma_get_comments,
        figma_list_components,
        figma_get_styles,
        figma_get_images,
    ]

else:
    TOOLS = []


def main() -> None:
    server = MCPServer(name="figma", version="1.0.0", tools=TOOLS)
    server.run()


if __name__ == "__main__":
    main()
