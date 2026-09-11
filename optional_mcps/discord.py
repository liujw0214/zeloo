"""Discord MCP Server — channels, messages, threads, and guild management."""

from __future__ import annotations

import os
from typing import Any

from optional_mcps.base import MCPServer, make_tool


def _get_bot_token() -> str:
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("Set DISCORD_BOT_TOKEN.")
    return token


_BASE_URL = "https://discord.com/api/v10"


def _discord_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    import httpx
    token = _get_bot_token()
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    url = f"{_BASE_URL}{path}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()


def _discord_post(path: str, json_data: dict[str, Any] | None = None) -> dict[str, Any]:
    import httpx
    token = _get_bot_token()
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    url = f"{_BASE_URL}{path}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, json=json_data)
        resp.raise_for_status()
        return resp.json()


@make_tool(
    name="discord_list_channels",
    description="List all channels in a Discord guild",
    input_schema={
        "type": "object",
        "properties": {
            "guild_id": {"type": "string", "description": "Discord guild ID"},
            "type": {
                "type": "string",
                "description": "Channel type filter (0=text, 2=voice, 4=category)",
            },
        },
        "required": ["guild_id"],
    },
)
def discord_list_channels(guild_id: str, type: str = "") -> str:
    params: dict[str, Any] = {}
    if type:
        params["type"] = type
    channels = _discord_get(f"/guilds/{guild_id}/channels", params)
    lines = []
    for ch in channels:
        lines.append(
            f"[{ch.get('type', 0)}] #{ch.get('name', 'unknown')} "
            f"(id={ch.get('id')}, parent={ch.get('parent_id', 'none')})"
        )
    return "\n".join(lines) if lines else "No channels found."


@make_tool(
    name="discord_send_message",
    description="Send a message to a Discord channel",
    input_schema={
        "type": "object",
        "properties": {
            "channel_id": {"type": "string", "description": "Discord channel ID"},
            "content": {"type": "string", "description": "Message content"},
        },
        "required": ["channel_id", "content"],
    },
)
def discord_send_message(channel_id: str, content: str) -> str:
    result = _discord_post(f"/channels/{channel_id}/messages", {"content": content})
    return (
        f"Message sent. id={result.get('id')} "
        f"channel={result.get('channel_id')} "
        f"author={result.get('author', {}).get('username', '?')}"
    )


@make_tool(
    name="discord_get_channel_messages",
    description="Get recent messages from a Discord channel",
    input_schema={
        "type": "object",
        "properties": {
            "channel_id": {"type": "string", "description": "Discord channel ID"},
            "limit": {"type": "integer", "description": "Max messages (default 25)", "default": 25},
        },
        "required": ["channel_id"],
    },
)
def discord_get_channel_messages(channel_id: str, limit: int = 25) -> str:
    messages = _discord_get(
        f"/channels/{channel_id}/messages",
        {"limit": min(limit, 100)},
    )
    lines = []
    for m in reversed(messages):
        author = m.get("author", {})
        lines.append(
            f"[{m.get('timestamp', '')}] "
            f"{author.get('username', '?')}: {m.get('content', '')[:120]}"
        )
    return "\n".join(lines) if lines else "No messages found."


@make_tool(
    name="discord_list_guilds",
    description="List all guilds the bot is a member of",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max results", "default": 100},
        },
    },
)
def discord_list_guilds(limit: int = 100) -> str:
    guilds = _discord_get("/users/@me/guilds", {"limit": limit})
    lines = []
    for g in guilds:
        lines.append(f"  {g.get('name', '?')} (id={g.get('id')})")
    return "\n".join(lines) if lines else "No guilds found."


@make_tool(
    name="discord_search_messages",
    description="Search messages across accessible channels",
    input_schema={
        "type": "object",
        "properties": {
            "guild_id": {"type": "string", "description": "Discord guild ID"},
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "description": "Max results", "default": 25},
        },
        "required": ["guild_id", "query"],
    },
)
def discord_search_messages(guild_id: str, query: str, limit: int = 25) -> str:
    results = _discord_get(
        f"/guilds/{guild_id}/messages/search",
        {"query": query, "limit": min(limit, 25)},
    )
    messages = results.get("messages", [])
    lines = []
    for group in messages:
        for m in group:
            author = m.get("author", {})
            lines.append(
                f"[{m.get('timestamp', '')}] "
                f"{author.get('username', '?')}: {m.get('content', '')[:120]}"
            )
    return "\n".join(lines) if lines else f"No results for '{query}'."


class DiscordServer(MCPServer):
    name = "discord"
    version = "1.0.0"
    TOOLS = [
        discord_list_channels,
        discord_send_message,
        discord_get_channel_messages,
        discord_list_guilds,
        discord_search_messages,
    ]


if __name__ == "__main__":
    server = DiscordServer(tools=DiscordServer.TOOLS)
    server.run()
