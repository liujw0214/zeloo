"""Tests for Gmail MCP server."""

from optional_mcps.gmail import (
    TOOLS,
    _format_label,
    _format_message,
)


class TestGmailFormatting:
    def test_format_message(self):
        msg = {
            "id": "msg123",
            "threadId": "thread456",
            "snippet": "This is a preview of the message",
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Subject", "value": "Test Subject"},
                    {"name": "Date", "value": "Mon, 7 Sep 2026 10:00:00 +0000"},
                ]
            },
        }
        result = _format_message(msg)
        assert "msg123" in result
        assert "thread456" in result
        assert "sender@example.com" in result
        assert "Test Subject" in result
        assert "Mon, 7 Sep 2026" in result
        assert "This is a preview" in result

    def test_format_message_minimal(self):
        msg = {"id": "x", "threadId": "y"}
        result = _format_message(msg)
        assert "x" in result
        assert "y" in result
        assert "(no preview)" in result

    def test_format_message_missing_headers(self):
        msg = {"id": "123", "snippet": "test", "payload": {"headers": []}}
        result = _format_message(msg)
        assert "123" in result

    def test_format_label(self):
        label = {
            "id": "INBOX",
            "name": "INBOX",
            "type": "system",
            "messagesTotal": 100,
            "messagesUnread": 5,
        }
        result = _format_label(label)
        assert "INBOX" in result
        assert "system" in result
        assert "100" in result
        assert "5" in result

    def test_format_label_minimal(self):
        label = {"id": "STARRED"}
        result = _format_label(label)
        assert "STARRED" in result


class TestGmailToolsList:
    def test_tools_defined(self):
        assert len(TOOLS) == 5
        names = [t.name for t in TOOLS]
        assert "gmail_list_messages" in names
        assert "gmail_get_message" in names
        assert "gmail_search_messages" in names
        assert "gmail_send_message" in names
        assert "gmail_list_labels" in names

    def test_all_tools_have_handlers(self):
        for tool in TOOLS:
            assert callable(tool.handler), f"{tool.name} has no handler"

    def test_all_tools_have_descriptions(self):
        for tool in TOOLS:
            assert tool.description, f"{tool.name} has no description"

    def test_all_tools_have_input_schema(self):
        for tool in TOOLS:
            assert tool.input_schema, f"{tool.name} has no input_schema"
