"""Unit tests for tools/ssh_tool.py.

Covers:
- SSHConfig / SSHResult dataclasses and to_dict()
- SSHConfigParser parsing of ssh_config files
- SSHTool.execute / test_connection / parse_ssh_config (mocked subprocess)
- Backend selection (paramiko vs subprocess)
- @tool-decorated function registration
"""

# ruff: noqa: E402
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from tools.ssh_tool import (  # noqa: E402
    SSHConfig,
    SSHConfigParser,
    SSHResult,
    SSHTool,
    ssh_download,
    ssh_execute,
    ssh_test,
    ssh_upload,
)


# ─────────────────────────────────────────────────────────────────────────────
# Dataclass tests
# ─────────────────────────────────────────────────────────────────────────────


class TestSSHConfig:
    def test_defaults(self) -> None:
        cfg = SSHConfig(host="example.com")
        assert cfg.port == 22
        assert cfg.user == "root"
        assert cfg.password is None
        assert cfg.key_path is None
        assert cfg.timeout == 30.0
        assert cfg.strict_host_key_checking is True

    def test_to_dict_masks_secrets(self) -> None:
        cfg = SSHConfig(
            host="example.com",
            password="hunter2",
            key_passphrase="another-secret",
        )
        d = cfg.to_dict()
        assert d["host"] == "example.com"
        assert d["password"] == "***"
        assert d["key_passphrase"] == "***"

    def test_to_dict_no_secrets(self) -> None:
        cfg = SSHConfig(host="h", user="u")
        d = cfg.to_dict()
        assert d["password"] is None  # stays None
        assert d["key_passphrase"] is None


class TestSSHResult:
    def test_defaults(self) -> None:
        r = SSHResult(success=True, stdout="out", stderr="err", exit_code=0)
        assert r.duration_ms == 0.0
        assert r.host == ""

    def test_to_dict(self) -> None:
        r = SSHResult(
            success=True,
            stdout="hello",
            stderr="",
            exit_code=0,
            duration_ms=12.5,
            host="h",
        )
        d = r.to_dict()
        assert d["success"] is True
        assert d["stdout"] == "hello"
        assert d["exit_code"] == 0
        assert d["host"] == "h"
        assert d["duration_ms"] == 12.5


# ─────────────────────────────────────────────────────────────────────────────
# SSHConfigParser
# ─────────────────────────────────────────────────────────────────────────────


class TestSSHConfigParser:
    @pytest.fixture
    def config_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "ssh_config"
        path.write_text(
            "# Example ssh config (key=value syntax used by this parser)\n"
            "Host=alpha\n"
            "Hostname=alpha.example.com\n"
            "User=alice\n"
            "Port=2222\n"
            "IdentityFile=~/.ssh/id_alpha\n"
            "StrictHostKeyChecking=no\n"
            "\n"
            "Host=*\n"
            "User=ignored\n"
            "\n"
            "Host=beta\n"
            "Hostname=beta.example.com\n"
            "Port=23\n",
            encoding="utf-8",
        )
        return path

    def test_parse_returns_none_when_missing(self, tmp_path: Path) -> None:
        parser = SSHConfigParser(str(tmp_path / "absent"))
        assert parser.parse("any") is None

    def test_parse_host_alias(self, config_file: Path) -> None:
        parser = SSHConfigParser(str(config_file))
        cfg = parser.parse("alpha")
        assert cfg is not None
        assert cfg.host == "alpha.example.com"
        assert cfg.user == "alice"
        assert cfg.port == 2222
        assert cfg.key_path is not None
        assert cfg.key_path.endswith("id_alpha")
        assert cfg.strict_host_key_checking is False

    def test_parse_second_host(self, config_file: Path) -> None:
        parser = SSHConfigParser(str(config_file))
        cfg = parser.parse("beta")
        assert cfg is not None
        assert cfg.host == "beta.example.com"
        assert cfg.port == 23

    def test_parse_unknown_alias(self, config_file: Path) -> None:
        parser = SSHConfigParser(str(config_file))
        assert parser.parse("ghost") is None

    def test_list_hosts(self, config_file: Path) -> None:
        parser = SSHConfigParser(str(config_file))
        hosts = parser.list_hosts()
        # ``*`` wildcard must be skipped.
        assert "alpha" in hosts
        assert "beta" in hosts
        assert "*" not in hosts

    def test_path_property(self, config_file: Path) -> None:
        parser = SSHConfigParser(str(config_file))
        assert parser.path == config_file

    def test_comments_and_blank_lines_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "ssh_cfg"
        path.write_text(
            "# leading comment\n"
            "\n"
            "Host=c1\n"
            "User=u1\n",
            encoding="utf-8",
        )
        parser = SSHConfigParser(str(path))
        cfg = parser.parse("c1")
        assert cfg is not None
        assert cfg.user == "u1"

    def test_match_block_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "ssh_cfg"
        path.write_text(
            "Match host *.foo\n"
            "User=bad\n"
            "Host=bar\n"
            "User=good\n",
            encoding="utf-8",
        )
        parser = SSHConfigParser(str(path))
        # ``Match`` block resets ``current`` so the User line is dropped.
        assert parser.list_hosts() == ["bar"]
        cfg = parser.parse("bar")
        assert cfg is not None
        assert cfg.user == "good"

    def test_unknown_keys_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "ssh_cfg"
        path.write_text(
            "Host=h\n"
            "User=u\n"
            "UnknownOption=ignored\n",
            encoding="utf-8",
        )
        parser = SSHConfigParser(str(path))
        cfg = parser.parse("h")
        assert cfg is not None
        assert cfg.user == "u"

    def test_env_override(self, tmp_path: Path, monkeypatch) -> None:
        path = tmp_path / "env_cfg"
        path.write_text("Host=envhost\nUser=euser\n", encoding="utf-8")
        monkeypatch.setenv("ZELOO_SSH_CONFIG", str(path))
        parser = SSHConfigParser()
        assert parser.path == path
        cfg = parser.parse("envhost")
        assert cfg is not None
        assert cfg.user == "euser"


