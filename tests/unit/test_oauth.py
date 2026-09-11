"""Tests for OAuth token management and provider routing."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from agent.oauth import (
    OAuthToken,
    OAuthTokenStore,
    get_oauth_provider_config,
)
from agent.provider_router import ProviderConfig


def test_token_roundtrip() -> None:
    """Token save → load → expiry roundtrip."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tokens.json"
        store = OAuthTokenStore(path)

        token = OAuthToken(
            provider="test",
            access_token="tok_abc123",
            expires_at=time.time() + 3600,
        )
        store.save(token)

        loaded = store.get("test")
        assert loaded is not None
        assert loaded.access_token == "tok_abc123"
        assert not loaded.is_expired


def test_token_expired() -> None:
    """Expired tokens are detected correctly."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tokens.json"
        store = OAuthTokenStore(path)

        store.save(
            OAuthToken(
                provider="expired_test",
                access_token="expired_tok",
                expires_at=time.time() - 1,
            )
        )
        token = store.get("expired_test")
        assert token is not None
        assert token.is_expired


def test_token_no_expiry() -> None:
    """Tokens with expires_at <= 0 are treated as non-expiring."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tokens.json"
        store = OAuthTokenStore(path)

        store.save(
            OAuthToken(
                provider="no_expiry",
                access_token="never_expires",
                expires_at=0,
            )
        )
        token = store.get("no_expiry")
        assert token is not None
        assert not token.is_expired


def test_token_delete() -> None:
    """Deleted tokens are no longer retrievable."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tokens.json"
        store = OAuthTokenStore(path)

        store.save(
            OAuthToken(provider="to_delete", access_token="secret", expires_at=0)
        )
        assert store.get("to_delete") is not None
        store.delete("to_delete")
        assert store.get("to_delete") is None


def test_store_file_permissions_on_unix() -> None:
    """The token file is created with mode 0600 on POSIX systems."""
    if os.name != "posix":
        return
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tokens.json"
        store = OAuthTokenStore(path)
        store.save(OAuthToken(provider="codex", access_token="a"))
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600


def test_store_persists_to_disk() -> None:
    """Tokens are actually written to disk as JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tokens.json"
        store = OAuthTokenStore(path)
        store.save(
            OAuthToken(provider="persist", access_token="tok_persist", expires_at=0)
        )

        store2 = OAuthTokenStore(path)
        token = store2.get("persist")
        assert token is not None
        assert token.access_token == "tok_persist"


def test_builtin_oauth_config() -> None:
    """Built-in providers (codex, nous) return valid provider configs."""
    codex = get_oauth_provider_config("codex")
    assert codex is not None
    assert codex.authorization_url == "https://auth.openai.com/authorize"
    assert codex.token_url == "https://auth.openai.com/oauth/token"

    nous = get_oauth_provider_config("nous")
    assert nous is not None


def test_unknown_oauth_config() -> None:
    """Unknown provider names return None."""
    assert get_oauth_provider_config("definitely-not-a-real-provider") is None


def test_provider_router_uses_oauth_token(tmp_path: Path) -> None:
    """ProviderConfig.resolve() falls back to an OAuth token when no API key."""
    orig_home = os.environ.get("zeloo_HOME")
    os.environ["zeloo_HOME"] = str(tmp_path)
    try:
        store = OAuthTokenStore()
        store.save(
            OAuthToken(
                provider="codex",
                access_token="oauth_injected",
                expires_at=time.time() + 3600,
            )
        )
        try:
            os.environ.pop("OPENAI_API_KEY", None)
            cfg = ProviderConfig(name="codex", model="o1")
            resolved = cfg.resolve()
            assert resolved.api_key == "oauth_injected"
            assert resolved.is_configured()
        finally:
            store.delete("codex")
    finally:
        if orig_home is not None:
            os.environ["zeloo_HOME"] = orig_home
        else:
            os.environ.pop("zeloo_HOME", None)


def test_provider_router_no_token_unconfigured(tmp_path: Path) -> None:
    """Without API key or OAuth token, provider is not configured."""
    orig_home = os.environ.get("zeloo_HOME")
    os.environ["zeloo_HOME"] = str(tmp_path)
    try:
        store = OAuthTokenStore()
        store.delete("nous")
        os.environ.pop("NOUS_API_KEY", None)  # nosec
        cfg = ProviderConfig(name="nous", model="hermes-3")
        resolved = cfg.resolve()
        assert not resolved.api_key
        assert not resolved.is_configured()
    finally:
        if orig_home is not None:
            os.environ["zeloo_HOME"] = orig_home
        else:
            os.environ.pop("zeloo_HOME", None)


if __name__ == "__main__":
    test_token_roundtrip()
    test_token_expired()
    test_token_no_expiry()
    test_token_delete()
    test_store_file_permissions_on_unix()
    test_store_persists_to_disk()
    test_builtin_oauth_config()
    test_unknown_oauth_config()
    test_provider_router_uses_oauth_token()
    test_provider_router_no_token_unconfigured()
    print("All OAuth tests passed!")
