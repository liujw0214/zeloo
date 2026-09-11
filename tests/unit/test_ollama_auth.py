"""Unit tests for Ollama auth module (anonymous-friendly)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import zeloo_cli.auth  # noqa: F401 触发 eager 注册
from zeloo_cli.auth.base import AuthError, TokenResponse
from zeloo_cli.auth.ollama_auth import OllamaAuth
from zeloo_cli.auth.registry import AUTH_REGISTRY, get_auth


class TestOllamaAuthInit:
    """Test OllamaAuth.__init__ parameter handling."""

    def test_default_init(self) -> None:
        auth = OllamaAuth()
        assert auth.provider_name == "ollama"
        assert auth.api_key == ""
        assert auth.api_base == "http://localhost:11434/v1"

    def test_custom_api_key_kwarg(self) -> None:
        auth = OllamaAuth(api_key="ollama-abc-123")
        assert auth.api_key == "ollama-abc-123"

    def test_api_key_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("OLLAMA_API_KEY", "ollama-env-key")
        auth = OllamaAuth()
        assert auth.api_key == "ollama-env-key"

    def test_priority_api_key_over_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("OLLAMA_API_KEY", "env-key")
        auth = OllamaAuth(api_key="kwarg-key")
        assert auth.api_key == "kwarg-key"

    def test_default_api_base(self) -> None:
        auth = OllamaAuth()
        assert auth.api_base
        assert "localhost" in auth.api_base or "ollama" in auth.api_base.lower()

    def test_custom_api_base(self) -> None:
        auth = OllamaAuth(api_key="k", api_base="http://ollama.local:9999/v1")
        assert auth.api_base == "http://ollama.local:9999/v1"


class TestResolvedApiKey:
    """Test _resolved_api_key() — empty when not configured."""

    def test_returns_empty_when_no_key(self) -> None:
        auth = OllamaAuth()
        assert auth._resolved_api_key() == ""

    def test_returns_key_when_set(self) -> None:
        auth = OllamaAuth(api_key="explicit-key")
        assert auth._resolved_api_key() == "explicit-key"

    def test_returns_env_key(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("OLLAMA_API_KEY", "env-key")
        auth = OllamaAuth()
        assert auth._resolved_api_key() == "env-key"


class TestIsAuthenticated:
    """Test is_authenticated() — always True for Ollama."""

    def test_authenticated_by_default(self) -> None:
        auth = OllamaAuth()
        # Ollama 默认 is_authenticated=True
        assert auth.is_authenticated() is True

    def test_authenticated_with_api_key(self) -> None:
        auth = OllamaAuth(api_key="k")
        assert auth.is_authenticated() is True

    def test_authenticated_without_api_key(self) -> None:
        auth = OllamaAuth()
        auth.api_key = ""
        assert auth.is_authenticated() is True


class TestGetAuthUrl:
    """Test get_auth_url() — placeholder OAuth URL."""

    def test_returns_local_url(self) -> None:
        auth = OllamaAuth()
        url = auth.get_auth_url("https://callback.example.com")
        assert "auth" in url.lower()
        assert "https%3A%2F%2Fcallback.example.com" in url or "callback" in url

    def test_includes_state(self) -> None:
        auth = OllamaAuth()
        url = auth.get_auth_url("https://cb.example.com", state="xyz")
        assert "state=xyz" in url


class TestExchangeCode:
    """Test exchange_code() stubbed."""

    @pytest.mark.asyncio
    async def test_returns_empty_token(self) -> None:
        auth = OllamaAuth(api_key="k")
        result = await auth.exchange_code("code", "https://cb.example.com")
        assert isinstance(result, TokenResponse)
        assert result.access_token == ""
        assert result.extras.get("stub") is True


class TestRefreshToken:
    """Test refresh_token() — not supported."""

    @pytest.mark.asyncio
    async def test_raises(self) -> None:
        auth = OllamaAuth(api_key="k")
        with pytest.raises(AuthError) as exc_info:
            await auth.refresh_token("any")
        assert "OAuth" in str(exc_info.value) or "refresh" in str(exc_info.value).lower()


class TestGetUserInfo:
    """Test get_user_info() local placeholder."""

    @pytest.mark.asyncio
    async def test_returns_local_user(self) -> None:
        auth = OllamaAuth(api_key="k")
        info = await auth.get_user_info("any-token")
        assert info.provider == "ollama"
        assert info.user_id == "ollama-local"
        assert info.name == "Ollama Local User"
        assert info.raw.get("api_base") == auth.api_base


class TestRegistryIntegration:
    """Test that Ollama is correctly registered in the auth registry."""

    def test_ollama_registered(self) -> None:
        assert "ollama" in AUTH_REGISTRY
        assert AUTH_REGISTRY["ollama"] is OllamaAuth

    def test_provider_name_matches(self) -> None:
        auth = OllamaAuth()
        assert auth.provider_name == "ollama"

    def test_get_auth_returns_correct_type(self) -> None:
        auth = get_auth("ollama", api_key="test-key")
        assert auth is not None
        assert isinstance(auth, OllamaAuth)
        assert auth.api_key == "test-key"

    def test_list_contains_ollama(self) -> None:
        from zeloo_cli.auth.registry import list_auth_providers

        providers = list_auth_providers()
        assert "ollama" in providers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])