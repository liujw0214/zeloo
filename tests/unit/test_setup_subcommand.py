"""Tests for ``zeloo_cli.subcommands.setup`` — Hermes-style setup wizard."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from zeloo_cli.subcommands.setup import (
    SECTIONS,
    TERMINAL_BACKENDS,
    VOICE_BACKENDS,
    _docker_daemon_status,
    _load_existing_config,
    _merge_yaml,
    build_setup_parser,
    cmd_setup,
    cmd_setup_agent,
    cmd_setup_gateway,
    cmd_setup_model,
    cmd_setup_portal,
    cmd_setup_telemetry,
    cmd_setup_terminal,
    cmd_setup_terminal_test,
    cmd_setup_tools,
    cmd_setup_tts,
    cmd_setup_tts_test,
    is_voice_backend_available,
)


def _make_args(**overrides):
    defaults = dict(
        section=None,
        non_interactive=False,
        reset=False,
        reconfigure=False,
        quick=False,
        portal=False,
        overwrite=False,
        json=False,
        home=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ── parser ─────────────────────────────────────────────────────────


class TestSetupParser:
    def test_build_setup_parser_attaches_setup(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        captured = {}

        def handler(args):
            captured["called"] = args
            return 0

        build_setup_parser(subparsers, cmd_setup_handler=handler)
        args = parser.parse_args(["setup"])
        assert args.func is handler

    def test_section_choices_match_hermes(self) -> None:
        assert SECTIONS == [
            "model", "tts", "terminal", "gateway", "tools", "telemetry", "agent",
        ]

    def test_all_flags_parseable(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        build_setup_parser(subparsers, cmd_setup_handler=lambda a: 0)
        args = parser.parse_args(
            [
                "setup", "model",
                "--non-interactive",
                "--reset",
                "--reconfigure",
                "--quick",
                "--portal",
                "--overwrite",
                "--test",
                "--json",
                "--home", str(Path.home()),
            ]
        )
        assert args.section == "model"
        assert args.non_interactive is True
        assert args.reset is True
        assert args.reconfigure is True
        assert args.quick is True
        assert args.portal is True
        assert args.overwrite is True
        assert args.test is True
        assert args.json is True


# ── non-interactive ────────────────────────────────────────────────


class TestNonInteractive:
    def test_writes_defaults(self, tmp_path: Path):
        args = _make_args(non_interactive=True, home=str(tmp_path), json=True)
        rc = cmd_setup(args)
        assert rc == 0
        assert (tmp_path / "config.yaml").exists()
        assert (tmp_path / ".env").exists()

    def test_overwrite_works_with_existing_files(self, tmp_path: Path):
        (tmp_path / "config.yaml").write_text("old: 1", encoding="utf-8")
        (tmp_path / ".env").write_text("OLD=1\n", encoding="utf-8")
        args = _make_args(
            non_interactive=True, home=str(tmp_path), overwrite=True
        )
        rc = cmd_setup(args)
        assert rc == 0


class TestReset:
    def test_reset_removes_existing_config(self, tmp_path: Path, capsys):
        (tmp_path / "config.yaml").write_text("provider: openai", encoding="utf-8")
        (tmp_path / ".env").write_text("OPENAI_API_KEY=test\n", encoding="utf-8")
        args = _make_args(reset=True, non_interactive=True, home=str(tmp_path))
        rc = cmd_setup(args)
        assert rc == 0
        assert "Reset" in capsys.readouterr().out


# ── section: model ─────────────────────────────────────────────────


class TestSectionModel:
    def test_non_interactive_writes_existing(self, tmp_path: Path):
        rc = cmd_setup_model(tmp_path, non_interactive=True)
        assert rc == 0
        assert (tmp_path / "config.yaml").exists()


# ── section: tts ───────────────────────────────────────────────────


class TestSectionTTS:
    def test_console_backend_non_interactive(self, tmp_path: Path):
        rc = cmd_setup_tts(tmp_path, non_interactive=True)
        assert rc == 0
        cfg = _load_existing_config(tmp_path)
        assert cfg["voice"]["backend"] == "console"

    def test_openai_backend_non_interactive(self, tmp_path: Path):
        rc = cmd_setup_tts(tmp_path, non_interactive=True)
        assert rc == 0
        (tmp_path / "config.yaml").write_text(
            "voice:\n  backend: openai\n  model: tts-1\n  voice: alloy\n",
            encoding="utf-8",
        )
        rc = cmd_setup_tts(tmp_path, non_interactive=True)
        assert rc == 0
        cfg = _load_existing_config(tmp_path)
        assert cfg["voice"]["backend"] == "openai"

    def test_elevenlabs_backend(self, tmp_path: Path):
        _merge_yaml(tmp_path, "voice.backend", "elevenlabs")
        rc = cmd_setup_tts(tmp_path, non_interactive=True)
        assert rc == 0
        cfg = _load_existing_config(tmp_path)
        assert cfg["voice"]["backend"] == "elevenlabs"

    def test_voice_backends_list(self):
        assert "console" in VOICE_BACKENDS
        assert "openai" in VOICE_BACKENDS
        assert "elevenlabs" in VOICE_BACKENDS

    def test_console_voice_test(self, tmp_path: Path, capsys):
        rc = cmd_setup_tts(tmp_path, non_interactive=True, test=True)
        assert rc == 0
        assert "TTS sample generated" in capsys.readouterr().out

    def test_elevenlabs_unavailable_without_key(self, tmp_path: Path, capsys):
        (tmp_path / "config.yaml").write_text(
            "voice:\n  backend: elevenlabs\n", encoding="utf-8"
        )
        rc = cmd_setup_tts_test(tmp_path)
        assert rc == 1
        assert "unavailable" in capsys.readouterr().out

    def test_voice_availability_helper(self):
        assert is_voice_backend_available(object()) is True
        assert is_voice_backend_available(type("Unavailable", (), {
            "is_available": lambda self: False,
        })()) is False


# ── section: terminal ──────────────────────────────────────────────


class TestSectionTerminal:
    def test_local_backend_non_interactive(self, tmp_path: Path):
        rc = cmd_setup_terminal(tmp_path, non_interactive=True)
        assert rc == 0
        cfg = _load_existing_config(tmp_path)
        assert cfg["terminal"]["backend"] == "local"

    def test_docker_backend_non_interactive(self, tmp_path: Path):
        _merge_yaml(tmp_path, "terminal.backend", "docker")
        rc = cmd_setup_terminal(tmp_path, non_interactive=True)
        assert rc == 0
        cfg = _load_existing_config(tmp_path)
        assert cfg["terminal"]["backend"] == "docker"
        assert "image" in cfg["terminal"]

    def test_ssh_backend_non_interactive(self, tmp_path: Path):
        _merge_yaml(tmp_path, "terminal.backend", "ssh")
        rc = cmd_setup_terminal(tmp_path, non_interactive=True)
        assert rc == 0
        cfg = _load_existing_config(tmp_path)
        assert cfg["terminal"]["backend"] == "ssh"
        assert "host" in cfg["terminal"]

    def test_terminal_backends_list(self):
        for backend in ["local", "docker", "ssh", "modal", "daytona"]:
            assert backend in TERMINAL_BACKENDS

    def test_local_terminal_test(self, tmp_path: Path, capsys):
        rc = cmd_setup_terminal(tmp_path, non_interactive=True, test=True)
        assert rc == 0
        assert "reachable" in capsys.readouterr().out

    def test_terminal_action_test_alias(self, tmp_path: Path, capsys):
        rc = cmd_setup_terminal_test(tmp_path)
        assert rc == 0
        assert "reachable" in capsys.readouterr().out

    def test_docker_probe_without_docker(self, monkeypatch, capsys):
        monkeypatch.setattr("zeloo_cli.subcommands.setup.shutil.which", lambda _name: None)
        ok, detail = _docker_daemon_status()
        assert ok is False
        assert "docker" in detail.lower()

    def test_ssh_key_path_preserved(self, tmp_path: Path):
        key_path = tmp_path / "id_ed25519"
        key_path.write_text("test", encoding="utf-8")
        _merge_yaml(tmp_path, "terminal.backend", "ssh")
        _merge_yaml(tmp_path, "terminal.key_path", str(key_path))
        rc = cmd_setup_terminal(tmp_path, non_interactive=True)
        assert rc == 0
        assert _load_existing_config(tmp_path)["terminal"]["key_path"] == str(key_path)


# ── section: gateway ───────────────────────────────────────────────


class TestSectionGateway:
    def test_writes_port(self, tmp_path: Path):
        rc = cmd_setup_gateway(tmp_path, non_interactive=True)
        assert rc == 0
        cfg = _load_existing_config(tmp_path)
        from gateway.api_server import DEFAULT_PORT
        assert cfg["gateway"]["api"]["port"] == DEFAULT_PORT

    def test_writes_auth_token_when_present(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setenv("ZELOO_API_KEY", "test-secret-abc123")
        rc = cmd_setup_gateway(tmp_path, non_interactive=True)
        assert rc == 0
        cfg = _load_existing_config(tmp_path)
        assert cfg["gateway"]["api"]["auth_token"] == "test-secret-abc123"


# ── section: tools ─────────────────────────────────────────────────


class TestSectionTools:
    def test_writes_toolsets(self, tmp_path: Path):
        rc = cmd_setup_tools(tmp_path, non_interactive=True)
        assert rc == 0
        cfg = _load_existing_config(tmp_path)
        assert "toolsets" in cfg
        assert isinstance(cfg["toolsets"], list)


# ── section: telemetry ─────────────────────────────────────────────


class TestSectionTelemetry:
    def test_default_observe_enabled(self, tmp_path: Path):
        rc = cmd_setup_telemetry(tmp_path, non_interactive=True)
        assert rc == 0
        cfg = _load_existing_config(tmp_path)
        assert cfg["observability"]["enabled"] is True
        assert cfg["observability"]["usage_tracking"]["enabled"] is True
        assert cfg["observability"]["langfuse"]["enabled"] is False

    def test_langfuse_keys_propagated(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
        _merge_yaml(tmp_path, "observability.langfuse.enabled", True)
        rc = cmd_setup_telemetry(tmp_path, non_interactive=True)
        assert rc == 0
        cfg = _load_existing_config(tmp_path)
        assert cfg["observability"]["langfuse"]["enabled"] is True


# ── section: agent ─────────────────────────────────────────────────


class TestSectionAgent:
    def test_writes_agent_defaults(self, tmp_path: Path):
        rc = cmd_setup_agent(tmp_path, non_interactive=True)
        assert rc == 0
        cfg = _load_existing_config(tmp_path)
        assert cfg["max_iterations"] == 25
        assert cfg["temperature"] == 0.0
        assert cfg["streaming"] is True

    def test_preserves_existing_values(self, tmp_path: Path):
        _merge_yaml(tmp_path, "max_iterations", 60)
        _merge_yaml(tmp_path, "temperature", 0.5)
        rc = cmd_setup_agent(tmp_path, non_interactive=True)
        assert rc == 0
        cfg = _load_existing_config(tmp_path)
        assert cfg["max_iterations"] == 60
        assert cfg["temperature"] == 0.5


# ── all sections smoke test ────────────────────────────────────────


class TestSectionHandlers:
    @pytest.mark.parametrize("section", SECTIONS)
    def test_each_section_runs(self, tmp_path: Path, section: str):
        args = _make_args(section=section, home=str(tmp_path))
        rc = cmd_setup(args)
        assert rc == 0

    def test_unknown_section_returns_1(self, tmp_path: Path):
        args = _make_args(section="bogus", home=str(tmp_path))
        rc = cmd_setup(args)
        assert rc == 1


# ── portal ─────────────────────────────────────────────────────────


class TestPortal:
    def test_portal_flow_returns_zero(self, tmp_path: Path):
        rc = cmd_setup_portal(tmp_path, non_interactive=True)
        assert rc == 0
        cfg = _load_existing_config(tmp_path)
        assert cfg.get("provider") == "openai"


# ── quick mode ────────────────────────────────────────────────────


class TestQuick:
    def test_quick_when_nothing_missing_returns_zero(self, tmp_path: Path):
        import os

        os.environ["OPENAI_API_KEY"] = "test-key"
        _merge_yaml(tmp_path, "provider", "openai")
        _merge_yaml(tmp_path, "model", "gpt-4o")
        args = _make_args(quick=True, home=str(tmp_path))
        rc = cmd_setup(args)
        assert rc == 0


# ── json output ───────────────────────────────────────────────────


class TestJsonOutput:
    def test_json_output_format(self, tmp_path: Path, capsys):
        args = _make_args(
            non_interactive=True, home=str(tmp_path), json=True
        )
        rc = cmd_setup(args)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "config" in data
        assert "env" in data


# ── helpers ───────────────────────────────────────────────────────


class TestHelpers:
    def test_merge_yaml_creates_file(self, tmp_path: Path):
        _merge_yaml(tmp_path, "voice.backend", "openai")
        cfg = _load_existing_config(tmp_path)
        assert cfg["voice"]["backend"] == "openai"

    def test_merge_yaml_preserves_other_keys(self, tmp_path: Path):
        _merge_yaml(tmp_path, "voice.backend", "openai")
        _merge_yaml(tmp_path, "voice.model", "tts-1")
        cfg = _load_existing_config(tmp_path)
        assert cfg["voice"]["backend"] == "openai"
        assert cfg["voice"]["model"] == "tts-1"

    def test_merge_yaml_nested(self, tmp_path: Path):
        _merge_yaml(tmp_path, "gateway.api.port", 9113)
        _merge_yaml(tmp_path, "gateway.api.auth_token", "secret")
        cfg = _load_existing_config(tmp_path)
        assert cfg["gateway"]["api"]["port"] == 9113
        assert cfg["gateway"]["api"]["auth_token"] == "secret"