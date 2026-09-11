"""Unit tests for AWS Bedrock auth module (SigV4 signing)."""

from __future__ import annotations

import hashlib
import hmac
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import zeloo_cli.auth  # noqa: F401 触发 eager 注册
from zeloo_cli.auth.base import AuthConfigError
from zeloo_cli.auth.bedrock_auth import BedrockAuth
from zeloo_cli.auth.registry import AUTH_REGISTRY, get_auth


class TestBedrockAuthInit:
    """Test BedrockAuth.__init__ parameter handling."""

    def test_default_init(self) -> None:
        auth = BedrockAuth()
        assert auth.provider_name == "bedrock"
        assert auth.access_key == ""
        assert auth.secret_key == ""
        assert auth.session_token == ""
        assert auth.api_base == "https://bedrock-runtime.us-east-1.amazonaws.com"

    def test_client_id_maps_to_access_key(self) -> None:
        auth = BedrockAuth(client_id="AKIA-ACCESS-123")
        assert auth.access_key == "AKIA-ACCESS-123"

    def test_client_secret_maps_to_secret_key(self) -> None:
        auth = BedrockAuth(client_secret="SECRET-KEY-456")
        assert auth.secret_key == "SECRET-KEY-456"

    def test_api_key_maps_to_session_token(self) -> None:
        auth = BedrockAuth(api_key="session-token-abc")
        assert auth.session_token == "session-token-abc"

    def test_access_key_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA-ENV-123")
        auth = BedrockAuth()
        assert auth.access_key == "AKIA-ENV-123"

    def test_secret_key_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "SECRET-ENV-456")
        auth = BedrockAuth()
        assert auth.secret_key == "SECRET-ENV-456"

    def test_session_token_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("AWS_SESSION_TOKEN", "token-env")
        auth = BedrockAuth()
        assert auth.session_token == "token-env"

    def test_region_from_env(self, monkeypatch: pytest.MonKeyPatch) -> None:
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        auth = BedrockAuth()
        assert auth.region == "eu-west-1"

    def test_region_default_fallback(self) -> None:
        auth = BedrockAuth()
        assert auth.region == "us-east-1"

    def test_region_from_kwargs(self) -> None:
        auth = BedrockAuth(region="ap-southeast-2")
        assert auth.region == "ap-southeast-2"

    def test_default_api_base(self) -> None:
        auth = BedrockAuth()
        assert auth.api_base
        assert "bedrock" in auth.api_base

    def test_model_id_from_kwargs(self) -> None:
        auth = BedrockAuth(model_id="anthropic.claude-3")
        assert auth.model_id == "anthropic.claude-3"


class TestIsAuthenticated:
    """Test is_authenticated() — requires both access_key and secret_key."""

    def test_false_without_credentials(self) -> None:
        auth = BedrockAuth()
        auth.access_key = ""
        auth.secret_key = ""
        assert auth.is_authenticated() is False

    def test_true_with_both_keys(self) -> None:
        auth = BedrockAuth(client_id="AKIA", client_secret="SECRET")
        assert auth.is_authenticated() is True

    def test_false_with_only_access_key(self) -> None:
        auth = BedrockAuth(client_id="AKIA")
        auth.secret_key = ""
        assert auth.is_authenticated() is False

    def test_false_with_only_secret_key(self) -> None:
        auth = BedrockAuth(client_secret="SECRET")
        auth.access_key = ""
        assert auth.is_authenticated() is False


class TestGetAuthUrl:
    """Test get_auth_url() — Bedrock does not support OAuth."""

    def test_raises_config_error(self) -> None:
        auth = BedrockAuth(client_id="k", client_secret="k")
        with pytest.raises(AuthConfigError) as exc_info:
            auth.get_auth_url("https://cb.example.com")
        assert "IAM" in str(exc_info.value) or "OAuth" in str(exc_info.value)


class TestExchangeCode:
    """Test exchange_code() — not supported."""

    @pytest.mark.asyncio
    async def test_raises(self) -> None:
        auth = BedrockAuth(client_id="k", client_secret="k")
        with pytest.raises(AuthConfigError):
            await auth.exchange_code("code", "https://cb.example.com")


class TestRefreshToken:
    """Test refresh_token() — not supported."""

    @pytest.mark.asyncio
    async def test_raises(self) -> None:
        auth = BedrockAuth(client_id="k", client_secret="k")
        with pytest.raises(AuthConfigError):
            await auth.refresh_token("any")


class TestGetUserInfo:
    """Test get_user_info() — IAM principal placeholder."""

    @pytest.mark.asyncio
    async def test_returns_principal(self) -> None:
        auth = BedrockAuth(client_id="AKIA-123", client_secret="SECRET")
        info = await auth.get_user_info("any")
        assert info.provider == "bedrock"
        assert info.user_id == "AKIA-123"
        assert info.raw.get("region") == auth.region


class TestSigV4Helpers:
    """Test SigV4 signing primitives."""

    def test_sha256_hex(self) -> None:
        result = BedrockAuth._sha256_hex("hello")
        expected = hashlib.sha256(b"hello").hexdigest()
        assert result == expected

    def test_hmac_sha256(self) -> None:
        key = b"key"
        result = BedrockAuth._hmac_sha256(key, "data")
        expected = hmac.new(key, b"data", hashlib.sha256).digest()
        assert result == expected

    def test_derive_signing_key_length(self) -> None:
        auth = BedrockAuth(client_id="AKIA-1", client_secret="SECRET-1", region="us-east-1")
        key = auth._derive_signing_key("20240101")
        # SigV4 signing key is 32 bytes
        assert len(key) == 32

    def test_canonical_query_empty(self) -> None:
        assert BedrockAuth._canonical_query("") == ""

    def test_canonical_query_simple(self) -> None:
        result = BedrockAuth._canonical_query("a=1&b=2")
        # Should be sorted alphabetically
        assert "a=1" in result and "b=2" in result

    def test_canonical_query_sorted(self) -> None:
        result = BedrockAuth._canonical_query("z=9&a=1")
        # a=1 must precede z=9
        assert result.index("a=1") < result.index("z=9")


