"""Unit tests for Together AI auth module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import zeloo_cli.auth  # noqa: F401 触发 eager 注册
from zeloo_cli.auth.base import AuthConfigError, AuthError, TokenResponse
from zeloo_cli.auth.together_auth import TogetherAuth
from zeloo_cli.auth.registry import AUTH_REGISTRY, get_auth


class TestTogetherAuthInit:
    """Test TogetherAuth.__init__ parameter handling."""

    def test_default_init(self) -> None:
        auth = TogetherAuth()
        assert auth.provider_name == "together"
        assert auth.api_key == ""
        assert auth.api_base == "https://api.together.xyz/v1"

    def test_custom_api_key_kwarg(self) -> None:
        auth = TogetherAuth(api_key="together-abc-123")
        assert auth.api_key == "together-abc-123"

    def test_api_key_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("TOGETHER_API_KEY", "together-env-key")
        auth = TogetherAuth()
        assert auth.api_key == "together-env-key"

    def test_priority_api_key_over_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("TOGETHER_API_KEY", "env-key")
        auth = TogetherAuth(api_key="kwarg-key")
        assert auth.api_key == "kwarg-key"

    def test_client_id_fallback(self) -> None:
        auth = TogetherAuth(client_id="tgr-id")
        assert auth.api_key == "tgr-id"

    def test_default_api_base(self) -> None:
        auth = TogetherAuth()
        assert auth.api_base
        assert "together" in auth.api_base

    def test_custom_api_base(self) -> None:
        auth = TogetherAuth(api_key="k", api_base="https://together-proxy.local/v1")
        assert auth.api_base == "https://together-proxy.local/v1"

    def test_organization_from_kwargs(self) -> None:
        auth = TogetherAuth(api_key="k", organization="my-org")
        assert auth.organization == "my-org"


class TestResolvedApiKey:
    """Test _resolved_api_key() resolution."""

    def test_direct_key(self) -> None:
        auth = TogetherAuth(api_key="direct-key")
        assert auth._resolved_api_key() == "direct-key"

    def test_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("TOGETHER_API_KEY", "env-key")
        auth = TogetherAuth()
        assert auth._resolved_api_key() == "env-key"

    def test_raises_when_unconfigured(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
        auth = TogetherAuth()
        auth.api_key = ""
        with pytest.raises(AuthConfigError) as exc_info:
            auth._resolved_api_key()
        assert "TOGETHER" in str(exc_info.value) or "Together" in str(exc_info.value)


class TestIsAuthenticated:
    """Test is_authenticated() status check."""

    def test_true_with_api_key(self) -> None:
        auth = TogetherAuth(api_key="k")
        assert auth.is_authenticated() is True

    def test_false_without_credentials(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
        auth = TogetherAuth()
        auth.api_key = ""
        assert auth.is_authenticated() is False


class TestGetAuthUrl:
    """Test get_auth_url() — Together does not support OAuth."""

    def test_raises_config_error(self) -> None:
        auth = TogetherAuth(api_key="k")
        with pytest.raises(AuthConfigError) as exc_info:
            auth.get_auth_url("https://cb.example.com")
        assert "OAuth" in str(exc_info.value) or "API key" in str(exc_info.value)


class TestExchangeCode:
    """Test exchange_code() — not supported."""

    @pytest.mark.asyncio
    async def test_raises_config_error(self) -> None:
        auth = TogetherAuth(api_key="k")
        with pytest.raises(AuthConfigError) as exc_info:
            await auth.exchange_code("auth-code", "https://cb.example.com")
        assert "OAuth" in str(exc_info.value) or "authorization" in str(exc_info.value).lower()


class TestRefreshToken:
    """Test refresh_token() — not supported."""

    @pytest.mark.asyncio
    async def test_raises_config_error(self) -> None:
        auth = TogetherAuth(api_key="k")
        with pytest.raises(AuthConfigError) as exc_info:
            await auth.refresh_token("any")
        assert "OAuth" in str(exc_info.value) or "refresh" in str(exc_info.value).lower()


class TestGetUserInfo:
    """Test get_user_info() — placeholder profile."""

    @pytest.mark.asyncio
    async def test_returns_placeholder(self) -> None:
        auth = TogetherAuth(api_key="k")
        info = await auth.get_user_info("any-token")
        assert info.provider == "together"
        assert info.user_id == "together-user"
        assert info.email is None


class TestRegistryIntegration:
    """Test that Together is correctly registered in the auth registry."""

    def test_together_registered(self) -> None:
        assert "together" in AUTH_REGISTRY
        assert AUTH_REGISTRY["together"] is TogetherAuth

    def test_provider_name_matches(self) -> None:
        auth = TogetherAuth()
        assert auth.provider_name == "together"

    def test_get_auth_returns_correct_type(self) -> None:
        auth = get_auth("together", api_key="test-key")
        assert auth is not None
        assert isinstance(auth, TogetherAuth)
        assert auth.api_key == "test-key"

    def test_list_contains_together(self) -> None:
        from zeloo_cli.auth.registry import list_auth_providers

        providers = list_auth_providers()
        assert "together" in providers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])