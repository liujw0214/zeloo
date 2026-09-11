"""Trello MCP — board, list, and card management."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

TRELLO_KEY = os.environ.get("TRELLO_API_KEY", "")
TRELLO_TOKEN = os.environ.get("TRELLO_TOKEN", "")
TRELLO_BASE_URL = "https://api.trello.com/1"


def _trello_params() -> dict[str, str]:
    if not TRELLO_KEY or not TRELLO_TOKEN:
        raise ValueError("TRELLO_API_KEY and TRELLO_TOKEN must be set")
    return {"key": TRELLO_KEY, "token": TRELLO_TOKEN}


@make_tool
def trello_list_boards() -> str:
    """List all Trello boards for the authenticated user."""
    url = f"{TRELLO_BASE_URL}/members/me/boards"
    params = {**_trello_params(), "fields": "name,desc,closed"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def trello_list_lists(board_id: str) -> str:
    """List all lists on a Trello board.

    Args:
        board_id: The board ID.
    """
    url = f"{TRELLO_BASE_URL}/boards/{board_id}/lists"
    params = {**_trello_params(), "filter": "open"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def trello_create_card(
    name: str,
    id_list: str,
    desc: str = "",
    due: str = "",
) -> str:
    """Create a new card on a Trello list.

    Args:
        name: Card name.
        id_list: The list ID to add the card to.
        desc: Card description.
        due: Due date (ISO format).
    """
    url = f"{TRELLO_BASE_URL}/cards"
    payload = {**_trello_params(), "name": name, "idList": id_list}
    if desc:
        payload["desc"] = desc
    if due:
        payload["due"] = due
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def trello_get_card(card_id: str) -> str:
    """Get a specific card by ID.

    Args:
        card_id: The card ID.
    """
    url = f"{TRELLO_BASE_URL}/cards/{card_id}"
    params = {**_trello_params(), "fields": "all"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def trello_archive_card(card_id: str) -> str:
    """Archive (close) a Trello card.

    Args:
        card_id: The card ID.
    """
    url = f"{TRELLO_BASE_URL}/cards/{card_id}"
    payload = {**_trello_params(), "closed": "true"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.put(url, json=payload)
        resp.raise_for_status()
    return json.dumps({"message": "Card archived"})


TOOLS = [
    trello_list_boards,
    trello_list_lists,
    trello_create_card,
    trello_get_card,
    trello_archive_card,
]


class TrelloMCPServer(MCPServer):
    name = "trello"
    description = "Trello board, list, and card management"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["TrelloMCPServer", "TOOLS"]
