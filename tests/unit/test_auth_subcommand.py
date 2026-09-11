"""Unit tests for ``zeloo_cli.subcommands.auth`` provider dispatch."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from zeloo_cli.subcommands.auth import AuthCmd, _login
from zeloo_cli.auth import AUTH_REGISTRY, get_auth


class TestLoginProviderDispatch:
    """Verify that ``_login`` dispatches on the ``provider`` argument."""

    def test_unknown_provider(self, capsys):
        result = _login(provider="nonexistent_xyz")
        assert result == 1
        captured = capsys.readouterr()
        # Rich may or may not emit ANSI escape sequences; just look for
        # the human-readable substrings.
        combined = captured.out + captured.err
        assert "Unknown provider" in combined
        assert "nonexistent_xyz" in combined

    def test_already_authenticated(self, capsys):
        with patch("zeloo_cli.auth.get_auth") as mock_get:
            mock_auth = MagicMock()
            mock_auth.is_authenticated.return_value = True
            mock_get.return_value = mock_auth
            result = _login(provider="openai")
            assert result == 0
            mock_auth.is_authenticated.assert_called_once()
            captured = capsys.readouterr()
            combined = captured.out + captured.err
            assert "Already authenticated" in combined

    def test_api_key_path(self, capsys, monkeypatch):
        # Make sure we don't pollute the real env.
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("zeloo_cli.auth.get_auth") as mock_get, \
             patch("zeloo_cli.auth.token_store.TokenStore") as mock_store:
            mock_auth = MagicMock()
            # First call (initial probe) → False; second call (after api_key) → True
            mock_auth.is_authenticated.side_effect = [False, True]
            mock_get.return_value = mock_auth
            mock_store.return_value.save.return_value = None

            result = _login(provider="openai", api_key="sk-test")
            assert result == 0
            mock_store.return_value.save.assert_called_once()
            # Saved payload should at minimum include the access_token
            args, _ = mock_store.return_value.save.call_args
            assert args[0] == "openai"
            assert args[1].get("access_token") == "sk-test"

    def test_no_code_returns_error(self, capsys, monkeypatch):
        # Simulate OAuth flow but no code provided by user.
        monkeypatch.setattr("builtins.input", lambda *_: "")
        with patch("zeloo_cli.auth.get_auth") as mock_get:
            mock_auth = MagicMock()
            mock_auth.is_authenticated.return_value = False
            mock_auth.get_auth_url.return_value = "https://example.com/auth"
            mock_get.return_value = mock_auth

            result = _login(provider="openai")
            assert result == 1
            captured = capsys.readouterr()
            combined = captured.out + captured.err
            assert "No code provided" in combined

    def test_oauth_success(self, capsys, monkeypatch):
        # OAuth authorization-code flow with a provided code.
        monkeypatch.setenv("OPENAI_CLIENT_ID", "test-client")  # not required by mock
        with patch("zeloo_cli.auth.get_auth") as mock_get:
            mock_auth = MagicMock()
            mock_auth.is_authenticated.return_value = False
            mock_auth.get_auth_url.return_value = "https://example.com/auth"
            mock_auth.exchange_code = AsyncMock(
                return_value=MagicMock(
                    to_dict=lambda: {
                        "access_token": "tok-abc",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    }
                )
            )
            mock_get.return_value = mock_auth

            result = _login(provider="openai", code="my-code")
            assert result == 0
            mock_auth.exchange_code.assert_awaited_once_with("my-code", "http://localhost:8888/callback")
            # When the provider exposes ``save_token`` (BaseAuth does), we use it.
            mock_auth.save_token.assert_called_once()

    def test_oauth_exception_is_caught(self, capsys, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda *_: "abc")
        with patch("zeloo_cli.auth.get_auth") as mock_get:
            mock_auth = MagicMock()
            mock_auth.is_authenticated.return_value = False
            mock_auth.get_auth_url.return_value = "https://example.com/auth"
            mock_auth.exchange_code = AsyncMock(side_effect=RuntimeError("boom"))
            mock_get.return_value = mock_auth

            result = _login(provider="openai")
            assert result == 1
            captured = capsys.readouterr()
            combined = captured.out + captured.err
            assert "Auth failed" in combined
            assert "boom" in combined

    def test_legacy_path_with_provider_none(self, monkeypatch):
        # When provider is None, the legacy flow should run; pre-set api_key to
        # avoid the interactive prompt.
        with patch("zeloo_cli.subcommands.auth._legacy_login") as mock_legacy:
            mock_legacy.return_value = 0
            result = _login(provider=None, api_key="sk-legacy")
            assert result == 0
            mock_legacy.assert_called_once_with("sk-legacy")

    def test_run_dispatches_login_with_provider(self):
        # Verify the run() wiring on AuthCmd.
        cmd = AuthCmd()
        with patch("zeloo_cli.subcommands.auth._login") as mock_login:
            mock_login.return_value = 0
            ns = MagicMock()
            ns.auth_action = "login"
            ns.provider = "openai"
            ns.api_key = "sk-x"
            ns.code = None
            ns.redirect_uri = "http://localhost:8888/callback"
            ns.use_device_flow = False
            result = cmd.run(ns)
            assert result == 0
            mock_login.assert_called_once()


class TestProviderRegistry:
    """Sanity checks against the eagerly-populated AUTH_REGISTRY."""

    def test_openai_registered(self):
        assert "openai" in AUTH_REGISTRY

    def test_anthropic_registered(self):
        assert "anthropic" in AUTH_REGISTRY

    def test_xai_registered(self):
        assert "xai" in AUTH_REGISTRY

    def test_all_16_providers_registered(self):
        expected = {
            "openai", "anthropic", "google", "github", "discord", "xai",
            "deepseek", "groq", "mistral", "ollama", "openrouter",
            "azure", "fireworks", "together", "bedrock", "local",
        }
        missing = expected - set(AUTH_REGISTRY.keys())
        assert not missing, f"Missing providers in AUTH_REGISTRY: {missing}"

    def test_get_auth_returns_baseauth_instance(self):
        auth = get_auth("openai")
        assert auth is not None
        from zeloo_cli.auth.base import BaseAuth

        assert isinstance(auth, BaseAuth)
        assert auth.provider_name == "openai"


class TestLoginParser:
    """Verify the CLI parser accepts the ``<provider>`` positional argument."""

    def test_parser_accepts_provider(self):
        parser = argparse = __import__("argparse").ArgumentParser()
        AuthCmd.configure_parser(parser)

        ns = parser.parse_args(["login", "openai"])
        assert ns.auth_action == "login"
        assert ns.provider == "openai"

    def test_parser_accepts_no_provider(self):
        parser = __import__("argparse").ArgumentParser()
        AuthCmd.configure_parser(parser)

        ns = parser.parse_args(["login"])
        assert ns.auth_action == "login"
        assert ns.provider is None

    def test_parser_accepts_api_key_flag(self):
        parser = __import__("argparse").ArgumentParser()
        AuthCmd.configure_parser(parser)

        ns = parser.parse_args(["login", "openai", "--api-key", "sk-xyz"])
        assert ns.api_key == "sk-xyz"

    def test_parser_accepts_code_flag(self):
        parser = __import__("argparse").ArgumentParser()
        AuthCmd.configure_parser(parser)

        ns = parser.parse_args(["login", "openai", "--code", "abc"])
        assert ns.code == "abc"

    def test_parser_accepts_device_flow_flag(self):
        parser = __import__("argparse").ArgumentParser()
        AuthCmd.configure_parser(parser)

        ns = parser.parse_args(["login", "openai", "--device-flow"])
        assert ns.use_device_flow is True