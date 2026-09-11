"""Unit tests for ``zeloo serve`` and ``zeloo z`` subcommands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest import mock

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from zeloo_cli.subcommands import _load_subcommands, _SUBCOMMANDS
from zeloo_cli.subcommands.serve import ServeCommand
from zeloo_cli.subcommands.z import ZCommand


# ── shared helpers ────────────────────────────────────────────────


def _parse(parser: argparse.ArgumentParser, argv: list[str]) -> argparse.Namespace:
    return parser.parse_args(argv)


@pytest.fixture(autouse=True)
def _ensure_loaded() -> None:
    """Force the subcommand registry to import the new modules."""
    _load_subcommands()


# ── ServeCommand ──────────────────────────────────────────────────


class TestServeCommand:
    def test_command_registered(self) -> None:
        assert "serve" in _SUBCOMMANDS
        assert _SUBCOMMANDS["serve"] is ServeCommand

    def test_default_parser(self) -> None:
        parser = argparse.ArgumentParser()
        ServeCommand.configure_parser(parser)
        ns = _parse(parser, [])
        assert ns.host == "0.0.0.0"
        assert ns.port == 9113
        assert ns.workers == 1
        assert ns.reload is False
        assert ns.api_key is None
        assert ns.cors_origins == "*"
        assert ns.model_name == "Zeloo"

    def test_parser_with_overrides(self) -> None:
        parser = argparse.ArgumentParser()
        ServeCommand.configure_parser(parser)
        ns = _parse(
            parser,
            [
                "--host", "127.0.0.1",
                "--port", "8080",
                "--workers", "4",
                "--reload",
                "--api-key", "tok123",
                "--cors-origins", "https://a,https://b",
                "--model-name", "my-model",
            ],
        )
        assert ns.host == "127.0.0.1"
        assert ns.port == 8080
        assert ns.workers == 4
        assert ns.reload is True
        assert ns.api_key == "tok123"
        assert ns.cors_origins == "https://a,https://b"
        assert ns.model_name == "my-model"

    def test_parse_cors_origin(self) -> None:
        assert ServeCommand._parse_cors("*") == ["*"]
        assert ServeCommand._parse_cors("a,b,c") == ["a", "b", "c"]
        assert ServeCommand._parse_cors(" a , b , ") == ["a", "b"]
        assert ServeCommand._parse_cors("") == ["*"]
        assert ServeCommand._parse_cors(None) == ["*"]

    def test_parse_auth_tokens(self) -> None:
        assert ServeCommand._parse_auth_tokens(None) is None
        assert ServeCommand._parse_auth_tokens("secret") == ["secret"]
        with mock.patch.dict("os.environ", {"zeloo_API_TOKEN": "env-tok"}, clear=False):
            assert ServeCommand._parse_auth_tokens(None) == ["env-tok"]
            assert ServeCommand._parse_auth_tokens("cli-tok") == ["cli-tok", "env-tok"]


# ── ZCommand ──────────────────────────────────────────────────────


class TestZCommand:
    def test_command_registered(self) -> None:
        assert "z" in _SUBCOMMANDS
        assert _SUBCOMMANDS["z"] is ZCommand

    def test_default_parser(self) -> None:
        parser = argparse.ArgumentParser()
        ZCommand.configure_parser(parser)
        ns = _parse(parser, ["hello world"])
        assert ns.query == "hello world"
        assert ns.model is None
        assert ns.provider is None
        assert ns.system is None
        assert ns.temperature is None

    def test_parser_with_overrides(self) -> None:
        parser = argparse.ArgumentParser()
        ZCommand.configure_parser(parser)
        ns = _parse(
            parser,
            [
                "Why?",
                "--model", "gpt-4o",
                "--provider", "openai",
                "--system", "be terse",
                "--temperature", "0.7",
            ],
        )
        assert ns.query == "Why?"
        assert ns.model == "gpt-4o"
        assert ns.provider == "openai"
        assert ns.system == "be terse"
        assert ns.temperature == pytest.approx(0.7)

    def test_run_empty_query_returns_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        cmd = ZCommand()
        ns = argparse.Namespace(
            query="   ", model=None, provider=None, system=None, temperature=None,
        )
        rc = cmd.run(ns)
        captured = capsys.readouterr()
        assert rc == 1
        assert "empty query" in captured.err.lower()

    def test_run_delegates_to_oneshot(self) -> None:
        cmd = ZCommand()
        ns = argparse.Namespace(
            query="hi", model="m", provider="p",
            system=None, temperature=0.5,
        )
        with mock.patch(
            "zeloo_cli.oneshot.run_oneshot", return_value=0,
        ) as mock_run:
            rc = cmd.run(ns)
        assert rc == 0
        mock_run.assert_called_once()
        # First positional arg is the query
        args, kwargs = mock_run.call_args
        assert args[0] == "hi"
        assert kwargs.get("model") == "m"
        assert kwargs.get("provider") == "p"
        assert kwargs.get("temperature") == 0.5

    def test_run_propagates_oneshot_error(self) -> None:
        cmd = ZCommand()
        ns = argparse.Namespace(
            query="boom", model=None, provider=None,
            system=None, temperature=None,
        )
        with mock.patch(
            "zeloo_cli.oneshot.run_oneshot", side_effect=RuntimeError("nope"),
        ):
            rc = cmd.run(ns)
        assert rc == 1
