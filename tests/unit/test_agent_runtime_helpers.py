"""Tests for agent_runtime_helpers."""

from unittest.mock import MagicMock

from agent.agent_runtime_helpers import (
    MODEL_CONTEXT_WINDOWS,
    build_tool_context,
    compute_token_estimate,
    parse_tool_calls_from_response,
    resolve_model_config,
    resolve_session_id,
    sanitize_api_key_for_log,
    should_compress_context,
    truncate_messages_for_context,
)


class TestComputeTokenEstimate:
    def test_empty_string(self):
        assert compute_token_estimate("") == 0

    def test_short_text(self):
        result = compute_token_estimate("hello world")
        assert isinstance(result, int)
        assert result > 0

    def test_longer_text(self):
        text = " ".join(["word"] * 100)
        result = compute_token_estimate(text)
        assert result > 20


class TestResolveSessionId:
    def test_returns_string(self):
        sid = resolve_session_id("cli", "user1")
        assert isinstance(sid, str)
        assert len(sid) == 24

    def test_deterministic(self):
        sid1 = resolve_session_id("cli", "user1")
        sid2 = resolve_session_id("cli", "user1")
        assert sid1 == sid2

    def test_different_platform(self):
        sid1 = resolve_session_id("cli", "user1")
        sid2 = resolve_session_id("telegram", "user1")
        assert sid1 != sid2


class TestSanitizeApiKeyForLog:
    def test_masks_key(self):
        masked = sanitize_api_key_for_log("sk-1234567890abcdef")
        assert "sk-1" in masked
        assert "..." in masked
        assert "abcdef" not in masked

    def test_short_key(self):
        masked = sanitize_api_key_for_log("sk-abcdef")
        assert "sk-a..." in masked
        assert "bcdef" not in masked


class TestParseToolCallsFromResponse:
    def test_no_tools(self):
        result = parse_tool_calls_from_response("Hello, how can I help you?")
        assert result == []

    def test_xml_tool_call(self):
        text = '<tool_call>\n  <name>web_search</name>\n  <args>{"query": "weather"}</args>\n</tool_call>'  # noqa: E501
        result = parse_tool_calls_from_response(text)
        assert len(result) == 1
        assert result[0]["name"] == "web_search"

    def test_multiple_tool_calls(self):
        text = (
            '<tool_call>\n  <name>read</name>\n  <args>{"path": "/a"}</args>\n</tool_call>'
            '<tool_call>\n  <name>write</name>\n  <args>{"path": "/b", "content": "hi"}</args>\n</tool_call>'  # noqa: E501
        )
        result = parse_tool_calls_from_response(text)
        assert len(result) == 2


class TestTruncateMessagesForContext:
    def test_empty_list(self):
        result = truncate_messages_for_context([], 1000)
        assert result == []

    def test_under_budget(self):
        msgs = [{"role": "user", "content": "hi"}]
        result = truncate_messages_for_context(msgs, 128000)
        assert result == msgs

    def test_over_budget_removes_oldest(self):
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply1"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "reply2"},
        ]
        result = truncate_messages_for_context(msgs, 1)
        assert len(result) <= len(msgs)
        assert result[-1]["content"] in ["second", "reply2"]


class TestResolveModelConfig:
    def test_returns_model_config(self):
        mock_agent = MagicMock()
        mock_agent.model = "gpt-4o"
        mock_agent.provider = "openai"
        cfg = resolve_model_config(mock_agent)
        assert cfg.model == "gpt-4o"
        assert cfg.provider == "openai"


class TestShouldCompressContext:
    def test_false_for_small_context(self):
        mock_agent = MagicMock()
        mock_agent.messages = [{"role": "user", "content": "hi"}]
        mock_agent.max_messages = 40
        assert should_compress_context(mock_agent) is False


class TestBuildToolContext:
    def test_empty_tools(self):
        ctx = build_tool_context([])
        assert "tools" in ctx
        assert isinstance(ctx["tools"], list)

    def test_single_tool(self):
        mock_tool = MagicMock()
        mock_tool.name = "search"
        mock_tool.description = "Search the web"
        mock_tool.input_schema = {"type": "object", "properties": {}}
        ctx = build_tool_context([mock_tool])
        assert len(ctx["tools"]) == 1
        assert ctx["tools"][0]["function"]["name"] == "search"


class TestModelContextWindows:
    def test_has_required_models(self):
        assert "gpt-4o" in MODEL_CONTEXT_WINDOWS
        assert "claude-3-5-sonnet" in MODEL_CONTEXT_WINDOWS
        assert "deepseek-chat" in MODEL_CONTEXT_WINDOWS

    def test_values_are_integers(self):
        for model, tokens in MODEL_CONTEXT_WINDOWS.items():
            assert isinstance(tokens, int), f"{model} has non-int value {tokens}"
            assert tokens > 0, f"{model} has zero/negative tokens"
