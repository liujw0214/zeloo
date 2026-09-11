"""Tests for transport adapters."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent.transports.anthropic_adapter import AnthropicAdapter
from agent.transports.base import (
    AuthenticationError,
    RateLimitError,
    Response,
    TransportAdapter,
)


class TestResponse:
    def test_response_total_tokens(self):
        r = Response(content="hello", usage_in=100, usage_out=50)
        assert r.total_tokens == 150

    def test_response_defaults(self):
        r = Response(content="test")
        assert r.content == "test"
        assert r.raw == {}
        assert r.model == ""
        assert r.finish_reason == ""
        assert r.usage_in == 0
        assert r.usage_out == 0
        assert r.tool_calls == []
        assert r.error is None


class TestTransportAdapter:
    def test_transport_adapter_has_abstract_methods(self):
        class BadAdapter(TransportAdapter):
            pass

        with pytest.raises(TypeError):
            BadAdapter()

    def test_transport_adapter_supports_feature(self):
        class MockAdapter(TransportAdapter):
            name = "mock"
            supports_streaming = True
            supports_vision = True
            supports_tools = False

            def chat_completion(self, messages, model, **kwargs):
                return Response(content="")

            def validate_credentials(self):
                return True

        adapter = MockAdapter()
        assert adapter.supports_feature("streaming") is True
        assert adapter.supports_feature("vision") is True
        assert adapter.supports_feature("tools") is False
        assert adapter.supports_feature("unknown") is False

    def test_transport_adapter_get_default_model(self):
        class MockAdapter(TransportAdapter):
            name = "mock"

            def chat_completion(self, messages, model, **kwargs):
                return Response(content="")

            def validate_credentials(self):
                return True

        adapter = MockAdapter()
        assert adapter.get_default_model() == ""

    def test_transport_adapter_format_error(self):
        class MockAdapter(TransportAdapter):
            name = "mock"

            def chat_completion(self, messages, model, **kwargs):
                return Response(content="")

            def validate_credentials(self):
                return True

        adapter = MockAdapter()
        assert adapter.format_error(ValueError("bad input")) == "bad input"


class TestAnthropicAdapterInit:
    def test_init_default_base_url(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        assert adapter.api_key == "sk-test"
        assert adapter.base_url == "https://api.anthropic.com"
        assert adapter.max_retries == 3
        assert adapter.timeout == 60.0

    def test_init_custom_base_url(self):
        adapter = AnthropicAdapter(
            api_key="sk-test",
            base_url="https://custom.anthropic.com",
            max_retries=5,
            timeout=30.0,
        )
        assert adapter.base_url == "https://custom.anthropic.com"
        assert adapter.max_retries == 5
        assert adapter.timeout == 30.0

    def test_adapter_attributes(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        assert adapter.name == "anthropic"
        assert adapter.supports_streaming is True
        assert adapter.supports_vision is True
        assert adapter.supports_tools is True
        assert adapter.max_context_tokens == 200000

    def test_get_default_model(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        assert adapter.get_default_model() == "claude-3-5-sonnet-20241022"

    def test_supports_feature_vision(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        assert adapter.supports_feature("vision") is True

    def test_supports_feature_tools(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        assert adapter.supports_feature("tools") is True

    def test_supports_feature_streaming(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        assert adapter.supports_feature("streaming") is True

    def test_supports_feature_unknown(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        assert adapter.supports_feature("json_mode") is False


class TestAnthropicMessageConversion:
    def test_convert_user_message(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        msgs = [{"role": "user", "content": "hello"}]
        converted = adapter._convert_messages(msgs)
        assert converted == [{"role": "user", "content": "hello"}]

    def test_convert_system_message(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        msgs = [{"role": "system", "content": "You are helpful."}]
        converted = adapter._convert_messages(msgs)
        assert converted == [{"role": "user", "content": "[System]\nYou are helpful."}]

    def test_convert_assistant_message_plain(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        msgs = [{"role": "assistant", "content": "I am here."}]
        converted = adapter._convert_messages(msgs)
        assert converted == [{"role": "assistant", "content": "I am here."}]

    def test_convert_assistant_message_with_tool_call(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        msgs = [{
            "role": "assistant",
            "content": "Let me search.",
            "tool_calls": [{
                "id": "call_abc",
                "type": "function",
                "function": {
                    "name": "web_search",
                    "arguments": json.dumps({"query": "weather"}),
                },
            }],
        }]
        converted = adapter._convert_messages(msgs)
        assert len(converted) == 1
        item = converted[0]
        assert item["role"] == "assistant"
        assert isinstance(item["content"], list)
        assert item["content"][0]["type"] == "text"
        assert item["content"][0]["text"] == "Let me search."
        assert item["content"][1]["type"] == "tool_use"
        assert item["content"][1]["id"] == "call_abc"
        assert item["content"][1]["name"] == "web_search"
        assert item["content"][1]["input"] == '{"query": "weather"}'

    def test_convert_tool_message(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        msgs = [{
            "role": "tool",
            "tool_call_id": "call_abc",
            "content": "The weather is sunny.",
        }]
        converted = adapter._convert_messages(msgs)
        assert converted == [{
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "call_abc",
                "content": "The weather is sunny.",
            }],
        }]

    def test_convert_assistant_tool_call_empty_content(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        msgs = [{
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_abc",
                "type": "function",
                "function": {
                    "name": "file_read",
                    "arguments": json.dumps({"path": "/a/b.txt"}),
                },
            }],
        }]
        converted = adapter._convert_messages(msgs)
        item = converted[0]
        assert item["role"] == "assistant"
        assert len(item["content"]) == 1
        assert item["content"][0]["type"] == "tool_use"
        assert item["content"][0]["name"] == "file_read"


class TestAnthropicToolConversion:
    def test_convert_tools_basic(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        tools = [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                    },
                    "required": ["city"],
                },
            },
        }]
        converted = adapter._convert_tools(tools)
        assert len(converted) == 1
        assert converted[0]["name"] == "get_weather"
        assert converted[0]["description"] == "Get current weather"
        assert converted[0]["input_schema"]["properties"]["city"]["type"] == "string"

    def test_convert_tools_no_function_key(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        tools = [{
            "name": "simple_tool",
            "description": "Does something",
            "parameters": {"type": "object"},
        }]
        converted = adapter._convert_tools(tools)
        assert converted[0]["name"] == "simple_tool"
        assert converted[0]["input_schema"] == {"type": "object", "properties": {}}


class TestAnthropicPayload:
    def test_build_payload_basic(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        msgs = [{"role": "user", "content": "hello"}]
        payload = adapter._build_payload(msgs, "claude-3-5-sonnet-20241022", None)
        assert payload["model"] == "claude-3-5-sonnet-20241022"
        assert len(payload["messages"]) == 1
        assert payload["max_tokens"] == 4096
        assert payload["temperature"] == 0.0

    def test_build_payload_with_tools(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        msgs = [{"role": "user", "content": "hello"}]
        tools = [{
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search",
                "parameters": {"type": "object"},
            },
        }]
        payload = adapter._build_payload(msgs, "claude-3-5-sonnet-20241022", tools)
        assert "tools" in payload
        assert payload["tools"][0]["name"] == "search"

    def test_build_payload_with_system(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        msgs = [{"role": "user", "content": "hello"}]
        payload = adapter._build_payload(msgs, "claude-3-5-sonnet-20241022", None, system="You are a cat.")  # noqa: E501
        assert payload["messages"][0]["role"] == "user"
        assert "System: You are a cat." in payload["messages"][0]["content"]

    def test_build_payload_custom_kwargs(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        msgs = [{"role": "user", "content": "hello"}]
        payload = adapter._build_payload(
            msgs, "claude-3-5-sonnet-20241022", None,
            max_tokens=1000, temperature=0.7
        )
        assert payload["max_tokens"] == 1000
        assert payload["temperature"] == 0.7


class TestAnthropicResponseParsing:
    def test_parse_text_response(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        raw = {
            "content": [{"type": "text", "text": "Hello, world!"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "model": "claude-3-5-sonnet-20241022",
        }
        resp = adapter._parse_response(raw, "claude-3-5-sonnet-20241022")
        assert resp.content == "Hello, world!"
        assert resp.finish_reason == "end_turn"
        assert resp.usage_in == 10
        assert resp.usage_out == 5
        assert resp.tool_calls == []
        assert resp.raw == raw

    def test_parse_tool_use_response(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        raw = {
            "content": [
                {"type": "text", "text": "Let me check."},
                {
                    "type": "tool_use",
                    "id": "toolu_abc123",
                    "name": "web_search",
                    "input": {"query": "pizza"},
                },
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 50, "output_tokens": 30},
            "model": "claude-3-5-sonnet-20241022",
        }
        resp = adapter._parse_response(raw, "claude-3-5-sonnet-20241022")
        assert resp.content == "Let me check."
        assert resp.finish_reason == "tool_use"
        assert len(resp.tool_calls) == 1
        tc = resp.tool_calls[0]
        assert tc["id"] == "toolu_abc123"
        assert tc["function"]["name"] == "web_search"
        assert tc["function"]["arguments"] == '{"query": "pizza"}'

    def test_parse_empty_response(self):
        adapter = AnthropicAdapter(api_key="sk-test")
        raw = {
            "content": [],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        resp = adapter._parse_response(raw, "claude-3-5-sonnet-20241022")
        assert resp.content == ""
        assert resp.finish_reason == "end_turn"


class TestAnthropicCredentialValidation:
    @patch("httpx.Client")
    def test_validate_credentials_success(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client_cls.return_value = mock_client

        adapter = AnthropicAdapter(api_key="sk-valid")
        result = adapter.validate_credentials()
        assert result is True

    @patch("httpx.Client")
    def test_validate_credentials_failure(self, mock_client_cls):
        import httpx
        mock_req = MagicMock(spec=httpx.Request)
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "rate limited", request=mock_req, response=MagicMock(status_code=429)
        )
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client_cls.return_value = mock_client

        adapter = AnthropicAdapter(api_key="sk-invalid")
        result = adapter.validate_credentials()
        assert result is False


class TestAnthropicExceptions:
    @patch("httpx.Client")
    def test_chat_completion_auth_error(self, mock_client_cls):
        import httpx
        mock_req = MagicMock(spec=httpx.Request)
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "unauthorized", request=mock_req, response=MagicMock(status_code=401)
        )
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client_cls.return_value = mock_client

        adapter = AnthropicAdapter(api_key="sk-bad")
        with pytest.raises(AuthenticationError):
            adapter.chat_completion([{"role": "user", "content": "hi"}], "claude-3-5-sonnet-20241022")  # noqa: E501

    @patch("httpx.Client")
    def test_chat_completion_rate_limit_error(self, mock_client_cls):
        import httpx
        mock_req = MagicMock(spec=httpx.Request)
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "rate limited", request=mock_req, response=MagicMock(status_code=429)
        )
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client_cls.return_value = mock_client

        adapter = AnthropicAdapter(api_key="sk-test")
        with pytest.raises(RateLimitError):
            adapter.chat_completion([{"role": "user", "content": "hi"}], "claude-3-5-sonnet-20241022")  # noqa: E501

    @patch("httpx.Client")
    def test_chat_completion_success(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = {
            "content": [{"type": "text", "text": "Hello!"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 3},
            "model": "claude-3-5-sonnet-20241022",
        }
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client_cls.return_value = mock_client

        adapter = AnthropicAdapter(api_key="sk-test")
        resp = adapter.chat_completion(
            [{"role": "user", "content": "hi"}], "claude-3-5-sonnet-20241022"
        )
        assert resp.content == "Hello!"
        assert resp.usage_in == 5
        assert resp.usage_out == 3
