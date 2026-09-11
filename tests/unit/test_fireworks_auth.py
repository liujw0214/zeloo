"""Unit tests for Fireworks auth module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import zeloo_cli.auth  # noqa: F401 触发 eager 注册
from zeloo_cli.auth.base import AuthConfigError, AuthError, TokenResponse
from zeloo_cli.auth.fireworks_auth import FireworksAuth
from zeloo_cli.auth.registry import AUTH_REGISTRY, get_auth


class TestFireworksAuthInit:
    """Test FireworksAuth.__init__ parameter handling."""

    def test_default_init(self) -> None:
        auth = FireworksAuth()
        assert auth.provider_name == "fireworks"
        assert auth.api_key == ""
        assert auth.api_base == "https://api.fireworks.ai/inference/v1"

    def test_custom_api_key_kwarg(self) -> None:
        auth = FireworksAuth(api_key="fw-abc-123")
        assert auth.api_key == "fw-abc-123"

    def test_api_key_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("FIREWORKS_API_KEY", "fw-env-key")
        auth = FireworksAuth()
        assert auth.api_key == "fw-env-key"

    def test_priority_api_key_over_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("FIREWORKS_API_KEY", "env-key")
        auth = FireworksAuth(api_key="kwarg-key")
        assert auth.api_key == "kwarg-key"

    def test_client_id_fallback(self) -> None:
        auth = FireworksAuth(client_id="fw-id")
        assert auth.api_key == "fw-id"

    def test_default_api_base(self) -> None:
        auth = FireworksAuth()
        assert auth.api_base
        assert "fireworks" in auth.api_base

    def test_custom_api_base(self) -> None:
        auth = FireworksAuth(api_key="k", api_base="https://fw-proxy.local/v1")
        assert auth.api_base == "https://fw-proxy.local/v1"

    def test_account_id_from_kwargs(self) -> None:
        auth = FireworksAuth(api_key="k", account_id="acct-123")
        assert auth.account_id == "acct-123"


class TestResolvedApiKey:
    """Test _resolved_api_key() resolution."""

    def test_direct_key(self) -> None:
        auth = FireworksAuth(api_key="direct-key")
        assert auth._resolved_api_key() == "direct-key"

    def test_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("FIREWORKS_API_KEY", "env-key")
        auth = FireworksAuth()
        assert auth._resolved_api_key() == "env-key"

    def test_raises_when_unconfigured(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
        auth = FireworksAuth()
        auth.api_key = ""
        with pytest.raises(AuthConfigError) as exc_info:
            auth._resolved_api_key()
        assert "FIREWORKS" in str(exc_info.value) or "Fireworks" in str(exc_info.value)


class TestIsAuthenticated:
    """Test is_authenticated() status check."""

    def test_true_with_api_key(self) -> None:
        auth = FireworksAuth(api_key="k")
        assert auth.is_authenticated() is True

    def test_false_without_credentials(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
        auth = FireworksAuth()
        auth.api_key = ""
        assert auth.is_authenticated() is False


class TestGetAuthUrl:
    """Test get_auth_url() — Fireworks does not support OAuth."""

    def test_raises_config_error(self) -> None:
        auth = FireworksAuth(api_key="k")
        with pytest.raises(AuthConfigError) as exc_info:
            auth.get_auth_url("https://cb.example.com")
        # 应当提示 OAuth 不支持
        assert "OAuth" in str(exc_info.value) or "API key" in str(exc_info.value)


class TestExchangeCode:
    """Test exchange_code() — not supported."""

    @pytest.mark.asyncio
    async def test_raises_config_error(self) -> None:
        auth = FireworksAuth(api_key="k")
        with pytest.raises(AuthConfigError) as exc_info:
            await auth.exchange_code("auth-code", "https://cb.example.com")
        assert "OAuth" in str(exc_info.value) or "authorization" in str(exc_info.value).lower()


class TestRefreshToken:
    """Test refresh_token() — not supported."""

    @pytest.mark.asyncio
    async def test_raises_config_error(self) -> None:
        auth = FireworksAuth(api_key="k")
        with pytest.raises(AuthConfigError) as exc_info:
            await auth.refresh_token("any")
        assert "OAuth" in str(exc_info.value) or "refresh" in str(exc_info.value).lower()


class TestGetUserInfo:
    """Test get_user_info() — returns fallback on error."""

    @pytest.mark.asyncio
    async def test_returns_placeholder(self) -> None:
        auth = FireworksAuth(api_key="k")
        info = await auth.get_user_info("any-token")
        assert info.provider == "fireworks"
        assert info.user_id == "fireworks-user"
        assert info.email is None


class TestRegistryIntegration:
    """Test that Fireworks is correctly registered in the auth registry."""

    def test_fireworks_registered(self) -> None:
        assert "fireworks" in AUTH_REGISTRY
        assert AUTH_REGISTRY["fireworks"] is FireworksAuth

    def test_provider_name_matches(self) -> None:
        auth = FireworksAuth()
        assert auth.provider_name == "fireworks"

    def test_get_auth_returns_correct_type(self) -> None:
        auth = get_auth("fireworks", api_key="test-key")
        assert auth is not None
        assert isinstance(auth, FireworksAuth)
        assert auth.api_key == "test-key"

    def test_list_contains_fireworks(self) -> None:
        from zeloo_cli.auth.registry import list_auth_providers

        providers = list_auth_providers()
        assert "fireworks" in providers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])