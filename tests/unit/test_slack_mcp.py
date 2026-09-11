"""Tests for optional_mcps.slack MCP server."""

from optional_mcps.slack import TOOLS, _format_channel, _format_message


class TestSlackFormatting:
    def test_format_channel_public(self):
        ch = {
            "name": "general",
            "id": "C001",
            "is_private": False,
            "num_members": 42,
            "topic": {"value": "Company-wide announcements"},
            "created": 1609459200,
        }
        result = _format_channel(ch)
        assert "#general" in result
        assert "C001" in result
        assert "public" in result
        assert "42" in result

    def test_format_channel_private(self):
        ch = {
            "name": "secret",
            "id": "C999",
            "is_private": True,
            "num_members": 5,
            "topic": {},
            "created": 1609459200,
        }
        result = _format_channel(ch)
        assert "#secret" in result
        assert "private" in result

    def test_format_channel_no_topic(self):
        ch = {"name": "random", "id": "C1", "is_private": False, "num_members": 10}
        result = _format_channel(ch)
        assert "#random" in result
        assert "Topic:" not in result

    def test_format_message_basic(self):
        msg = {
            "user": "U001",
            "ts": "1609459200.000001",
            "text": "Hello world",
        }
        users = {"U001": "Alice"}
        result = _format_message(msg, users)
        assert "Alice" in result
        assert "Hello world" in result
        assert "1609459200.000001" in result

    def test_format_message_thread_reply(self):
        msg = {
            "user": "U002",
            "ts": "1609459200.000002",
            "text": "Reply here",
            "thread_ts": "1609459200.000001",
        }
        result = _format_message(msg, {})
        assert "thread reply" in result

    def test_format_message_unknown_user(self):
        msg = {"user": "U999", "ts": "1", "text": "Hi"}
        users = {}
        result = _format_message(msg, users)
        assert "U999" in result


class TestSlackToolsList:
    def test_tools_defined(self):
        assert len(TOOLS) == 5
        names = [t.name for t in TOOLS]
        assert "slack_list_channels" in names
        assert "slack_post_message" in names
        assert "slack_search_messages" in names
        assert "slack_get_channel_history" in names
        assert "slack_list_users" in names

    def test_all_have_handlers(self):
        for tool in TOOLS:
            assert callable(tool.handler), f"{tool.name} has no handler"