class TestSignRequest:
    """Test _sign_request() SigV4 header generation."""

    def test_sign_request_returns_dict(self) -> None:
        auth = BedrockAuth(
            client_id="AKIA-TEST",
            client_secret="test-secret",
            region="us-east-1",
        )
        headers = auth._sign_request(
            "POST",
            "https://bedrock-runtime.us-east-1.amazonaws.com/model/test/invoke",
            body='{"prompt":"hi"}',
        )
        assert isinstance(headers, dict)
        assert "Authorization" in headers
        assert "X-Amz-Date" in headers
        assert "X-Amz-Content-Sha256" in headers
        assert "Host" in headers

    def test_authorization_header_format(self) -> None:
        auth = BedrockAuth(
            client_id="AKIA-TEST",
            client_secret="test-secret",
            region="us-east-1",
        )
        headers = auth._sign_request(
            "POST",
            "https://bedrock-runtime.us-east-1.amazonaws.com/foo",
        )
        auth_header = headers["Authorization"]
        assert auth_header.startswith("AWS4-HMAC-SHA256 ")
        assert "Credential=AKIA-TEST/" in auth_header
        assert "SignedHeaders=" in auth_header
        assert "Signature=" in auth_header

    def test_credential_scope_format(self) -> None:
        auth = BedrockAuth(
            client_id="AKIA-TEST",
            client_secret="test-secret",
            region="eu-west-2",
        )
        headers = auth._sign_request(
            "POST",
            "https://bedrock-runtime.eu-west-2.amazonaws.com/foo",
        )
        auth_header = headers["Authorization"]
        # credential scope: date/region/bedrock/aws4_request
        assert "/eu-west-2/bedrock/aws4_request" in auth_header

    def test_amz_date_format(self) -> None:
        auth = BedrockAuth(
            client_id="AKIA-TEST",
            client_secret="test-secret",
            region="us-east-1",
        )
        headers = auth._sign_request("POST", "https://example.com/foo")
        amz_date = headers["X-Amz-Date"]
        # Format: YYYYMMDDTHHMMSSZ (16 chars)
        assert len(amz_date) == 16
        assert amz_date.endswith("Z")
        assert "T" in amz_date

    def test_content_sha256_present(self) -> None:
        auth = BedrockAuth(
            client_id="AKIA-TEST",
            client_secret="test-secret",
            region="us-east-1",
        )
        headers = auth._sign_request(
            "POST",
            "https://example.com/foo",
            body="some-body",
        )
        # sha256 hex is 64 chars
        assert len(headers["X-Amz-Content-Sha256"]) == 64

    def test_session_token_included_when_present(self) -> None:
        auth = BedrockAuth(
            client_id="AKIA-TEST",
            client_secret="test-secret",
            api_key="session-token-xyz",
            region="us-east-1",
        )
        headers = auth._sign_request("POST", "https://example.com/foo")
        assert "X-Amz-Security-Token" in headers
        assert headers["X-Amz-Security-Token"] == "session-token-xyz"

    def test_no_session_token_when_absent(self) -> None:
        auth = BedrockAuth(
            client_id="AKIA-TEST",
            client_secret="test-secret",
            region="us-east-1",
        )
        auth.session_token = ""
        headers = auth._sign_request("POST", "https://example.com/foo")
        assert "X-Amz-Security-Token" not in headers

    def test_raises_without_credentials(self) -> None:
        auth = BedrockAuth()
        auth.access_key = ""
        auth.secret_key = ""
        with pytest.raises(AuthConfigError) as exc_info:
            auth._sign_request("POST", "https://example.com/foo")
        assert "AWS_ACCESS_KEY_ID" in str(exc_info.value) or "credentials" in str(exc_info.value).lower()

    def test_signature_is_hex(self) -> None:
        auth = BedrockAuth(
            client_id="AKIA-TEST",
            client_secret="test-secret",
            region="us-east-1",
        )
        headers = auth._sign_request("POST", "https://example.com/foo")
        # Extract signature from Authorization
        auth_header = headers["Authorization"]
        sig_part = auth_header.split("Signature=")[1]
        # hex sha256 is 64 chars
        assert len(sig_part) == 64
        assert all(c in "0123456789abcdef" for c in sig_part)


class TestRegistryIntegration:
    """Test that Bedrock is correctly registered in the auth registry."""

    def test_bedrock_registered(self) -> None:
        assert "bedrock" in AUTH_REGISTRY
        assert AUTH_REGISTRY["bedrock"] is BedrockAuth

    def test_provider_name_matches(self) -> None:
        auth = BedrockAuth()
        assert auth.provider_name == "bedrock"

    def test_get_auth_returns_correct_type(self) -> None:
        auth = get_auth("bedrock", client_id="AKIA", client_secret="SECRET")
        assert auth is not None
        assert isinstance(auth, BedrockAuth)
        assert auth.access_key == "AKIA"
        assert auth.secret_key == "SECRET"

    def test_list_contains_bedrock(self) -> None:
        from zeloo_cli.auth.registry import list_auth_providers

        providers = list_auth_providers()
        assert "bedrock" in providers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])