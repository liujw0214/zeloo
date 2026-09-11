"""Unit tests for DeepSeek auth module."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import zeloo_cli.auth  # noqa: F401 触发 eager 注册
from zeloo_cli.auth.base import AuthConfigError, AuthError, TokenResponse
from zeloo_cli.auth.deepseek_auth import DeepSeekAuth
from zeloo_cli.auth.registry import AUTH_REGISTRY, get_auth


class TestDeepSeekAuthInit:
    """Test DeepSeekAuth.__init__ parameter handling."""

    def test_default_init(self) -> None:
        auth = DeepSeekAuth()
        assert auth.provider_name == "deepseek"
        assert auth.api_key == ""
        assert auth.api_base == "https://api.deepseek.com/v1"

    def test_custom_api_key_kwarg(self) -> None:
        auth = DeepSeekAuth(api_key="sk-deepseek-123")
        assert auth.api_key == "sk-deepseek-123"

    def test_api_key_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-deepseek")
        auth = DeepSeekAuth()
        assert auth.api_key == "sk-env-deepseek"

    def test_priority_api_key_over_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
        auth = DeepSeekAuth(api_key="kwarg-key")
        assert auth.api_key == "kwarg-key"

    def test_client_id_stored(self) -> None:
        auth = DeepSeekAuth(client_id="ds-client-id")
        # DeepSeek 不使用 client_id 作为 api_key 回退（仅作保留字段）
        assert auth.client_id == "ds-client-id"

    def test_custom_api_base(self) -> None:
        auth = DeepSeekAuth(api_key="k", api_base="https://custom.deepseek.com/v1")
        assert auth.api_base == "https://custom.deepseek.com/v1"

    def test_default_api_base(self) -> None:
        auth = DeepSeekAuth()
        assert auth.api_base  # 非空
        assert "deepseek" in auth.api_base

    def test_client_secret_stored(self) -> None:
        auth = DeepSeekAuth(client_secret="ds-secret")
        assert auth.client_secret == "ds-secret"


class TestResolvedApiKey:
    """Test _resolved_api_key() resolution."""

    def test_direct_key(self) -> None:
        auth = DeepSeekAuth(api_key="direct-key")
        assert auth._resolved_api_key() == "direct-key"

    def test_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
        auth = DeepSeekAuth()
        assert auth._resolved_api_key() == "env-key"

    def test_raises_when_unconfigured(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        auth = DeepSeekAuth()
        auth.api_key = ""
        with pytest.raises(AuthConfigError) as exc_info:
            auth._resolved_api_key()
        assert "DEEPSEEK_API_KEY" in str(exc_info.value) or "DeepSeek" in str(exc_info.value)


class TestIsAuthenticated:
    """Test is_authenticated() status check."""

    def test_true_with_api_key(self) -> None:
        auth = DeepSeekAuth(api_key="k")
        assert auth.is_authenticated() is True

    def test_false_without_credentials(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        auth = DeepSeekAuth()
        auth.api_key = ""
        assert auth.is_authenticated() is False


class TestGetAuthUrl:
    """Test get_auth_url() placeholder OAuth URL builder."""

    def test_returns_url(self) -> None:
        auth = DeepSeekAuth(client_id="ds-cli")
        url = auth.get_auth_url("https://callback.example.com")
        assert "deepseek.com/oauth/authorize" in url
        assert "ds-cli" in url
        assert "https%3A%2F%2Fcallback.example.com" in url

    def test_url_includes_state(self) -> None:
        auth = DeepSeekAuth(client_id="cid")
        url = auth.get_auth_url("https://cb.example.com", state="xyz")
        assert "state=xyz" in url

    def test_default_client_id(self) -> None:
        auth = DeepSeekAuth()
        url = auth.get_auth_url("https://cb.example.com")
        assert "deepseek-cli" in url


class TestExchangeCode:
    """Test exchange_code() stubbed behaviour."""

    @pytest.mark.asyncio
    async def test_returns_stub_token(self) -> None:
        auth = DeepSeekAuth(api_key="k")
        result = await auth.exchange_code("auth-code-abc", "https://cb.example.com")
        assert isinstance(result, TokenResponse)
        assert result.access_token == "auth-code-abc"
        assert result.token_type == "Bearer"
        assert result.extras.get("stub") is True

    @pytest.mark.asyncio
    async def test_redirect_uri_in_extras(self) -> None:
        auth = DeepSeekAuth(api_key="k")
        result = await auth.exchange_code("code", "https://cb.example.com/cb")
        assert result.extras.get("redirect_uri") == "https://cb.example.com/cb"


class TestRefreshToken:
    """Test refresh_token() — not supported by DeepSeek."""

    @pytest.mark.asyncio
    async def test_raises(self) -> None:
        auth = DeepSeekAuth(api_key="k")
        with pytest.raises(AuthError) as exc_info:
            await auth.refresh_token("any-refresh")
        assert "OAuth" in str(exc_info.value) or "refresh" in str(exc_info.value).lower()


class TestGetUserInfo:
    """Test get_user_info() placeholder profile."""

    @pytest.mark.asyncio
    async def test_returns_placeholder(self) -> None:
        auth = DeepSeekAuth(api_key="k")
        info = await auth.get_user_info("any-token")
        assert info.provider == "deepseek"
        assert info.user_id == "deepseek-user"
        assert info.email is None


class TestParseTokenResponse:
    """DeepSeek stub: token parsing not exercised; verify TokenResponse shape."""

    def test_full_token_shape(self) -> None:
        resp = TokenResponse(
            access_token="at",
            token_type="Bearer",
            refresh_token="rt",
            expires_in=3600,
            scope="api:read api:write",
        )
        assert resp.access_token == "at"
        assert resp.refresh_token == "rt"
        assert resp.expires_in == 3600


class TestRegistryIntegration:
    """Test that DeepSeek is correctly registered in the auth registry."""

    def test_deepseek_registered(self) -> None:
        assert "deepseek" in AUTH_REGISTRY
        assert AUTH_REGISTRY["deepseek"] is DeepSeekAuth

    def test_provider_name_matches(self) -> None:
        auth = DeepSeekAuth()
        assert auth.provider_name == "deepseek"

    def test_get_auth_returns_correct_type(self) -> None:
        auth = get_auth("deepseek", api_key="test-key")
        assert auth is not None
        assert isinstance(auth, DeepSeekAuth)
        assert auth.api_key == "test-key"

    def test_list_contains_deepseek(self) -> None:
        from zeloo_cli.auth.registry import list_auth_providers

        providers = list_auth_providers()
        assert "deepseek" in providers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])