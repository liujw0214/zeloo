"""Unit tests for Local (OpenAI-compatible) auth module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import zeloo_cli.auth  # noqa: F401 触发 eager 注册
from zeloo_cli.auth.base import AuthConfigError
from zeloo_cli.auth.local_auth import LocalAuth
from zeloo_cli.auth.registry import AUTH_REGISTRY, get_auth


class TestLocalAuthInit:
    """Test LocalAuth.__init__ parameter handling."""

    def test_default_init(self) -> None:
        auth = LocalAuth()
        assert auth.provider_name == "local"
        assert auth.api_key == ""
        assert auth.api_base == "http://localhost:1234/v1"
        assert auth.require_auth is False

    def test_custom_api_key_kwarg(self) -> None:
        auth = LocalAuth(api_key="local-key-123")
        assert auth.api_key == "local-key-123"

    def test_api_key_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("LOCAL_API_KEY", "local-env-key")
        auth = LocalAuth()
        assert auth.api_key == "local-env-key"

    def test_priority_api_key_over_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("LOCAL_API_KEY", "env-key")
        auth = LocalAuth(api_key="kwarg-key")
        assert auth.api_key == "kwarg-key"

    def test_client_id_fallback(self) -> None:
        auth = LocalAuth(client_id="local-id")
        assert auth.api_key == "local-id"

    def test_default_api_base(self) -> None:
        auth = LocalAuth()
        assert auth.api_base
        assert "localhost" in auth.api_base or "127.0.0.1" in auth.api_base

    def test_custom_api_base(self) -> None:
        auth = LocalAuth(api_key="k", api_base="http://my-local-llm:8000/v1")
        assert auth.api_base == "http://my-local-llm:8000/v1"

    def test_require_auth_default_false(self) -> None:
        auth = LocalAuth()
        assert auth.require_auth is False

    def test_require_auth_true(self) -> None:
        auth = LocalAuth(require_auth=True)
        assert auth.require_auth is True


class TestResolvedApiKey:
    """Test _resolved_api_key() — empty by default, key when configured."""

    def test_empty_when_no_key(self) -> None:
        auth = LocalAuth()
        assert auth._resolved_api_key() == ""

    def test_returns_key_when_set(self) -> None:
        auth = LocalAuth(api_key="explicit-key")
        assert auth._resolved_api_key() == "explicit-key"

    def test_returns_env_key(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("LOCAL_API_KEY", "env-key")
        auth = LocalAuth()
        assert auth._resolved_api_key() == "env-key"

    def test_client_id_fallback(self) -> None:
        auth = LocalAuth(client_id="cid-fallback")
        assert auth._resolved_api_key() == "cid-fallback"


class TestIsAuthenticated:
    """Test is_authenticated() — local servers are always authenticated."""

    def test_authenticated_by_default(self) -> None:
        auth = LocalAuth()
        # Local 默认 is_authenticated=True
        assert auth.is_authenticated() is True

    def test_authenticated_with_api_key(self) -> None:
        auth = LocalAuth(api_key="k")
        assert auth.is_authenticated() is True

    def test_authenticated_without_api_key(self) -> None:
        auth = LocalAuth()
        auth.api_key = ""
        assert auth.is_authenticated() is True

    def test_unauthenticated_when_require_auth_and_no_key(self) -> None:
        auth = LocalAuth(require_auth=True)
        auth.api_key = ""
        assert auth.is_authenticated() is False

    def test_authenticated_when_require_auth_with_key(self) -> None:
        auth = LocalAuth(require_auth=True, api_key="k")
        assert auth.is_authenticated() is True


class TestGetAuthUrl:
    """Test get_auth_url() — Local does not support OAuth."""

    def test_raises_config_error(self) -> None:
        auth = LocalAuth(api_key="k")
        with pytest.raises(AuthConfigError) as exc_info:
            auth.get_auth_url("https://cb.example.com")
        assert "OAuth" in str(exc_info.value) or "inference" in str(exc_info.value).lower()


class TestExchangeCode:
    """Test exchange_code() — not supported."""

    @pytest.mark.asyncio
    async def test_raises(self) -> None:
        auth = LocalAuth(api_key="k")
        with pytest.raises(AuthConfigError) as exc_info:
            await auth.exchange_code("code", "https://cb.example.com")
        assert "OAuth" in str(exc_info.value) or "inference" in str(exc_info.value).lower()


class TestRefreshToken:
    """Test refresh_token() — not supported."""

    @pytest.mark.asyncio
    async def test_raises(self) -> None:
        auth = LocalAuth(api_key="k")
        with pytest.raises(AuthConfigError) as exc_info:
            await auth.refresh_token("any")
        assert "OAuth" in str(exc_info.value) or "refresh" in str(exc_info.value).lower()


class TestGetUserInfo:
    """Test get_user_info() local placeholder."""

    @pytest.mark.asyncio
    async def test_returns_local_user(self) -> None:
        auth = LocalAuth(api_key="k")
        info = await auth.get_user_info("any")
        assert info.provider == "local"
        assert info.user_id == "local-user"
        assert info.name == "Local User"
        assert info.username == "local"
        assert info.raw.get("api_base") == auth.api_base


class TestRegistryIntegration:
    """Test that Local is correctly registered in the auth registry."""

    def test_local_registered(self) -> None:
        assert "local" in AUTH_REGISTRY
        assert AUTH_REGISTRY["local"] is LocalAuth

    def test_provider_name_matches(self) -> None:
        auth = LocalAuth()
        assert auth.provider_name == "local"

    def test_get_auth_returns_correct_type(self) -> None:
        auth = get_auth("local", api_key="test-key")
        assert auth is not None
        assert isinstance(auth, LocalAuth)
        assert auth.api_key == "test-key"

    def test_list_contains_local(self) -> None:
        from zeloo_cli.auth.registry import list_auth_providers

        providers = list_auth_providers()
        assert "local" in providers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])