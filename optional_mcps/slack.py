"""Slack MCP server — exposes Slack Web API as MCP tools over stdio JSON-RPC."""

from __future__ import annotations

import os

from optional_mcps.base import MCPServer, make_tool

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


SLACK_API_BASE = "https://slack.com/api"


def _slack_get(method: str, params: dict | None = None) -> dict:
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    url = f"{SLACK_API_BASE}/{method}"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=headers, params=params or {})
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")
        return data


def _slack_post(method: str, data: dict) -> dict:
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    url = f"{SLACK_API_BASE}/{method}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=headers, json=data)
        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            raise RuntimeError(f"Slack API error: {result.get('error', 'unknown')}")
        return result


def _format_channel(channel: dict) -> str:
    is_private = channel.get("is_private", False)
    topic = channel.get("topic", {}).get("value", "")
    member_count = channel.get("num_members", 0)
    visibility = "private" if is_private else "public"
    topic_str = f" | Topic: {topic}" if topic else ""
    return (
        f"#{channel.get('name', '?')} (ID: {channel.get('id', '?')}) "
        f"[{visibility}] | {member_count} members{topic_str}\n"
        f"  Created: {channel.get('created', '?')}"
    )


def _format_message(msg: dict, users: dict) -> str:
    user_id = msg.get("user", "?")
    user_name = users.get(user_id, user_id)
    ts = msg.get("ts", "?")
    text = msg.get("text", "")
    thread_ts = msg.get("thread_ts", "")
    thread_suffix = " (thread reply)" if thread_ts else ""
    return f"[{ts}] {user_name}: {text}{thread_suffix}"


if _HTTPX_AVAILABLE:

    @make_tool(
        name="slack_list_channels",
        description="List all channels visible to the bot",
        input_schema={
            "type": "object",
            "properties": {
                "exclude_archived": {
                    "type": "boolean",
                    "description": "Exclude archived channels",
                    "default": True,
                },
                "types": {
                    "type": "string",
                    "description": "Comma-separated: public_channel,private_channel,im,mpim",
                    "default": "public_channel,private_channel",
                },
            },
        },
    )
    def slack_list_channels(
        exclude_archived: bool = True, types: str = "public_channel,private_channel"
    ) -> str:
        types_param = ",".join(t.strip() for t in types.split(","))
        params = {
            "exclude_archived": exclude_archived,
            "types": types_param,
            "limit": 200,
        }
        data = _slack_get("conversations.list", params)
        channels = data.get("channels", [])
        if not channels:
            return "No channels found."
        return "\n".join(_format_channel(ch) for ch in channels)

    @make_tool(
        name="slack_post_message",
        description="Post a message to a Slack channel or user",
        input_schema={
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Channel ID, channel name (e.g. #general), or user ID",
                },
                "text": {"type": "string", "description": "Message text (supports Slack markdown)"},
                "thread_ts": {
                    "type": "string",
                    "description": "Reply to a thread (optional, use parent message ts)",
                },
            },
            "required": ["channel", "text"],
        },
    )
    def slack_post_message(channel: str, text: str, thread_ts: str = "") -> str:
        payload: dict[str, object] = {"channel": channel, "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        result = _slack_post("chat.postMessage", payload)
        ts = result.get("ts", "?")
        channel_name = result.get("channel", channel)
        thread_note = " (thread reply)" if thread_ts else ""
        return f"Message posted to {channel_name} at {ts}{thread_note}"

    @make_tool(
        name="slack_search_messages",
        description="Search messages across all channels the bot has access to",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    )
    def slack_search_messages(query: str, max_results: int = 10) -> str:
        params = {"query": query, "count": max_results, "sort": "score"}
        data = _slack_get("search.messages", params)
        matches = data.get("messages", {}).get("matches", [])
        if not matches:
            return f"No messages found for: {query}"
        user_map: dict[str, str] = {}
        results: list[str] = []
        for msg in matches:
            user_id = msg.get("user", "?")
            if user_id not in user_map:
                user_data = _slack_get("users.info", {"user": user_id})
                user_map[user_id] = (
                    user_data.get("user", {}).get("real_name", user_id)
                )
            results.append(_format_message(msg, user_map))
        return f"Found {len(results)} result(s) for '{query}':\n" + "\n".join(results)

    @make_tool(
        name="slack_get_channel_history",
        description="Get recent messages from a channel",
        input_schema={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel ID or name"},
                "max_messages": {
                    "type": "integer",
                    "description": "Max messages to fetch",
                    "default": 50,
                },
                "include_threads": {
                    "type": "boolean",
                    "description": "Include thread replies",
                    "default": False,
                },
            },
            "required": ["channel"],
        },
    )
    def slack_get_channel_history(
        channel: str,
        max_messages: int = 50,
        include_threads: bool = False,
    ) -> str:
        channel_data = _slack_get("conversations.info", {"channel": channel})
        ch = channel_data.get("channel", {})
        channel_id = ch.get("id", channel)
        params = {"channel": channel_id, "limit": min(max_messages, 200)}
        data = _slack_get("conversations.history", params)
        messages = data.get("messages", [])
        if not messages:
            return f"No messages in #{ch.get('name', channel)}"
        user_map: dict[str, str] = {}
        lines: list[str] = []
        for msg in messages:
            if msg.get("subtype") == "bot_message":
                lines.append(f"[{msg.get('ts', '?')}] bot: {msg.get('text', '')}")
                continue
            user_id = msg.get("user", "?")
            if user_id not in user_map:
                try:
                    user_data = _slack_get("users.info", {"user": user_id})
                    user_map[user_id] = (
                        user_data.get("user", {}).get("real_name", user_id)
                    )
                except Exception:
                    user_map[user_id] = user_id
            lines.append(_format_message(msg, user_map))
        return f"Recent messages in #{ch.get('name', channel)}:\n" + "\n".join(lines)

    @make_tool(
        name="slack_list_users",
        description="List users in the workspace",
        input_schema={
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "default": 50},
            },
        },
    )
    def slack_list_users(max_results: int = 50) -> str:
        params = {"limit": min(max_results, 200)}
        data = _slack_get("users.list", params)
        members = data.get("members", [])
        if not members:
            return "No users found."
        lines: list[str] = []
        for user in members:
            if user.get("deleted"):
                continue
            name = user.get("real_name") or user.get("name", "?")
            status = user.get("profile", {}).get("status_emoji", "")
            status_text = user.get("profile", {}).get("status_text", "")
            status_str = f" {status}{status_text}" if status_text else ""
            is_bot = " [bot]" if user.get("is_bot") else ""
            lines.append(f"- {name}{is_bot}{status_str} | ID: {user.get('id', '?')}")
        return f"Users ({len(lines)}):\n" + "\n".join(lines)

    TOOLS: list = [
        slack_list_channels,
        slack_post_message,
        slack_search_messages,
        slack_get_channel_history,
        slack_list_users,
    ]

else:
    TOOLS = []


def main() -> None:
    server = MCPServer(name="slack", version="1.0.0", tools=TOOLS)
    server.run()


if __name__ == "__main__":
    main()