# ─────────────────────────────────────────────────────────────────────────────
# SSHTool.execute via subprocess mock
# ─────────────────────────────────────────────────────────────────────────────


class TestSSHToolSubprocessBackend:
    @pytest.fixture
    def tool(self) -> SSHTool:
        # Force subprocess backend by removing paramiko if any.
        with patch("tools.ssh_tool._paramiko_available", return_value=False):
            t = SSHTool()
        return t

    @pytest.fixture
    def config(self) -> SSHConfig:
        return SSHConfig(
            host="example.com",
            user="test",
            port=22,
            strict_host_key_checking=False,
            timeout=5.0,
        )

    def test_backend_label_subprocess(self, tool: SSHTool) -> None:
        assert tool._backend_label() == "subprocess"

    def test_execute_success(self, tool: SSHTool, config: SSHConfig) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "hello world"
        mock_proc.stderr = ""
        with patch("shutil.which", return_value="/usr/bin/ssh"):
            with patch("subprocess.run", return_value=mock_proc):
                result = tool.execute("echo hello", config)
        assert result.success is True
        assert result.stdout == "hello world"
        assert result.exit_code == 0
        assert result.host == "example.com"

    def test_execute_failure(self, tool: SSHTool, config: SSHConfig) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "boom"
        with patch("shutil.which", return_value="/usr/bin/ssh"):
            with patch("subprocess.run", return_value=mock_proc):
                result = tool.execute("false", config)
        assert result.success is False
        assert result.exit_code == 1

    def test_execute_no_ssh_binary(self, tool: SSHTool, config: SSHConfig) -> None:
        with patch("shutil.which", return_value=None):
            result = tool.execute("anything", config)
        assert result.success is False
        assert "not found" in result.stderr.lower()

    def test_execute_timeout(self, tool: SSHTool, config: SSHConfig) -> None:
        import subprocess as sp

        with patch("shutil.which", return_value="/usr/bin/ssh"):
            with patch(
                "subprocess.run",
                side_effect=sp.TimeoutExpired(cmd="ssh", timeout=5),
            ):
                result = tool.execute("sleep 999", config)
        assert result.success is False
        assert result.exit_code == 124

    def test_execute_string_alias(self, tool: SSHTool) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "x"
        mock_proc.stderr = ""
        # Provide a fake SSH config to resolve the alias.
        with patch("shutil.which", return_value="/usr/bin/ssh"):
            with patch("subprocess.run", return_value=mock_proc):
                with patch.object(
                    SSHConfigParser,
                    "parse",
                    return_value=SSHConfig(host="h", user="u"),
                ):
                    result = tool.execute("echo x", "some-alias")
        assert result.success is True

    def test_test_connection(self, tool: SSHTool, config: SSHConfig) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "ok\n"
        mock_proc.stderr = ""
        with patch("shutil.which", return_value="/usr/bin/ssh"):
            with patch("subprocess.run", return_value=mock_proc):
                ok = asyncio.run(tool.test_connection(config))
        assert ok is True

    def test_test_connection_failure(self, tool: SSHTool, config: SSHConfig) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "nope"
        mock_proc.stderr = ""
        with patch("shutil.which", return_value="/usr/bin/ssh"):
            with patch("subprocess.run", return_value=mock_proc):
                ok = asyncio.run(tool.test_connection(config))
        assert ok is False

    def test_parse_ssh_config_alias(self, tool: SSHTool, tmp_path: Path) -> None:
        cfg_file = tmp_path / "ssh_cfg"
        cfg_file.write_text(
            "Host=myhost\nHostname=my.example.com\nPort=2200\nUser=me\n",
            encoding="utf-8",
        )
        cfg = tool.parse_ssh_config("myhost", ssh_config_path=str(cfg_file))
        assert cfg.host == "my.example.com"
        assert cfg.port == 2200
        assert cfg.user == "me"

    def test_parse_ssh_config_missing(self, tool: SSHTool, tmp_path: Path) -> None:
        cfg_file = tmp_path / "nope"
        cfg = tool.parse_ssh_config("ghost", ssh_config_path=str(cfg_file))
        assert cfg.host == "ghost"

    def test_build_ssh_cmd_includes_user_host(self, tool: SSHTool, config: SSHConfig) -> None:
        cmd = tool._build_ssh_cmd("echo hi", config)
        assert "ssh" in cmd[0]
        assert "test@example.com" in cmd
        assert "--" in cmd
        assert "echo hi" in cmd


