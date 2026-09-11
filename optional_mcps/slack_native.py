"""Slack MCP native — messages, channels, and users via Slack Web API."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_BASE_URL = "https://slack.com/api"


def _slack_headers() -> dict[str, str]:
    if not SLACK_TOKEN:
        raise ValueError("SLACK_BOT_TOKEN environment variable not set")
    return {
        "Authorization": f"Bearer {SLACK_TOKEN}",
        "Content-Type": "application/json",
    }


@make_tool
def slack_list_channels(limit: int = 200) -> str:
    """List all Slack channels in the workspace.

    Args:
        limit: Maximum number of channels.
    """
    url = f"{SLACK_BASE_URL}/conversations.list"
    params = {"limit": min(limit, 200), "exclude_archived": True}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_slack_headers(), params=params)
        resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        return json.dumps({"error": data.get("error", "unknown")})
    channels = [
        {"id": c["id"], "name": c["name"], "is_channel": c.get("is_channel", False)}
        for c in data.get("channels", [])
    ]
    return json.dumps({"channels": channels}, indent=2)


@make_tool
def slack_post_message(
    channel: str,
    text: str,
    thread_ts: str = "",
) -> str:
    """Post a message to a Slack channel.

    Args:
        channel: Channel ID or name (with # prefix).
        text: Message text.
        thread_ts: Thread timestamp for replies.
    """
    url = f"{SLACK_BASE_URL}/chat.postMessage"
    payload: dict[str, Any] = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_slack_headers(), json=payload)
        resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        return json.dumps({"error": data.get("error", "unknown")})
    return json.dumps({"ts": data.get("ts"), "channel": data.get("channel")})


@make_tool
def slack_get_thread_replies(
    channel: str,
    thread_ts: str,
) -> str:
    """Get replies in a Slack thread.

    Args:
        channel: Channel ID.
        thread_ts: Thread timestamp.
    """
    url = f"{SLACK_BASE_URL}/conversations.replies"
    params = {"channel": channel, "ts": thread_ts}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_slack_headers(), params=params)
        resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        return json.dumps({"error": data.get("error", "unknown")})
    return json.dumps({"messages": data.get("messages", [])}, indent=2, ensure_ascii=False)


@make_tool
def slack_list_users(limit: int = 200) -> str:
    """List all Slack workspace users.

    Args:
        limit: Maximum number of users.
    """
    url = f"{SLACK_BASE_URL}/users.list"
    params = {"limit": min(limit, 200)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_slack_headers(), params=params)
        resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        return json.dumps({"error": data.get("error", "unknown")})
    users = [
        {"id": u["id"], "name": u["name"], "real_name": u.get("real_name", "")}
        for u in data.get("members", [])
        if not u.get("deleted")
    ]
    return json.dumps({"users": users}, indent=2, ensure_ascii=False)


@make_tool
def slack_search_messages(query: str, count: int = 20) -> str:
    """Search messages in Slack.

    Args:
        query: Search query.
        count: Number of results.
    """
    url = f"{SLACK_BASE_URL}/search.messages"
    params = {"query": query, "count": min(count, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_slack_headers(), params=params)
        resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        return json.dumps({"error": data.get("error", "unknown")})
    results = data.get("messages", {}).get("matches", [])
    return json.dumps(
        {"matches": [
            {"channel": m.get("channel", {}).get("name"),
             "user": m.get("user"),
             "text": m.get("text", ""),
             "ts": m.get("ts", "")}
            for m in results
        ]},
        indent=2,
        ensure_ascii=False,
    )


TOOLS = [
    slack_list_channels,
    slack_post_message,
    slack_get_thread_replies,
    slack_list_users,
    slack_search_messages,
]


class SlackNativeMCPServer(MCPServer):
    name = "slack-native"
    description = "Slack messages, channels, threads, and users via native Web API"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["SlackNativeMCPServer", "TOOLS"]
