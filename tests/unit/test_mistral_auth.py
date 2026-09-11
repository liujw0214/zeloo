"""Unit tests for Mistral auth module (full OAuth support)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import zeloo_cli.auth  # noqa: F401 触发 eager 注册
from zeloo_cli.auth.base import AuthConfigError, AuthError, TokenResponse
from zeloo_cli.auth.mistral_auth import MistralAuth
from zeloo_cli.auth.registry import AUTH_REGISTRY, get_auth


class TestMistralAuthInit:
    """Test MistralAuth.__init__ parameter handling."""

    def test_default_init(self) -> None:
        auth = MistralAuth()
        assert auth.provider_name == "mistral"
        assert auth.api_key == ""
        assert auth.api_base == "https://api.mistral.ai/v1"

    def test_custom_api_key_kwarg(self) -> None:
        auth = MistralAuth(api_key="mistral-key-abc")
        assert auth.api_key == "mistral-key-abc"

    def test_api_key_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "mistral-env-key")
        auth = MistralAuth()
        assert auth.api_key == "mistral-env-key"

    def test_priority_api_key_over_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "env-key")
        auth = MistralAuth(api_key="kwarg-key")
        assert auth.api_key == "kwarg-key"

    def test_client_id_fallback(self) -> None:
        auth = MistralAuth(client_id="mistral-cid")
        assert auth.api_key == "mistral-cid"

    def test_default_api_base(self) -> None:
        auth = MistralAuth()
        assert auth.api_base
        assert "mistral" in auth.api_base

    def test_custom_api_base(self) -> None:
        auth = MistralAuth(api_key="k", api_base="https://mistral-proxy.local/v1")
        assert auth.api_base == "https://mistral-proxy.local/v1"


class TestResolvedApiKey:
    """Test _resolved_api_key() resolution."""

    def test_direct_key(self) -> None:
        auth = MistralAuth(api_key="direct-key")
        assert auth._resolved_api_key() == "direct-key"

    def test_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "env-key")
        auth = MistralAuth()
        assert auth._resolved_api_key() == "env-key"

    def test_raises_when_unconfigured(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        auth = MistralAuth()
        auth.api_key = ""
        with pytest.raises(AuthConfigError) as exc_info:
            auth._resolved_api_key()
        assert "MISTRAL" in str(exc_info.value) or "Mistral" in str(exc_info.value)


class TestIsAuthenticated:
    """Test is_authenticated() status check."""

    def test_true_with_api_key(self) -> None:
        auth = MistralAuth(api_key="k")
        assert auth.is_authenticated() is True

    def test_false_without_credentials(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        auth = MistralAuth()
        auth.api_key = ""
        assert auth.is_authenticated() is False


class TestGetAuthUrl:
    """Test get_auth_url() — Mistral supports full OAuth."""

    def test_raises_without_client_id(self) -> None:
        auth = MistralAuth(api_key="k")
        with pytest.raises(AuthConfigError) as exc_info:
            auth.get_auth_url("https://callback.example.com")
        assert "client_id" in str(exc_info.value)

    def test_returns_url_with_client_id(self) -> None:
        auth = MistralAuth(client_id="my-client-id")
        url = auth.get_auth_url("https://callback.example.com")
        assert "auth.mistral.ai/oauth/authorize" in url
        assert "my-client-id" in url
        assert "https%3A%2F%2Fcallback.example.com" in url

    def test_url_includes_state(self) -> None:
        auth = MistralAuth(client_id="cid")
        url = auth.get_auth_url("https://cb.example.com", state="csrf-state")
        assert "state=csrf-state" in url

    def test_default_scope_present(self) -> None:
        auth = MistralAuth(client_id="cid")
        url = auth.get_auth_url("https://cb.example.com")
        assert "scope=" in url
        # scope contains "openid" by default
        assert "openid" in url or "api%3Aread" in url

    def test_custom_scope(self) -> None:
        auth = MistralAuth(client_id="cid")
        url = auth.get_auth_url("https://cb.example.com", scope="custom:scope")
        assert "custom%3Ascope" in url or "custom:scope" in url


class TestExchangeCode:
    """Test exchange_code() full OAuth token exchange."""

    @pytest.mark.asyncio
    async def test_raises_without_client_id(self) -> None:
        auth = MistralAuth(api_key="k")
        with pytest.raises(AuthConfigError):
            await auth.exchange_code("code123", "https://cb.example.com")

    @pytest.mark.asyncio
    async def test_parses_token_response(self) -> None:
        auth = MistralAuth(client_id="cid", client_secret="csec")
        mock_response = {
            "access_token": "mistral_access_tok",
            "refresh_token": "mistral_refresh_tok",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "openid api:read",
        }

        async def fake_post_form(url, data, headers=None, timeout=30.0):
            return mock_response

        with mock.patch.object(auth, "_post_form", fake_post_form):
            result = await auth.exchange_code("auth-code-789", "https://cb.example.com")

        assert result.access_token == "mistral_access_tok"
        assert result.refresh_token == "mistral_refresh_tok"
        assert result.token_type == "Bearer"
        assert result.expires_in == 3600
        assert result.scope == "openid api:read"


class TestRefreshToken:
    """Test refresh_token() full OAuth refresh."""

    @pytest.mark.asyncio
    async def test_raises_without_client_id(self) -> None:
        auth = MistralAuth(api_key="k")
        with pytest.raises(AuthConfigError):
            await auth.refresh_token("refresh-tok")

    @pytest.mark.asyncio
    async def test_parses_refreshed_token(self) -> None:
        auth = MistralAuth(client_id="cid", client_secret="csec")
        mock_response = {
            "access_token": "mistral_new_access",
            "refresh_token": "mistral_new_refresh",
            "token_type": "Bearer",
            "expires_in": 7200,
        }

        async def fake_post_form(url, data, headers=None, timeout=30.0):
            return mock_response

        with mock.patch.object(auth, "_post_form", fake_post_form):
            result = await auth.refresh_token("old-refresh-tok")

        assert result.access_token == "mistral_new_access"
        assert result.refresh_token == "mistral_new_refresh"


class TestParseTokenResponse:
    """Test _parse_token_response() shape."""

    def test_full_token_response(self) -> None:
        auth = MistralAuth(api_key="k")
        data = {
            "access_token": "mat",
            "refresh_token": "mrt",
            "token_type": "Bearer",
            "expires_in": 1800,
            "scope": "openid api:read api:write",
            "extra": "keep",
        }
        result = auth._parse_token_response(data)
        assert result.access_token == "mat"
        assert result.refresh_token == "mrt"
        assert result.expires_in == 1800
        assert result.extras.get("extra") == "keep"

    def test_missing_access_token_raises(self) -> None:
        auth = MistralAuth(api_key="k")
        with pytest.raises(AuthError) as exc_info:
            auth._parse_token_response({"error": "invalid_grant"})
        assert "access_token" in str(exc_info.value)

    def test_no_expiry_is_none(self) -> None:
        auth = MistralAuth(api_key="k")
        result = auth._parse_token_response({"access_token": "tok"})
        assert result.expires_in is None
        assert result.refresh_token is None


class TestRegistryIntegration:
    """Test that Mistral is correctly registered in the auth registry."""

    def test_mistral_registered(self) -> None:
        assert "mistral" in AUTH_REGISTRY
        assert AUTH_REGISTRY["mistral"] is MistralAuth

    def test_provider_name_matches(self) -> None:
        auth = MistralAuth()
        assert auth.provider_name == "mistral"

    def test_get_auth_returns_correct_type(self) -> None:
        auth = get_auth("mistral", api_key="test-key")
        assert auth is not None
        assert isinstance(auth, MistralAuth)
        assert auth.api_key == "test-key"

    def test_list_contains_mistral(self) -> None:
        from zeloo_cli.auth.registry import list_auth_providers

        providers = list_auth_providers()
        assert "mistral" in providers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])