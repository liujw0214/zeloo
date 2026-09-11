"""Twilio MCP Server — SMS / WhatsApp / Voice via Twilio API."""

from __future__ import annotations

import os
from typing import Any

from optional_mcps.base import MCPServer, make_tool


def _get_client() -> Any:
    from twilio.rest import Client
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        raise RuntimeError("Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.")
    return Client(auth_token, account_sid)


@make_tool(
    name="twilio_send_sms",
    description="Send an SMS message via Twilio",
    input_schema={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient phone number (E.164)"},
            "from_": {"type": "string", "description": "Twilio phone number (E.164)"},
            "body": {"type": "string", "description": "Message text"},
        },
        "required": ["to", "from_", "body"],
    },
)
def twilio_send_sms(to: str, from_: str, body: str) -> str:
    client = _get_client()
    msg = client.messages.create(to=to, from_=from_, body=body)
    return f"SMS sent. SID={msg.sid}, status={msg.status}"


@make_tool(
    name="twilio_send_whatsapp",
    description="Send a WhatsApp message via Twilio",
    input_schema={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient WhatsApp number (whatsapp:)"},
            "from_": {"type": "string", "description": "Twilio WhatsApp number (whatsapp:)"},
            "body": {"type": "string", "description": "Message text"},
        },
        "required": ["to", "from_", "body"],
    },
)
def twilio_send_whatsapp(to: str, from_: str, body: str) -> str:
    client = _get_client()
    msg = client.messages.create(to=f"whatsapp:{to}", from_=f"whatsapp:{from_}", body=body)
    return f"WhatsApp sent. SID={msg.sid}, status={msg.status}"


@make_tool(
    name="twilio_list_messages",
    description="List recent SMS messages",
    input_schema={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Filter by recipient"},
            "from_": {"type": "string", "description": "Filter by sender"},
            "limit": {"type": "integer", "description": "Max results (default 20)", "default": 20},
        },
    },
)
def twilio_list_messages(to: str = "", from_: str = "", limit: int = 20) -> str:
    client = _get_client()
    filters: dict[str, Any] = {"limit": limit}
    if to:
        filters["to"] = to
    if from_:
        filters["from_"] = from_
    msgs = client.messages.list(**filters)
    lines = []
    for m in msgs[:limit]:
        lines.append(
            f"{m.sid} | {m.direction} | {m.from_} → {m.to} | "
            f"{m.status} | {m.date_sent}"
        )
        lines.append(f"  {m.body[:80]}")
    return "\n".join(lines) if lines else "No messages found."


@make_tool(
    name="twilio_get_message",
    description="Get a single message by SID",
    input_schema={
        "type": "object",
        "properties": {
            "sid": {"type": "string", "description": "Message SID"},
        },
        "required": ["sid"],
    },
)
def twilio_get_message(sid: str) -> str:
    client = _get_client()
    msg = client.messages(sid).fetch()
    return (
        f"SID={msg.sid}\nFrom={msg.from_}\nTo={msg.to}\n"
        f"Status={msg.status}\nDate={msg.date_sent}\nBody={msg.body}"
    )


@make_tool(
    name="twilio_create_call",
    description="Initiate a voice call via Twilio",
    input_schema={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient phone (E.164)"},
            "from_": {"type": "string", "description": "Twilio phone (E.164)"},
            "url": {"type": "string", "description": "TwiML URL for the call"},
        },
        "required": ["to", "from_", "url"],
    },
)
def twilio_create_call(to: str, from_: str, url: str) -> str:
    client = _get_client()
    call = client.calls.create(to=to, from_=from_, url=url)
    return f"Call initiated. SID={call.sid}, status={call.status}"


@make_tool(
    name="twilio_list_calls",
    description="List recent voice calls",
    input_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Filter by status (completed, busy, failed, etc.)",
            },
            "limit": {"type": "integer", "description": "Max results", "default": 20},
        },
    },
)
def twilio_list_calls(status: str = "", limit: int = 20) -> str:
    client = _get_client()
    filters: dict[str, Any] = {"limit": limit}
    if status:
        filters["status"] = status
    calls = client.calls.stream(**filters)
    lines = []
    for c in calls:
        if len(lines) >= limit:
            break
        lines.append(
            f"{c.sid} | {c.from_formatted} → {c.to_formatted} | "
            f"{c.status} | {c.duration}s"
        )
    return "\n".join(lines) if lines else "No calls found."


class TwilioServer(MCPServer):
    name = "twilio"
    version = "1.0.0"
    TOOLS = [
        twilio_send_sms,
        twilio_send_whatsapp,
        twilio_list_messages,
        twilio_get_message,
        twilio_create_call,
        twilio_list_calls,
    ]


if __name__ == "__main__":
    server = TwilioServer(tools=TwilioServer.TOOLS)
    server.run()
