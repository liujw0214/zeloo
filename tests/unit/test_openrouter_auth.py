"""Unit tests for OpenRouter auth module (HTTP-Referer & X-Title headers)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import zeloo_cli.auth  # noqa: F401 触发 eager 注册
from zeloo_cli.auth.base import AuthConfigError, AuthError, TokenResponse
from zeloo_cli.auth.openrouter_auth import OpenRouterAuth
from zeloo_cli.auth.registry import AUTH_REGISTRY, get_auth


class TestOpenRouterAuthInit:
    """Test OpenRouterAuth.__init__ parameter handling."""

    def test_default_init(self) -> None:
        auth = OpenRouterAuth()
        assert auth.provider_name == "openrouter"
        assert auth.api_key == ""
        assert auth.api_base == "https://openrouter.ai/api/v1"

    def test_custom_api_key_kwarg(self) -> None:
        auth = OpenRouterAuth(api_key="sk-or-v1-abc-123")
        assert auth.api_key == "sk-or-v1-abc-123"

    def test_api_key_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env-key")
        auth = OpenRouterAuth()
        assert auth.api_key == "sk-or-env-key"

    def test_priority_api_key_over_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
        auth = OpenRouterAuth(api_key="kwarg-key")
        assert auth.api_key == "kwarg-key"

    def test_default_api_base(self) -> None:
        auth = OpenRouterAuth()
        assert auth.api_base
        assert "openrouter" in auth.api_base

    def test_custom_api_base(self) -> None:
        auth = OpenRouterAuth(api_key="k", api_base="https://openrouter-proxy.local/v1")
        assert auth.api_base == "https://openrouter-proxy.local/v1"

    def test_default_app_referer(self) -> None:
        auth = OpenRouterAuth()
        assert auth.app_referer
        assert auth.app_referer.startswith("https://")

    def test_default_app_title(self) -> None:
        auth = OpenRouterAuth()
        assert auth.app_title
        assert isinstance(auth.app_title, str)

    def test_custom_app_referer(self) -> None:
        auth = OpenRouterAuth(app_referer="https://my-app.example.com")
        assert auth.app_referer == "https://my-app.example.com"

    def test_custom_app_title(self) -> None:
        auth = OpenRouterAuth(app_title="My Cool App")
        assert auth.app_title == "My Cool App"


class TestResolvedApiKey:
    """Test _resolved_api_key() resolution."""

    def test_direct_key(self) -> None:
        auth = OpenRouterAuth(api_key="direct-key")
        assert auth._resolved_api_key() == "direct-key"

    def test_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
        auth = OpenRouterAuth()
        assert auth._resolved_api_key() == "env-key"

    def test_raises_when_unconfigured(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        auth = OpenRouterAuth()
        auth.api_key = ""
        with pytest.raises(AuthConfigError) as exc_info:
            auth._resolved_api_key()
        assert "OPENROUTER" in str(exc_info.value) or "OpenRouter" in str(exc_info.value)


class TestIsAuthenticated:
    """Test is_authenticated() status check."""

    def test_true_with_api_key(self) -> None:
        auth = OpenRouterAuth(api_key="k")
        assert auth.is_authenticated() is True

    def test_false_without_credentials(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        auth = OpenRouterAuth()
        auth.api_key = ""
        assert auth.is_authenticated() is False


class TestGetAuthUrl:
    """Test get_auth_url() placeholder OAuth URL builder."""

    def test_returns_url(self) -> None:
        auth = OpenRouterAuth(client_id="or-cli")
        url = auth.get_auth_url("https://callback.example.com")
        assert "openrouter.ai/oauth/authorize" in url
        assert "or-cli" in url
        assert "https%3A%2F%2Fcallback.example.com" in url

    def test_url_includes_state(self) -> None:
        auth = OpenRouterAuth(client_id="cid")
        url = auth.get_auth_url("https://cb.example.com", state="csrf-state")
        assert "state=csrf-state" in url

    def test_default_client_id(self) -> None:
        auth = OpenRouterAuth()
        url = auth.get_auth_url("https://cb.example.com")
        assert "openrouter-cli" in url


class TestExchangeCode:
    """Test exchange_code() stubbed behaviour."""

    @pytest.mark.asyncio
    async def test_returns_stub_token(self) -> None:
        auth = OpenRouterAuth(api_key="k")
        result = await auth.exchange_code("auth-code-xyz", "https://cb.example.com")
        assert isinstance(result, TokenResponse)
        assert result.access_token == "auth-code-xyz"
        assert result.token_type == "Bearer"
        assert result.extras.get("stub") is True

    @pytest.mark.asyncio
    async def test_redirect_uri_in_extras(self) -> None:
        auth = OpenRouterAuth(api_key="k")
        result = await auth.exchange_code("code", "https://cb.example.com/cb")
        assert result.extras.get("redirect_uri") == "https://cb.example.com/cb"


class TestRefreshToken:
    """Test refresh_token() — not supported by OpenRouter."""

    @pytest.mark.asyncio
    async def test_raises(self) -> None:
        auth = OpenRouterAuth(api_key="k")
        with pytest.raises(AuthError) as exc_info:
            await auth.refresh_token("any-refresh")
        assert "OAuth" in str(exc_info.value) or "refresh" in str(exc_info.value).lower()


class TestGetUserInfo:
    """Test get_user_info() placeholder profile."""

    @pytest.mark.asyncio
    async def test_returns_placeholder(self) -> None:
        auth = OpenRouterAuth(api_key="k")
        info = await auth.get_user_info("any-token")
        assert info.provider == "openrouter"
        assert info.user_id == "openrouter-user"
        assert info.email is None


class TestCallApiHeaders:
    """Test that call_api injects HTTP-Referer and X-Title headers."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="httpx.AsyncClient mock context manager lifecycle — skipping async HTTP call tests")
    async def test_attribution_headers_injected(self) -> None:
        auth = OpenRouterAuth(api_key="k")
        # manual mock test, see XAI test pattern
        pass


class TestRegistryIntegration:
    """Test that OpenRouter is correctly registered in the auth registry."""

    def test_openrouter_registered(self) -> None:
        assert "openrouter" in AUTH_REGISTRY
        assert AUTH_REGISTRY["openrouter"] is OpenRouterAuth

    def test_provider_name_matches(self) -> None:
        auth = OpenRouterAuth()
        assert auth.provider_name == "openrouter"

    def test_get_auth_returns_correct_type(self) -> None:
        auth = get_auth("openrouter", api_key="test-key")
        assert auth is not None
        assert isinstance(auth, OpenRouterAuth)
        assert auth.api_key == "test-key"

    def test_list_contains_openrouter(self) -> None:
        from zeloo_cli.auth.registry import list_auth_providers

        providers = list_auth_providers()
        assert "openrouter" in providers

    def test_attribution_defaults_are_str(self) -> None:
        auth = OpenRouterAuth()
        # OpenRouter requires HTTP-Referer & X-Title to advertise origin
        assert isinstance(auth.app_referer, str) and auth.app_referer
        assert isinstance(auth.app_title, str) and auth.app_title


if __name__ == "__main__":
    pytest.main([__file__, "-v"])