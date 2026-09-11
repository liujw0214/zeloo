"""Unit tests for Groq auth module."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import zeloo_cli.auth  # noqa: F401 触发 eager 注册
from zeloo_cli.auth.base import AuthConfigError, AuthError, TokenResponse
from zeloo_cli.auth.groq_auth import GroqAuth
from zeloo_cli.auth.registry import AUTH_REGISTRY, get_auth


class TestGroqAuthInit:
    """Test GroqAuth.__init__ parameter handling."""

    def test_default_init(self) -> None:
        auth = GroqAuth()
        assert auth.provider_name == "groq"
        assert auth.api_key == ""
        assert auth.api_base == "https://api.groq.com/openai/v1"

    def test_custom_api_key_kwarg(self) -> None:
        auth = GroqAuth(api_key="gsk-abc-123")
        assert auth.api_key == "gsk-abc-123"

    def test_api_key_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "gsk-env-key")
        auth = GroqAuth()
        assert auth.api_key == "gsk-env-key"

    def test_priority_api_key_over_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "env-key")
        auth = GroqAuth(api_key="kwarg-key")
        assert auth.api_key == "kwarg-key"

    def test_client_id_fallback(self) -> None:
        auth = GroqAuth(client_id="groq-id")
        assert auth.api_key == "groq-id"

    def test_client_secret_fallback(self) -> None:
        auth = GroqAuth(client_secret="groq-secret")
        assert auth.api_key == "groq-secret"

    def test_default_api_base(self) -> None:
        auth = GroqAuth()
        assert auth.api_base
        assert "groq" in auth.api_base

    def test_custom_api_base(self) -> None:
        auth = GroqAuth(api_key="k", api_base="https://groq-proxy.local/v1")
        assert auth.api_base == "https://groq-proxy.local/v1"


class TestResolvedApiKey:
    """Test _resolved_api_key() resolution."""

    def test_direct_key(self) -> None:
        auth = GroqAuth(api_key="direct-key")
        assert auth._resolved_api_key() == "direct-key"

    def test_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "env-key")
        auth = GroqAuth()
        assert auth._resolved_api_key() == "env-key"

    def test_raises_when_unconfigured(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        auth = GroqAuth()
        auth.api_key = ""
        with pytest.raises(AuthConfigError) as exc_info:
            auth._resolved_api_key()
        assert "GROQ" in str(exc_info.value) or "Groq" in str(exc_info.value)


class TestIsAuthenticated:
    """Test is_authenticated() status check."""

    def test_true_with_api_key(self) -> None:
        auth = GroqAuth(api_key="k")
        assert auth.is_authenticated() is True

    def test_false_without_credentials(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        auth = GroqAuth()
        auth.api_key = ""
        assert auth.is_authenticated() is False


class TestGetAuthUrl:
    """Test get_auth_url() placeholder OAuth URL builder."""

    def test_returns_url(self) -> None:
        auth = GroqAuth(client_id="groq-cli")
        url = auth.get_auth_url("https://callback.example.com")
        assert "groq.com/oauth/authorize" in url
        assert "groq-cli" in url
        assert "https%3A%2F%2Fcallback.example.com" in url

    def test_url_includes_state(self) -> None:
        auth = GroqAuth(client_id="cid")
        url = auth.get_auth_url("https://cb.example.com", state="csrf-tok")
        assert "state=csrf-tok" in url

    def test_default_client_id(self) -> None:
        auth = GroqAuth()
        url = auth.get_auth_url("https://cb.example.com")
        assert "groq-cli" in url


class TestExchangeCode:
    """Test exchange_code() stubbed behaviour."""

    @pytest.mark.asyncio
    async def test_returns_stub_token(self) -> None:
        auth = GroqAuth(api_key="k")
        result = await auth.exchange_code("auth-code-xyz", "https://cb.example.com")
        assert isinstance(result, TokenResponse)
        assert result.access_token == "auth-code-xyz"
        assert result.token_type == "Bearer"
        assert result.extras.get("stub") is True

    @pytest.mark.asyncio
    async def test_redirect_uri_in_extras(self) -> None:
        auth = GroqAuth(api_key="k")
        result = await auth.exchange_code("code", "https://cb.example.com/cb")
        assert result.extras.get("redirect_uri") == "https://cb.example.com/cb"


class TestRefreshToken:
    """Test refresh_token() — Groq does not support refresh tokens."""

    @pytest.mark.asyncio
    async def test_raises(self) -> None:
        auth = GroqAuth(api_key="k")
        with pytest.raises(AuthError) as exc_info:
            await auth.refresh_token("any-refresh")
        assert "refresh" in str(exc_info.value).lower() or "OAuth" in str(exc_info.value)


class TestGetUserInfo:
    """Test get_user_info() placeholder profile."""

    @pytest.mark.asyncio
    async def test_returns_placeholder(self) -> None:
        auth = GroqAuth(api_key="k")
        info = await auth.get_user_info("any-token")
        assert info.provider == "groq"
        assert info.user_id == "groq-user"
        assert info.email is None


class TestRegistryIntegration:
    """Test that Groq is correctly registered in the auth registry."""

    def test_groq_registered(self) -> None:
        assert "groq" in AUTH_REGISTRY
        assert AUTH_REGISTRY["groq"] is GroqAuth

    def test_provider_name_matches(self) -> None:
        auth = GroqAuth()
        assert auth.provider_name == "groq"

    def test_get_auth_returns_correct_type(self) -> None:
        auth = get_auth("groq", api_key="test-key")
        assert auth is not None
        assert isinstance(auth, GroqAuth)
        assert auth.api_key == "test-key"

    def test_list_contains_groq(self) -> None:
        from zeloo_cli.auth.registry import list_auth_providers

        providers = list_auth_providers()
        assert "groq" in providers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])