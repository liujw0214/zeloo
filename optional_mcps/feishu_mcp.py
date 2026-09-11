"""Feishu (飞书) MCP Server — messages, calendar, contacts, docs."""

from __future__ import annotations

import os
from typing import Any

from optional_mcps.base import MCPServer, make_tool

_FEISHU_BASE = "https://open.feishu.cn/open-apis"


def _feishu_headers() -> dict[str, str]:
    token = os.environ.get("FEISHU_APP_ACCESS_TOKEN") or os.environ.get("FEISHU_USER_TOKEN")
    if not token:
        raise RuntimeError("Set FEISHU_APP_ACCESS_TOKEN or FEISHU_USER_TOKEN.")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _feishu_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    import httpx
    url = f"{_FEISHU_BASE}{path}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=_feishu_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


def _feishu_post(path: str, json_data: dict[str, Any]) -> dict[str, Any]:
    import httpx
    url = f"{_FEISHU_BASE}{path}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=_feishu_headers(), json=json_data)
        resp.raise_for_status()
        return resp.json()


@make_tool(
    name="feishu_send_message",
    description="Send a text message to a Feishu chat",
    input_schema={
        "type": "object",
        "properties": {
            "chat_id": {"type": "string", "description": "Feishu chat ID"},
            "msg_type": {"type": "string", "description": "Message type", "default": "text"},
            "content": {"type": "string", "description": "Message content"},
        },
        "required": ["chat_id", "content"],
    },
)
def feishu_send_message(chat_id: str, content: str, msg_type: str = "text") -> str:
    payload = {
        "receive_id": chat_id,
        "msg_type": msg_type,
        "content": content if msg_type == "text" else '{"text":"' + content + '"}',
    }
    result = _feishu_post("/im/v1/messages?receive_id_type=chat_id", payload)
    code = result.get("code", 0)
    if code != 0:
        return f"Error {code}: {result.get('msg', '')}"
    return f"Message sent. msg_id={result.get('data', {}).get('message_id', 'N/A')}"


@make_tool(
    name="feishu_list_messages",
    description="List recent messages in a Feishu chat",
    input_schema={
        "type": "object",
        "properties": {
            "chat_id": {"type": "string", "description": "Feishu chat ID"},
            "limit": {"type": "integer", "description": "Max messages (default 20)", "default": 20},
        },
        "required": ["chat_id"],
    },
)
def feishu_list_messages(chat_id: str, limit: int = 20) -> str:
    data = _feishu_get(
        "/im/v1/messages",
        {"container_id_type": "chat", "container_id": chat_id, "limit": limit},
    )
    items = data.get("data", {}).get("items", [])
    lines = []
    for m in items:
        body = m.get("body", {})
        content = body.get("content", "")[:80]
        sender = m.get("sender", {}).get("id", "?")
        lines.append(f"[{m.get('create_time','?')}] {sender}: {content}")
    return "\n".join(lines) if lines else "No messages found."


@make_tool(
    name="feishu_list_events",
    description="List calendar events from Feishu Calendar",
    input_schema={
        "type": "object",
        "properties": {
            "calendar_id": {
                "type": "string",
                "description": "Calendar ID (default: primary)",
                "default": "primary",
            },
            "start_time": {"type": "string", "description": "Start time (ISO 8601)"},
            "end_time": {"type": "string", "description": "End time (ISO 8601)"},
            "limit": {"type": "integer", "description": "Max results", "default": 20},
        },
    },
)
def feishu_list_events(
    calendar_id: str = "primary",
    start_time: str = "",
    end_time: str = "",
    limit: int = 20,
) -> str:
    params: dict[str, Any] = {"limit": limit}
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    data = _feishu_get(f"/calendar/v4/calendars/{calendar_id}/events", params)
    items = data.get("data", {}).get("items", [])
    lines = []
    for e in items:
        s = e.get("start_time", {})
        en = e.get("end_time", {})
        lines.append(f"• {e.get('summary','(no title)')} | {s} — {en}")
    return "\n".join(lines) if lines else "No events found."


