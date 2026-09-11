"""Unit tests for Azure auth module (multi-mode auth: API key / Azure AD / Managed Identity)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import zeloo_cli.auth  # noqa: F401 触发 eager 注册
from zeloo_cli.auth.azure_auth import AzureAuth
from zeloo_cli.auth.base import AuthConfigError, AuthError, TokenResponse
from zeloo_cli.auth.registry import AUTH_REGISTRY, get_auth


class TestAzureAuthInit:
    """Test AzureAuth.__init__ parameter handling."""

    def test_default_init(self) -> None:
        auth = AzureAuth()
        assert auth.provider_name == "azure"
        assert auth.api_key == ""
        assert auth.endpoint == ""
        assert auth.deployment == ""
        assert auth.tenant_id == ""

    def test_custom_api_key_kwarg(self) -> None:
        auth = AzureAuth(api_key="azure-key-123")
        assert auth.api_key == "azure-key-123"

    def test_api_key_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-env-key")
        auth = AzureAuth()
        assert auth.api_key == "azure-env-key"

    def test_priority_api_key_over_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "env-key")
        auth = AzureAuth(api_key="kwarg-key")
        assert auth.api_key == "kwarg-key"

    def test_tenant_id_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("AZURE_TENANT_ID", "tenant-abc")
        auth = AzureAuth()
        assert auth.tenant_id == "tenant-abc"

    def test_endpoint_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://my.openai.azure.com")
        auth = AzureAuth()
        assert auth.endpoint == "https://my.openai.azure.com"

    def test_deployment_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "my-deployment")
        auth = AzureAuth()
        assert auth.deployment == "my-deployment"

    def test_api_version_default(self) -> None:
        auth = AzureAuth()
        # default api_version is non-empty
        assert auth.api_version

    def test_managed_identity_client_id(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("AZURE_CLIENT_ID", "msi-client")
        auth = AzureAuth()
        assert auth.managed_identity_client == "msi-client"


class TestResolveAuthMode:
    """Test _resolve_auth_mode() logic."""

    def test_api_key_mode(self) -> None:
        auth = AzureAuth(api_key="k")
        assert auth._resolve_auth_mode() == "api_key"

    def test_managed_identity_mode(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("AZURE_CLIENT_ID", "msi-client")
        auth = AzureAuth()
        assert auth._resolve_auth_mode() == "managed_identity"

    def test_azure_ad_mode(self) -> None:
        # AzureAuth 要求 client_secret 非空才能进入 azure_ad 模式
        # (api_key 在 client_secret 非空时也会回退,故 api_key="" 避免误判)
        auth = AzureAuth(
            client_id="cid",
            client_secret="csec",
            tenant_id="tenant",
        )
        # 直接构造一个 stub: api_key 必须为空才能进入 azure_ad 分支
        auth.api_key = ""
        assert auth._resolve_auth_mode() == "azure_ad"

    def test_unconfigured_raises(self) -> None:
        auth = AzureAuth()
        with pytest.raises(AuthConfigError) as exc_info:
            auth._resolve_auth_mode()
        assert "Azure" in str(exc_info.value)


class TestIsAuthenticated:
    """Test is_authenticated() status check."""

    def test_true_with_api_key(self) -> None:
        auth = AzureAuth(api_key="k")
        assert auth.is_authenticated() is True

    def test_false_without_credentials(self) -> None:
        auth = AzureAuth()
        auth.api_key = ""
        assert auth.is_authenticated() is False


class TestGetAuthUrl:
    """Test get_auth_url() — Azure AD delegated flow."""

    def test_raises_without_client_id(self) -> None:
        auth = AzureAuth(api_key="k")
        with pytest.raises(AuthConfigError):
            auth.get_auth_url("https://cb.example.com")

    def test_returns_url_with_tenant(self) -> None:
        auth = AzureAuth(client_id="my-cid", tenant_id="my-tenant")
        url = auth.get_auth_url("https://cb.example.com")
        assert "login.microsoftonline.com" in url
        assert "my-tenant" in url
        assert "my-cid" in url
        assert "https%3A%2F%2Fcb.example.com" in url

    def test_url_includes_state(self) -> None:
        auth = AzureAuth(client_id="cid", tenant_id="tenant")
        url = auth.get_auth_url("https://cb.example.com", state="csrf")
        assert "state=csrf" in url


class TestExchangeCode:
    """Test exchange_code() Azure AD token exchange."""

    @pytest.mark.asyncio
    async def test_raises_without_client_id(self) -> None:
        auth = AzureAuth(api_key="k")
        with pytest.raises(AuthConfigError):
            await auth.exchange_code("code", "https://cb.example.com")

    @pytest.mark.asyncio
    async def test_parses_token_response(self) -> None:
        auth = AzureAuth(client_id="cid", client_secret="csec", tenant_id="tenant")
        mock_response = {
            "access_token": "azure_access",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        async def fake_post_form(url, data, headers=None, timeout=30.0):
            return mock_response

        with mock.patch.object(auth, "_post_form", fake_post_form):
            result = await auth.exchange_code("auth-code", "https://cb.example.com")

        assert result.access_token == "azure_access"
        assert result.expires_in == 3600


class TestRefreshToken:
    """Test refresh_token() Azure AD refresh."""

    @pytest.mark.asyncio
    async def test_raises_without_client_id(self) -> None:
        auth = AzureAuth(api_key="k")
        with pytest.raises(AuthConfigError):
            await auth.refresh_token("refresh-tok")

    @pytest.mark.asyncio
    async def test_parses_refreshed_token(self) -> None:
        auth = AzureAuth(client_id="cid", client_secret="csec", tenant_id="tenant")
        mock_response = {
            "access_token": "azure_new_access",
            "token_type": "Bearer",
            "expires_in": 7200,
        }

        async def fake_post_form(url, data, headers=None, timeout=30.0):
            return mock_response

        with mock.patch.object(auth, "_post_form", fake_post_form):
            result = await auth.refresh_token("old-refresh")

        assert result.access_token == "azure_new_access"


class TestGetUserInfo:
    """Test get_user_info() — placeholder."""

    @pytest.mark.asyncio
    async def test_returns_placeholder(self) -> None:
        auth = AzureAuth(api_key="k")
        info = await auth.get_user_info("any-token")
        assert info.provider == "azure"
        assert info.user_id == "azure-user"
        assert info.raw.get("mode") == "api_key"


class TestParseTokenResponse:
    """Test _parse_token_response() shape."""

    def test_full_token_response(self) -> None:
        auth = AzureAuth(api_key="k")
        data = {
            "access_token": "az-at",
            "refresh_token": "az-rt",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "https://cognitiveservices.azure.com/.default",
            "ext": "keep",
        }
        result = auth._parse_token_response(data)
        assert result.access_token == "az-at"
        assert result.refresh_token == "az-rt"
        assert result.expires_in == 3600
        assert result.extras.get("ext") == "keep"

    def test_missing_access_token_raises(self) -> None:
        auth = AzureAuth(api_key="k")
        with pytest.raises(AuthError) as exc_info:
            auth._parse_token_response({"error": "invalid_grant"})
        assert "access_token" in str(exc_info.value)


class TestRegistryIntegration:
    """Test that Azure is correctly registered in the auth registry."""

    def test_azure_registered(self) -> None:
        assert "azure" in AUTH_REGISTRY
        assert AUTH_REGISTRY["azure"] is AzureAuth

    def test_provider_name_matches(self) -> None:
        auth = AzureAuth()
        assert auth.provider_name == "azure"

    def test_get_auth_returns_correct_type(self) -> None:
        auth = get_auth("azure", api_key="test-key")
        assert auth is not None
        assert isinstance(auth, AzureAuth)
        assert auth.api_key == "test-key"

    def test_list_contains_azure(self) -> None:
        from zeloo_cli.auth.registry import list_auth_providers

        providers = list_auth_providers()
        assert "azure" in providers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])