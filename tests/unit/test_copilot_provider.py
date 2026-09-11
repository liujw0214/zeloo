"""Tests for model_providers/copilot.py — GitHub Copilot provider."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


class TestGitHubCopilotBasics:
    def test_module_imports(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="test-key-123456789012345678")
        assert provider.name == "copilot"
        assert provider.default_model == "gpt-4o"
        assert provider.base_url == "https://api.githubcopilot.com/chat/completions"
        assert provider.supports_function_calling is True
        assert provider.supports_streaming is True
        assert provider.supports_vision is False

    def test_instantiation_with_explicit_key(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="explicit-key-12345")
        assert provider.api_key == "explicit-key-12345"

    def test_instantiation_with_env_var(self) -> None:
        with patch.dict(os.environ, {"GITHUB_TOKEN": "env-key-12345"}):
            from model_providers.copilot import GitHubCopilotProvider

            provider = GitHubCopilotProvider()
            assert provider.api_key == "env-key-12345"

    def test_instantiation_without_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            from model_providers.copilot import GitHubCopilotProvider

            provider = GitHubCopilotProvider()
            assert provider.api_key == ""


class TestGitHubCopilotRegistry:
    def test_provider_in_registry(self) -> None:
        from model_providers import list_providers

        providers = list_providers()
        assert "copilot" in providers

    def test_get_provider_returns_instance(self) -> None:
        from model_providers import get_provider

        provider = get_provider("copilot", api_key="test-key-12345")
        assert provider is not None
        assert provider.name == "copilot"

    def test_import_from_package(self) -> None:
        from model_providers import GitHubCopilotProvider

        assert GitHubCopilotProvider is not None
        assert hasattr(GitHubCopilotProvider, "chat_completion")


class TestGitHubCopilotValidateCredentials:
    def test_empty_key_invalid(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="")
        assert provider.validate_credentials() is False

    def test_valid_key_network_success(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="valid-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.Client") as mock_client_class:
            mock_client_class.return_value.__enter__.return_value.post.return_value = mock_resp
            assert provider.validate_credentials() is True

    def test_auth_error_returns_false(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="bad-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        with patch("httpx.Client") as mock_client_class:
            mock_client_class.return_value.__enter__.return_value.post.return_value = mock_resp
            assert provider.validate_credentials() is False

    def test_network_error_returns_false(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="test-key")
        with patch("httpx.Client") as mock_client_class:
            mock_client_class.return_value.__enter__.return_value.post.side_effect = (
                ConnectionError("network down")
            )
            assert provider.validate_credentials() is False


class TestGitHubCopilotCostEstimation:
    def test_estimate_cost_known_model(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="test")
        cost = provider.estimate_cost(1000, 1000, "gpt-4o")
        assert cost == pytest.approx(0.0125, rel=0.01)

    def test_estimate_cost_unknown_model(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="test")
        cost = provider.estimate_cost(1000, 1000, "unknown-model")
        assert cost > 0

    def test_estimate_cost_gpt_4_turbo(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="test")
        cost = provider.estimate_cost(1000, 1000, "gpt-4-turbo")
        assert cost > 0


class TestGitHubCopilotChatCompletion:
    def test_chat_requires_api_key(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="")
        with pytest.raises(RuntimeError, match="GitHub token not set"):
            provider.chat_completion([{"role": "user", "content": "hi"}])

    def test_chat_sends_correct_payload(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="valid-token-12345")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {"content": "Hello!", "tool_calls": None},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }
        mock_resp.raise_for_status.return_value = None
        with patch("httpx.Client") as mock_client_class:
            mock_client_class.return_value.__enter__.return_value.post.return_value = mock_resp
            response = provider.chat_completion([{"role": "user", "content": "hi"}])
        assert response.content == "Hello!"
        assert response.model == "gpt-4o"
        assert response.provider == "copilot"
        assert response.prompt_tokens == 5
        assert response.completion_tokens == 3

    def test_chat_with_custom_model(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="valid-token-12345")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [
                {"message": {"content": "ok", "tool_calls": None}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        mock_resp.raise_for_status.return_value = None
        with patch("httpx.Client") as mock_client_class:
            mock_client_class.return_value.__enter__.return_value.post.return_value = mock_resp
            response = provider.chat_completion(
                [{"role": "user", "content": "hi"}],
                model="gpt-4-turbo",
                temperature=0.5,
            )
        assert response.model == "gpt-4-turbo"

    def test_chat_with_tools(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="valid-token-12345")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [
                {"message": {"content": "ok", "tool_calls": None}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        mock_resp.raise_for_status.return_value = None
        tools = [{"type": "function", "function": {"name": "test"}}]
        with patch("httpx.Client") as mock_client_class:
            mock_client_class.return_value.__enter__.return_value.post.return_value = mock_resp
            response = provider.chat_completion(
                [{"role": "user", "content": "hi"}], tools=tools
            )
        assert response.tool_calls is None
        call_kwargs = mock_client_class.return_value.__enter__.return_value.post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json"))
        assert "tools" in payload

    def test_chat_includes_auth_headers(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="ghp_testkey12345")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [
                {"message": {"content": "ok", "tool_calls": None}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        mock_resp.raise_for_status.return_value = None
        with patch("httpx.Client") as mock_client_class:
            mock_client_class.return_value.__enter__.return_value.post.return_value = mock_resp
            provider.chat_completion([{"role": "user", "content": "hi"}])
            call_kwargs = mock_client_class.return_value.__enter__.return_value.post.call_args
            headers = call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers"))
        assert "Authorization" in headers
        assert "Bearer ghp_testkey12345" in headers["Authorization"]
        assert "X-GitHub-Token" in headers
        assert headers["X-GitHub-Token"] == "ghp_testkey12345"

    def test_chat_http_error_raises(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="valid-token-12345")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = RuntimeError("500 Server Error")
        with patch("httpx.Client") as mock_client_class:
            mock_client_class.return_value.__enter__.return_value.post.return_value = mock_resp
            with pytest.raises(RuntimeError, match="500 Server Error"):
                provider.chat_completion([{"role": "user", "content": "hi"}])

    def test_chat_with_tool_calls_response(self) -> None:
        from model_providers.copilot import GitHubCopilotProvider

        provider = GitHubCopilotProvider(api_key="valid-token-12345")
        tool_calls_data = [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "Beijing"}'},
            }
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {"content": None, "tool_calls": tool_calls_data},
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_resp.raise_for_status.return_value = None
        with patch("httpx.Client") as mock_client_class:
            mock_client_class.return_value.__enter__.return_value.post.return_value = mock_resp
            response = provider.chat_completion([{"role": "user", "content": "weather?"}])
        assert response.finish_reason == "tool_calls"
        assert response.tool_calls == tool_calls_data