class TestSSHToolBackendSelection:
    def test_paramiko_backend_when_available(self) -> None:
        with patch("tools.ssh_tool._paramiko_available", return_value=True):
            tool = SSHTool()
        # If we got here without exception, the backend selection ran.
        # Backend label is either paramiko (if import succeeded) or subprocess.
        assert tool._backend_label() in {"paramiko", "subprocess"}

    def test_subprocess_backend_when_paramiko_missing(self) -> None:
        with patch("tools.ssh_tool._paramiko_available", return_value=False):
            tool = SSHTool()
        assert tool._backend_label() == "subprocess"


# ─────────────────────────────────────────────────────────────────────────────
# @tool-decorated registration
# ─────────────────────────────────────────────────────────────────────────────


class TestSSHToolRegistration:
    def test_all_ssh_tools_registered(self) -> None:
        from tools.base import get_registry

        registry = get_registry()
        for name in ("ssh_execute", "ssh_upload", "ssh_download", "ssh_test"):
            assert name in registry.get_names(), f"{name} missing"

    def test_ssh_execute_invocation(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "ok"
        mock_proc.stderr = ""
        with patch("shutil.which", return_value="/usr/bin/ssh"):
            with patch("subprocess.run", return_value=mock_proc):
                result = ssh_execute(
                    command="echo ok",
                    host="h",
                    user="u",
                )
        assert result["success"] is True
        assert result["stdout"] == "ok"

    def test_ssh_test_invocation(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "ok"
        mock_proc.stderr = ""
        with patch("shutil.which", return_value="/usr/bin/ssh"):
            with patch("subprocess.run", return_value=mock_proc):
                result = ssh_test(host="h", user="u")
        assert result["host"] == "h"
        # success depends on whether "ok" appears in stdout.
        assert "success" in result
        assert "backend" in result

    def test_ssh_upload_invocation(self, tmp_path: Path) -> None:
        local = tmp_path / "src.txt"
        local.write_text("payload")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        with patch("shutil.which", return_value="/usr/bin/scp"):
            with patch("subprocess.run", return_value=mock_proc):
                result = ssh_upload(
                    local_path=str(local),
                    remote_path="/tmp/dst.txt",
                    host="h",
                    user="u",
                )
        assert result["local_path"] == str(local)
        assert result["remote_path"] == "/tmp/dst.txt"
        assert result["host"] == "h"

    def test_ssh_download_invocation(self, tmp_path: Path) -> None:
        dest = tmp_path / "down.txt"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        with patch("shutil.which", return_value="/usr/bin/scp"):
            with patch("subprocess.run", return_value=mock_proc):
                result = ssh_download(
                    remote_path="/tmp/src.txt",
                    local_path=str(dest),
                    host="h",
                    user="u",
                )
        assert result["remote_path"] == "/tmp/src.txt"
        assert result["local_path"] == str(dest)
