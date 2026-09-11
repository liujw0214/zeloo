"""Monday.com MCP — work management and boards."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

MONDAY_TOKEN = os.environ.get("MONDAY_API_KEY", "")
MONDAY_BASE_URL = "https://api.monday.com/v2"


def _monday_headers() -> dict[str, str]:
    if not MONDAY_TOKEN:
        raise ValueError("MONDAY_API_KEY must be set")
    return {
        "Authorization": MONDAY_TOKEN,
        "Content-Type": "application/json",
    }


def _query(q: str, variables: dict | None = None) -> dict:
    body: dict = {"query": q}
    if variables:
        body["variables"] = variables
    with httpx.Client(timeout=20.0) as client:
        resp = client.post(MONDAY_BASE_URL, headers=_monday_headers(), json=body)
        resp.raise_for_status()
    return resp.json()


@make_tool
def monday_list_boards(limit: int = 50) -> str:
    """List Monday.com boards."""
    q = "query { boards(limit: $limit) { id name state type } }"
    data = _query(q, {"limit": min(limit, 100)})
    boards = data.get("data", {}).get("boards", [])
    return json.dumps({"boards": boards}, indent=2, ensure_ascii=False)


@make_tool
def monday_list_items(board_id: int, limit: int = 25) -> str:
    """List items from a Monday.com board.

    Args:
        board_id: Board numeric ID.
        limit: Number of items.
    """
    q = """
    query($id: ID!, $limit: Int) {
      items_page(board_id: $id, limit: $limit) {
        items { id name column_values { id text value } }
      }
    }
    """
    data = _query(q, {"id": str(board_id), "limit": min(limit, 100)})
    items = data.get("data", {}).get("items_page", {}).get("items", [])
    return json.dumps({"items": items}, indent=2, ensure_ascii=False)


@make_tool
def monday_create_item(
    board_id: int,
    item_name: str,
    column_values: str = "",
) -> str:
    """Create a Monday.com item.

    Args:
        board_id: Board ID.
        item_name: Item name.
        column_values: JSON string of column values.
    """
    cols = json.loads(column_values) if column_values else {}
    q = """
    mutation($name: String!, $board_id: ID!, $cols: JSON) {
      create_item(
        item_name: $name,
        board_id: $board_id,
        column_values: $cols
      ) { id name }
    }
    """
    data = _query(q, {
        "name": item_name,
        "board_id": str(board_id),
        "cols": json.dumps(cols),
    })
    result = data.get("data", {}).get("create_item", {})
    return json.dumps({"id": result.get("id"), "name": result.get("name")}, indent=2)


@make_tool
def monday_get_board_groups(board_id: int) -> str:
    """Get groups in a Monday board."""
    q = "query($id: ID!) { boards(ids: [$id]) { groups { id title } } }"
    data = _query(q, {"id": str(board_id)})
    groups = data.get("data", {}).get("boards", [{}])[0].get("groups", [])
    return json.dumps({"groups": groups}, indent=2, ensure_ascii=False)


@make_tool
def monday_search_items(query: str, limit: int = 20) -> str:
    """Search Monday items by text."""
    q = """
    query($term: String!, $limit: Int) {
      items_page_by_search(
        query: $term,
        limit: $limit
      ) { items { id name board { id name } }
    }
    """
    data = _query(q, {"term": query, "limit": min(limit, 50)})
    items = (
        data.get("data", {})
        .get("items_page_by_search", {})
        .get("items", [])
    )
    return json.dumps({"items": items}, indent=2, ensure_ascii=False)


TOOLS = [
    monday_list_boards,
    monday_list_items,
    monday_create_item,
    monday_get_board_groups,
    monday_search_items,
]


class MondayMCPServer(MCPServer):
    name = "monday"
    description = "Monday.com work management and boards"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["MondayMCPServer", "TOOLS"]
