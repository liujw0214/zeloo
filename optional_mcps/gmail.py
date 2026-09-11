"""Gmail MCP server — exposes Gmail API as MCP tools over stdio JSON-RPC."""

from __future__ import annotations

import base64
import os

from optional_mcps.base import MCPServer, make_tool

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


GMAIL_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"


def _get_gmail_headers() -> dict[str, str]:
    token = os.environ.get("GMAIL_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _gmail_get(path: str, params: dict | None = None) -> dict:
    url = f"{GMAIL_BASE_URL}/{path.lstrip('/')}"
    headers = _get_gmail_headers()
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=headers, params=params or {})
        resp.raise_for_status()
        return resp.json()


def _gmail_post(path: str, data: dict | None = None) -> dict:
    url = f"{GMAIL_BASE_URL}/{path.lstrip('/')}"
    headers = _get_gmail_headers()
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, json=data or {})
        resp.raise_for_status()
        return resp.json()


def _format_message(msg: dict) -> str:
    msg_id = msg.get("id", "?")
    thread_id = msg.get("threadId", "?")
    snippet = msg.get("snippet", "(no preview)")
    headers = msg.get("payload", {}).get("headers", [])
    msg_from = ""
    subject = ""
    date = ""
    for h in headers:
        h_name = h.get("name", "").lower()
        if h_name == "from":
            msg_from = h.get("value", "")
        elif h_name == "subject":
            subject = h.get("value", "")
        elif h_name == "date":
            date = h.get("value", "")
    return (
        f"ID: {msg_id} | Thread: {thread_id}\n"
        f"From: {msg_from}\n"
        f"Subject: {subject}\n"
        f"Date: {date}\n"
        f"Snippet: {snippet[:200]}"
    )


def _format_label(label: dict) -> str:
    return (
        f"ID: {label.get('id', '?')} | Name: {label.get('name', '?')} | "
        f"Type: {label.get('type', '?')} | "
        f"Messages: {label.get('messagesTotal', 0)} | "
        f"Unread: {label.get('messagesUnread', 0)}"
    )


if _HTTPX_AVAILABLE:

    @make_tool(
        name="gmail_list_messages",
        description="List recent messages",
        input_schema={
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "default": 20},
            },
        },
    )
    def gmail_list_messages(max_results: int = 20) -> str:
        data = _gmail_get("messages", {"maxResults": max_results})
        messages = data.get("messages", [])
        if not messages:
            return "No messages found."
        result = []
        for m in messages:
            try:
                msg_url = f"messages/{m.get('id')}"
                msg_url += "?format=metadata"
                msg_url += "&metadataHeaders=From"
                msg_url += "&metadataHeaders=Subject"
                msg_url += "&metadataHeaders=Date"
                msg_data = _gmail_get(msg_url)
                result.append(_format_message(msg_data))
            except Exception:
                result.append(f"ID: {m.get('id', '?')} (could not fetch details)")
        return "\n\n---\n\n".join(result)

    @make_tool(
        name="gmail_get_message",
        description="Get full details of a message",
        input_schema={
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Message ID"},
            },
            "required": ["message_id"],
        },
    )
    def gmail_get_message(message_id: str) -> str:
        data = _gmail_get(f"messages/{message_id}")
        payload = data.get("payload", {})
        headers = payload.get("headers", [])
        msg_from = ""
        msg_to = ""
        subject = ""
        date = ""
        for h in headers:
            h_name = h.get("name", "").lower()
            if h_name == "from":
                msg_from = h.get("value", "")
            elif h_name == "to":
                msg_to = h.get("value", "")
            elif h_name == "subject":
                subject = h.get("value", "")
            elif h_name == "date":
                date = h.get("value", "")
        body_text = ""
        parts = payload.get("parts", [])
        if parts:
            for part in parts:
                if part.get("mimeType") == "text/plain":
                    body_data = part.get("body", {}).get("data", "")
                    if body_data:
                        body_bytes = body_data.encode()
                        body_text = base64.urlsafe_b64decode(body_bytes).decode(
                            "utf-8", errors="replace"
                        )
                        break
        else:
            body_data = payload.get("body", {}).get("data", "")
            if body_data:
                body_bytes = body_data.encode()
                body_text = base64.urlsafe_b64decode(body_bytes).decode(
                    "utf-8", errors="replace"
                )
        return (
            f"From: {msg_from}\n"
            f"To: {msg_to}\n"
            f"Subject: {subject}\n"
            f"Date: {date}\n"
            f"Body:\n{body_text[:2000]}"
        )

    @make_tool(
        name="gmail_search_messages",
        description="Search messages by query",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    )
    def gmail_search_messages(query: str, max_results: int = 10) -> str:
        data = _gmail_get("messages", {"q": query, "maxResults": max_results})
        messages = data.get("messages", [])
        if not messages:
            return f"No messages found for query: {query}"
        result = []
        for m in messages:
            try:
                msg_url = f"messages/{m.get('id')}"
                msg_url += "?format=metadata"
                msg_url += "&metadataHeaders=From"
                msg_url += "&metadataHeaders=Subject"
                msg_url += "&metadataHeaders=Date"
                msg_data = _gmail_get(msg_url)
                result.append(_format_message(msg_data))
            except Exception:
                result.append(f"ID: {m.get('id', '?')} (could not fetch details)")
        return f"Found {len(result)} message(s) for '{query}':\n\n" + "\n\n---\n\n".join(result)

    @make_tool(
        name="gmail_send_message",
        description="Send an email message",
        input_schema={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body text"},
                "cc": {"type": "string", "description": "CC recipients (comma-separated)"},
            },
            "required": ["to", "subject", "body"],
        },
    )
    def gmail_send_message(to: str, subject: str, body: str, cc: str = "") -> str:
        import email.utils
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart()
        msg["To"] = to
        msg["Subject"] = subject
        msg["From"] = email.utils.formataddr(("Sender", os.environ.get("GMAIL_FROM", "me")))
        if cc:
            msg["Cc"] = cc
        msg.attach(MIMEText(body, "plain"))
        raw_bytes = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        raw = raw_bytes.replace("+", "-").replace("/", "_").rstrip("=")
        data = _gmail_post("messages/send", {"raw": raw})
        return (
            f"Message sent successfully!\n"
            f"ID: {data.get('id', 'unknown')}\n"
            f"Thread ID: {data.get('threadId', 'unknown')}"
        )

    @make_tool(
        name="gmail_list_labels",
        description="List all email labels",
        input_schema={
            "type": "object",
            "properties": {},
        },
    )
    def gmail_list_labels() -> str:
        data = _gmail_get("labels")
        labels = data.get("labels", [])
        if not labels:
            return "No labels found."
        return "\n".join(_format_label(label_item) for label_item in labels)

    TOOLS: list = [
        gmail_list_messages,
        gmail_get_message,
        gmail_search_messages,
        gmail_send_message,
        gmail_list_labels,
    ]

else:
    TOOLS = []


def main() -> None:
    server = MCPServer(name="gmail", version="1.0.0", tools=TOOLS)
    server.run()


if __name__ == "__main__":
    main()