@make_tool(
    name="feishu_create_event",
    description="Create a calendar event in Feishu Calendar",
    input_schema={
        "type": "object",
        "properties": {
            "calendar_id": {"type": "string", "description": "Calendar ID", "default": "primary"},
            "summary": {"type": "string", "description": "Event title"},
            "start_time": {"type": "string", "description": "Start time (ISO 8601)"},
            "end_time": {"type": "string", "description": "End time (ISO 8601)"},
            "description": {"type": "string", "description": "Event description"},
            "attendees": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Attendee emails",
            },
        },
        "required": ["summary", "start_time", "end_time"],
    },
)
def feishu_create_event(
    calendar_id: str = "primary",
    summary: str = "",
    start_time: str = "",
    end_time: str = "",
    description: str = "",
    attendees: list[str] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "summary": summary,
        "start_time": {"timestamp": start_time, "timezone": "Asia/Shanghai"},
        "end_time": {"timestamp": end_time, "timezone": "Asia/Shanghai"},
    }
    if description:
        payload["description"] = description
    if attendees:
        payload["attendees"] = {
            "attendees": [
                {"type": "third_party", "third_party_email": e} for e in attendees
            ]
        }
    result = _feishu_post(f"/calendar/v4/calendars/{calendar_id}/events", payload)
    code = result.get("code", 0)
    if code != 0:
        return f"Error {code}: {result.get('msg', '')}"
    return f"Event created. event_id={result.get('data',{}).get('event',{}).get('event_id','N/A')}"


@make_tool(
    name="feishu_search_docs",
    description="Search Feishu documents by keyword",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search keyword"},
            "count": {"type": "integer", "description": "Max results", "default": 10},
        },
        "required": ["query"],
    },
)
def feishu_search_docs(query: str, count: int = 10) -> str:
    data = _feishu_post("/search/v1/object", {
        "search_key": query,
        "count": count,
        "types": ["doc", "docx", "sheet", "mindnote"],
    })
    items = data.get("data", {}).get("items", [])
    lines = []
    for item in items:
        obj = item.get("object", {})
        lines.append(
            f"• [{obj.get('type','?')}] {obj.get('title','(no title)')} "
            f"| {obj.get('token','?')}"
        )
    return "\n".join(lines) if lines else f"No docs found for '{query}'."


@make_tool(
    name="feishu_get_contact",
    description="Get a Feishu user contact by email",
    input_schema={
        "type": "object",
        "properties": {
            "email": {"type": "string", "description": "User email"},
        },
        "required": ["email"],
    },
)
def feishu_get_contact(email: str) -> str:
    data = _feishu_post("/contact/v3/users/batch_get_id", {
        "emails": [email],
    })
    users = data.get("data", {}).get("user_list", [])
    if not users or users[0].get("user_id") == "":
        return f"User not found: {email}"
    uid = users[0].get("user_id", "")
    user_data = _feishu_get(f"/contact/v3/users/{uid}", {"user_id_type": "open_id"})
    u = user_data.get("data", {}).get("user", {})
    return (
        f"name={u.get('name','?')}\n"
        f"open_id={u.get('open_id','?')}\n"
        f"email={u.get('email','?')}\n"
        f"mobile={u.get('mobile','?')}\n"
        f"department={u.get('department_id','?')}\n"
        f"avatar_url={u.get('avatar',{}).get('avatar_72','')}"
    )


class FeishuServer(MCPServer):
    name = "feishu"
    version = "1.0.0"
    TOOLS = [
        feishu_send_message,
        feishu_list_messages,
        feishu_list_events,
        feishu_create_event,
        feishu_search_docs,
        feishu_get_contact,
    ]


if __name__ == "__main__":
    server = FeishuServer(tools=FeishuServer.TOOLS)
    server.run()
