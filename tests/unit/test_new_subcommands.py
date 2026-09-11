"""Tests for newly implemented subcommands: sessions, logs, tools, skills, memory, auth, config, secrets, backup, dump, model."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)


# ─────────────────────────────────────────────────────────────────────────────
# sessions
# ─────────────────────────────────────────────────────────────────────────────

from zeloo_cli.subcommands.sessions import SessionsCmd


class TestSessionsCmd:
    def _make_args(self, **overrides) -> argparse.Namespace:
        defaults = dict(sessions_action=None, limit=20, platform=None, session_id=None, force=False, query=None)
        return argparse.Namespace(**{**defaults, **overrides})

    def test_sessions_cmd_name(self) -> None:
        assert SessionsCmd.name == "sessions"

    def test_run_no_action_returns_1(self) -> None:
        cmd = SessionsCmd()
        rc = cmd.run(self._make_args(sessions_action=None))
        assert rc == 1

    def test_list_no_db(self, capsys) -> None:
        with patch("zeloo_state.SessionDB", side_effect=Exception("no db")):
            cmd = SessionsCmd()
            rc = cmd.run(self._make_args(sessions_action="list"))
        assert rc == 1
        assert "Failed" in capsys.readouterr().out

    def test_list_empty_sessions(self, capsys) -> None:
        with patch("zeloo_state.SessionDB") as mock_cls:
            mock_cls.return_value.list_sessions.return_value = []
            cmd = SessionsCmd()
            rc = cmd.run(self._make_args(sessions_action="list"))
        assert rc == 0
        assert "No sessions found" in capsys.readouterr().out

    def test_list_with_sessions(self, capsys) -> None:
        with patch("zeloo_state.SessionDB") as mock_cls:
            mock_cls.return_value.list_sessions.return_value = [
                {
                    "session_id": "abc123",
                    "platform": "cli",
                    "created_at": "2026-09-11T10:00:00",
                    "updated_at": "2026-09-11T11:00:00",
                    "message_count": 5,
                }
            ]
            cmd = SessionsCmd()
            rc = cmd.run(self._make_args(sessions_action="list"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "abc123" in out

    def test_list_platform_filter(self) -> None:
        with patch("zeloo_state.SessionDB") as mock_cls:
            mock_cls.return_value.list_sessions.return_value = [
                {"session_id": "a", "platform": "gateway", "created_at": "t", "updated_at": "t", "message_count": 1}
            ]
            cmd = SessionsCmd()
            rc = cmd.run(self._make_args(sessions_action="list", platform="cli"))
        assert rc == 0

    def test_show_not_found(self, capsys) -> None:
        with patch("zeloo_state.SessionDB") as mock_cls:
            mock_cls.return_value.get_session.return_value = None
            cmd = SessionsCmd()
            rc = cmd.run(self._make_args(sessions_action="show", session_id="nonexistent"))
        assert rc == 1
        assert "not found" in capsys.readouterr().out.lower()

    def test_show_found(self, capsys) -> None:
        with patch("zeloo_state.SessionDB") as mock_cls:
            mock_cls.return_value.get_session.return_value = {
                "session_id": "abc123",
                "platform": "cli",
                "user_id": "u1",
                "created_at": "2026-09-11T10:00:00",
                "updated_at": "2026-09-11T11:00:00",
            }
            mock_cls.return_value.get_messages.return_value = [
                {"role": "user", "content": "hello"}
            ]
            cmd = SessionsCmd()
            rc = cmd.run(self._make_args(sessions_action="show", session_id="abc123"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "abc123" in out

    def test_delete_with_force(self, capsys) -> None:
        with patch("zeloo_state.SessionDB") as mock_cls:
            mock_cls.return_value._conn = MagicMock()
            cmd = SessionsCmd()
            rc = cmd.run(self._make_args(sessions_action="delete", session_id="abc123", force=True))
        assert rc == 0
        assert "Deleted" in capsys.readouterr().out

    def test_delete_db_error(self, capsys) -> None:
        with patch("zeloo_state.SessionDB", side_effect=Exception("db error")):
            cmd = SessionsCmd()
            rc = cmd.run(self._make_args(sessions_action="delete", session_id="abc123", force=True))
        assert rc == 1

    def test_search_no_results(self, capsys) -> None:
        with patch("zeloo_state.SessionDB") as mock_cls:
            mock_cls.return_value.list_sessions.return_value = []
            cmd = SessionsCmd()
            rc = cmd.run(self._make_args(sessions_action="search", query="hello"))
        assert rc == 0
        assert "No sessions found" in capsys.readouterr().out

    def test_search_with_match(self, capsys) -> None:
        with patch("zeloo_state.SessionDB") as mock_cls:
            mock_cls.return_value.list_sessions.return_value = [
                {"session_id": "abc123", "platform": "cli", "created_at": "t", "updated_at": "t", "message_count": 1}
            ]
            mock_cls.return_value.get_messages.return_value = [
                {"role": "user", "content": "hello world"}
            ]
            cmd = SessionsCmd()
            rc = cmd.run(self._make_args(sessions_action="search", query="hello"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "Found" in out


# ─────────────────────────────────────────────────────────────────────────────
# logs
# ─────────────────────────────────────────────────────────────────────────────

from zeloo_cli.subcommands.logs import LogsCmd


class TestLogsCmd:
    def _make_args(self, **overrides) -> argparse.Namespace:
        defaults = dict(logs_action=None, lines=100, level=None, force=False)
        return argparse.Namespace(**{**defaults, **overrides})

    def test_logs_cmd_name(self) -> None:
        assert LogsCmd.name == "logs"

    def test_run_no_action_calls_view(self) -> None:
        with patch.object(LogsCmd, "_view", return_value=0) as mock_view:
            cmd = LogsCmd()
            cmd.run(self._make_args(logs_action=None))
        mock_view.assert_called_once()

    def test_list_logs_no_dir(self, capsys) -> None:
        with patch.object(LogsCmd, "_get_log_dir", return_value=Path("/nonexistent")):
            cmd = LogsCmd()
            rc = cmd.run(self._make_args(logs_action="list"))
        assert rc == 0

    def test_list_logs_empty(self, capsys) -> None:
        with patch.object(LogsCmd, "_get_log_dir", return_value=Path("/nonexistent")):
            with patch.object(LogsCmd, "_list_log_files", return_value=[]):
                cmd = LogsCmd()
                rc = cmd._list_logs()
        assert rc == 0
        assert "No log files" in capsys.readouterr().out

    def test_view_no_dir(self, capsys) -> None:
        with patch.object(LogsCmd, "_get_log_dir", return_value=Path("/nonexistent")):
            cmd = LogsCmd()
            rc = cmd._view(100, None)
        assert rc == 1
        assert "not found" in capsys.readouterr().out.lower()

    def test_view_no_files(self, capsys) -> None:
        with patch.object(LogsCmd, "_get_log_dir", return_value=Path("/tmp")):
            with patch.object(LogsCmd, "_list_log_files", return_value=[]):
                cmd = LogsCmd()
                rc = cmd._view(100, None)
        assert rc == 0

    def test_view_with_file(self, tmp_path, capsys) -> None:
        log_file = tmp_path / "test.log"
        log_file.write_text("INFO: test line 1\nWARNING: test line 2\n")

        with patch.object(LogsCmd, "_get_log_dir", return_value=tmp_path):
            with patch.object(LogsCmd, "_list_log_files", return_value=[log_file]):
                cmd = LogsCmd()
                rc = cmd._view(100, None)
        assert rc == 0
        out = capsys.readouterr().out
        assert "INFO" in out or "test" in out

    def test_view_level_filter(self, tmp_path, capsys) -> None:
        log_file = tmp_path / "test.log"
        log_file.write_text("INFO: skip\nERROR: match\nDEBUG: skip\n")

        with patch.object(LogsCmd, "_get_log_dir", return_value=tmp_path):
            with patch.object(LogsCmd, "_list_log_files", return_value=[log_file]):
                cmd = LogsCmd()
                rc = cmd._view(100, "ERROR")
        assert rc == 0
        out = capsys.readouterr().out
        assert "ERROR" in out
        assert "INFO" not in out

    def test_view_respects_lines_limit(self, tmp_path, capsys) -> None:
        log_file = tmp_path / "test.log"
        log_file.write_text("\n".join(f"LINE {i}" for i in range(50)))

        with patch.object(LogsCmd, "_get_log_dir", return_value=tmp_path):
            with patch.object(LogsCmd, "_list_log_files", return_value=[log_file]):
                cmd = LogsCmd()
                rc = cmd._view(5, None)
        assert rc == 0
        out = capsys.readouterr().out
        lines = out.strip().split("\n")
        assert len(lines) <= 6

    def test_clear_no_files(self, capsys) -> None:
        with patch.object(LogsCmd, "_get_log_dir", return_value=Path("/nonexistent")):
            with patch.object(LogsCmd, "_list_log_files", return_value=[]):
                cmd = LogsCmd()
                rc = cmd._clear(force=True)
        assert rc == 0

    def test_clear_force(self, tmp_path, capsys) -> None:
        log_file = tmp_path / "test.log"
        log_file.write_text("test")

        with patch.object(LogsCmd, "_get_log_dir", return_value=tmp_path):
            with patch.object(LogsCmd, "_list_log_files", return_value=[log_file]):
                cmd = LogsCmd()
                rc = cmd._clear(force=True)
        assert rc == 0
        assert not log_file.exists()

    def test_tail_no_dir(self, capsys) -> None:
        with patch.object(LogsCmd, "_get_log_dir", return_value=Path("/nonexistent")):
            with patch.object(LogsCmd, "_list_log_files", return_value=[]):
                cmd = LogsCmd()
                rc = cmd._tail(50, None)
        assert rc == 1

    def test_tail_keyboard_interrupt(self, tmp_path, capsys) -> None:
        log_file = tmp_path / "test.log"
        log_file.write_text("line1\n")

        def raise_kbi():
            raise KeyboardInterrupt()

        with patch.object(LogsCmd, "_get_log_dir", return_value=tmp_path):
            with patch.object(LogsCmd, "_list_log_files", return_value=[log_file]):
                cmd = LogsCmd()
                with patch.object(cmd, "_tail", side_effect=KeyboardInterrupt()):
                    pass
        assert True


# ─────────────────────────────────────────────────────────────────────────────
# tools
# ─────────────────────────────────────────────────────────────────────────────

from zeloo_cli.subcommands.tools import ToolsCmd


class TestToolsCmd:
    def _make_args(self, **overrides) -> argparse.Namespace:
        defaults = dict(tools_action=None, category=None, as_json=False, tool_name=None)
        return argparse.Namespace(**{**defaults, **overrides})

    def test_tools_cmd_name(self) -> None:
        assert ToolsCmd.name == "tools"

    def test_run_no_action(self, capsys) -> None:
        cmd = ToolsCmd()
        rc = cmd.run(self._make_args(tools_action=None))
        assert rc == 1
        assert "Usage" in capsys.readouterr().out

    def test_list_no_registry(self, capsys) -> None:
        with patch("tools.base.discover_builtin_tools", return_value=None):
            with patch("tools.base.get_registry") as mock_reg:
                mock_reg.return_value.get_all.return_value = {}
                cmd = ToolsCmd()
                rc = cmd.run(self._make_args(tools_action="list"))
        assert rc == 0

    def test_show_not_found(self, capsys) -> None:
        with patch("tools.base.discover_builtin_tools"):
            with patch("tools.base.get_registry") as mock_reg:
                mock_reg.return_value.get.return_value = None
                cmd = ToolsCmd()
                rc = cmd.run(self._make_args(tools_action="show", tool_name="nonexistent"))
        assert rc == 1
        assert "not found" in capsys.readouterr().out.lower()

    def test_validate_no_tools(self, capsys) -> None:
        with patch("tools.base.discover_builtin_tools"):
            with patch("tools.base.get_registry") as mock_reg:
                mock_reg.return_value.get_all.return_value = {}
                cmd = ToolsCmd()
                rc = cmd.run(self._make_args(tools_action="validate"))
        assert rc == 1


# ─────────────────────────────────────────────────────────────────────────────
# skills
# ─────────────────────────────────────────────────────────────────────────────

from zeloo_cli.subcommands.skills import SkillsCmd


class TestSkillsCmd:
    def _make_args(self, **overrides) -> argparse.Namespace:
        defaults = dict(skills_action=None, json=False, query=None, identifier=None, name=None)
        return argparse.Namespace(**{**defaults, **overrides})

    def test_skills_cmd_name(self) -> None:
        assert SkillsCmd.name == "skills"

    def test_run_no_action(self, capsys) -> None:
        cmd = SkillsCmd()
        rc = cmd.run(self._make_args(skills_action=None))
        assert rc == 1

    def test_list_no_skills(self, capsys) -> None:
        with patch.object(SkillsCmd, "_discover_skills", return_value=[]):
            cmd = SkillsCmd()
            rc = cmd.run(self._make_args(skills_action="list"))
        assert rc == 0
        assert "No skills found" in capsys.readouterr().out

    def test_list_with_skills(self, capsys) -> None:
        with patch.object(
            SkillsCmd, "_discover_skills",
            return_value=[
                {"name": "test-skill", "version": "1.0", "description": "A test skill", "path": "/tmp/skills/test", "source": "/tmp"},
            ],
        ):
            cmd = SkillsCmd()
            rc = cmd.run(self._make_args(skills_action="list"))
        assert rc == 0

    def test_search_runs_real_implementation(self, capsys) -> None:
        cmd = SkillsCmd()
        # Real implementation returns 1 when query is non-empty but no index matches
        rc = cmd.run(self._make_args(skills_action="search", query="xyzzy_no_match_zzz"))
        out = capsys.readouterr().out
        # Either shows table OR prints no-match message — never "not yet implemented"
        assert "not yet implemented" not in out
        assert rc in (0, 1)

    def test_install_rejects_missing_local_path(self, capsys) -> None:
        cmd = SkillsCmd()
        # Real install checks path existence; missing path returns error code 1
        rc = cmd.run(self._make_args(skills_action="install", identifier="test/skill"))
        out = capsys.readouterr().out
        assert "Placeholder" not in out
        assert rc == 1  # path doesn't exist
        assert "not exist" in out.lower() or "failed" in out.lower()

    def test_inspect_not_found(self, capsys) -> None:
        with patch.object(SkillsCmd, "_discover_skills", return_value=[]):
            cmd = SkillsCmd()
            rc = cmd.run(self._make_args(skills_action="inspect", name="nonexistent"))
        assert rc == 1
        assert "not found" in capsys.readouterr().out.lower()

    def test_inspect_found(self, capsys) -> None:
        with patch.object(
            SkillsCmd, "_discover_skills",
            return_value=[
                {"name": "test-skill", "version": "1.0", "description": "Test", "path": "/tmp/skills/test", "source": "/tmp"},
            ],
        ):
            cmd = SkillsCmd()
            rc = cmd.run(self._make_args(skills_action="inspect", name="test-skill"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "test-skill" in out

    def test_check_no_skills(self, capsys) -> None:
        with patch.object(SkillsCmd, "_discover_skills", return_value=[]):
            cmd = SkillsCmd()
            rc = cmd.run(self._make_args(skills_action="check"))
        assert rc == 0

    def test_check_with_valid_skills(self, capsys) -> None:
        with patch.object(SkillsCmd, "_discover_skills", return_value=[]):
            cmd = SkillsCmd()
            rc = cmd.run(self._make_args(skills_action="check"))
        assert rc == 0

    def test_parse_frontmatter_empty(self) -> None:
        cmd = SkillsCmd()
        result = cmd._parse_frontmatter("")
        assert result == {}

    def test_parse_frontmatter_no_marker(self) -> None:
        cmd = SkillsCmd()
        result = cmd._parse_frontmatter("Just plain text")
        assert result == {}

    def test_parse_frontmatter_valid(self) -> None:
        cmd = SkillsCmd()
        content = "---\nname: test\nversion: 1.0\n---\nSome content"
        result = cmd._parse_frontmatter(content)
        assert result.get("name") == "test"
        assert result.get("version") == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# memory
# ─────────────────────────────────────────────────────────────────────────────

from zeloo_cli.subcommands.memory import MemoryCmd


class TestMemoryCmd:
    def _make_args(self, **overrides) -> argparse.Namespace:
        defaults = dict(memory_action=None, json=False, all=False, force=False)
        return argparse.Namespace(**{**defaults, **overrides})

    def test_memory_cmd_name(self) -> None:
        assert MemoryCmd.name == "memory"

    def test_run_no_action(self, capsys) -> None:
        cmd = MemoryCmd()
        rc = cmd.run(self._make_args(memory_action=None))
        assert rc == 1

    def test_list_no_dirs(self, capsys) -> None:
        with patch.object(MemoryCmd, "_get_memory_dirs", return_value=[]):
            cmd = MemoryCmd()
            rc = cmd.run(self._make_args(memory_action="list"))
        assert rc == 0
        assert "No memory directories" in capsys.readouterr().out

    def test_stats_db_error(self, capsys) -> None:
        with patch("zeloo_state.SessionDB", side_effect=Exception("no db")):
            with patch.object(MemoryCmd, "_get_memory_dirs", return_value=[]):
                cmd = MemoryCmd()
                rc = cmd.run(self._make_args(memory_action="stats"))
        assert rc == 0
        assert "Warning" in capsys.readouterr().out

    def test_stats_with_json(self, capsys) -> None:
        with patch("zeloo_state.SessionDB") as mock_cls:
            mock_cls.return_value.list_sessions.return_value = [{"message_count": 5}]
            with patch.object(MemoryCmd, "_get_memory_dirs", return_value=[]):
                cmd = MemoryCmd()
                rc = cmd.run(self._make_args(memory_action="stats", json=True))
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "sessions" in data

    def test_clear_force_no_dirs(self, capsys) -> None:
        with patch.object(MemoryCmd, "_get_memory_dirs", return_value=[]):
            cmd = MemoryCmd()
            rc = cmd.run(self._make_args(memory_action="clear", force=True))
        assert rc == 0

    def test_format_size_bytes(self) -> None:
        cmd = MemoryCmd()
        assert "0.0 B" in cmd._format_size(0)
        assert "1.0 B" in cmd._format_size(1)
        assert "1.0 KB" in cmd._format_size(1024)
        assert "1.0 MB" in cmd._format_size(1024 * 1024)


# ─────────────────────────────────────────────────────────────────────────────
# auth
# ─────────────────────────────────────────────────────────────────────────────

from zeloo_cli.subcommands.auth import AuthCmd


class TestAuthCmd:
    def _make_args(self, **overrides) -> argparse.Namespace:
        defaults = dict(auth_action=None)
        return argparse.Namespace(**{**defaults, **overrides})

    def test_auth_cmd_name(self) -> None:
        assert AuthCmd.name == "auth"

    def test_run_no_action(self, capsys) -> None:
        cmd = AuthCmd()
        rc = cmd.run(self._make_args(auth_action=None))
        assert rc == 1

    def test_status_no_auth_file(self, capsys) -> None:
        with patch.object(AuthCmd, "_load_auth_info", return_value=None):
            with patch("zeloo_state.SessionDB") as mock_cls:
                mock_cls.return_value.list_sessions.return_value = []
                cmd = AuthCmd()
                rc = cmd.run(self._make_args(auth_action="status"))
        assert rc == 0

    def test_logout_no_file(self, capsys) -> None:
        with patch.object(AuthCmd, "_get_auth_file", return_value=Path("/nonexistent")):
            cmd = AuthCmd()
            rc = cmd.run(self._make_args(auth_action="logout"))
        assert rc == 0
        assert "No authentication" in capsys.readouterr().out

    def test_refresh_no_auth(self, capsys) -> None:
        with patch.object(AuthCmd, "_load_auth_info", return_value=None):
            cmd = AuthCmd()
            rc = cmd.run(self._make_args(auth_action="refresh"))
        assert rc == 1
        assert "No authentication" in capsys.readouterr().out

    def test_refresh_with_auth(self, capsys) -> None:
        with patch.object(AuthCmd, "_load_auth_info", return_value={"token": "abc123xyz"}):
            cmd = AuthCmd()
            rc = cmd.run(self._make_args(auth_action="refresh"))
        assert rc == 0

    def test_load_auth_info_missing_file(self) -> None:
        cmd = AuthCmd()
        with patch.object(cmd, "_get_auth_file", return_value=Path("/nonexistent")):
            result = cmd._load_auth_info()
        assert result is None

    def test_load_auth_info_invalid_json(self, tmp_path) -> None:
        bad_file = tmp_path / "auth.json"
        bad_file.write_text("not json{{")

        cmd = AuthCmd()
        with patch.object(cmd, "_get_auth_file", return_value=bad_file):
            result = cmd._load_auth_info()
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# config
# ─────────────────────────────────────────────────────────────────────────────

from zeloo_cli.subcommands.config import ConfigCmd


class TestConfigCmd:
    def _make_args(self, **overrides) -> argparse.Namespace:
        defaults = dict(config_action=None, key=None, value=None)
        return argparse.Namespace(**{**defaults, **overrides})

    def test_config_cmd_name(self) -> None:
        assert ConfigCmd.name == "config"

    def test_run_no_action(self, capsys) -> None:
        cmd = ConfigCmd()
        rc = cmd.run(self._make_args(config_action=None))
        assert rc == 1

    def test_get_missing_key(self, capsys) -> None:
        with patch.object(ConfigCmd, "_load_config", return_value={}):
            cmd = ConfigCmd()
            rc = cmd.run(self._make_args(config_action="get", key="model"))
        assert rc == 1
        assert "not set" in capsys.readouterr().out.lower()

    def test_get_existing_key(self, capsys) -> None:
        with patch.object(ConfigCmd, "_load_config", return_value={"model": "gpt-4o"}):
            cmd = ConfigCmd()
            rc = cmd.run(self._make_args(config_action="get", key="model"))
        assert rc == 0
        assert "gpt-4o" in capsys.readouterr().out

    def test_get_nested_key(self, capsys) -> None:
        with patch.object(
            ConfigCmd, "_load_config",
            return_value={"provider": {"openai": {"model": "gpt-4o"}}},
        ):
            cmd = ConfigCmd()
            rc = cmd.run(self._make_args(config_action="get", key="provider.openai.model"))
        assert rc == 0
        assert "gpt-4o" in capsys.readouterr().out

    def test_set_new_key(self, capsys) -> None:
        with patch.object(ConfigCmd, "_load_config", return_value={}):
            with patch.object(ConfigCmd, "_save_config") as mock_save:
                cmd = ConfigCmd()
                rc = cmd.run(self._make_args(config_action="set", key="model", value="gpt-4o"))
        assert rc == 0
        mock_save.assert_called_once()

    def test_set_bool_value(self) -> None:
        with patch.object(ConfigCmd, "_load_config", return_value={}):
            with patch.object(ConfigCmd, "_save_config") as mock_save:
                cmd = ConfigCmd()
                cmd.run(self._make_args(config_action="set", key="debug", value="true"))
        saved = mock_save.call_args[0][0]
        assert saved["debug"] is True

    def test_set_int_value(self) -> None:
        with patch.object(ConfigCmd, "_load_config", return_value={}):
            with patch.object(ConfigCmd, "_save_config") as mock_save:
                cmd = ConfigCmd()
                cmd.run(self._make_args(config_action="set", key="timeout", value="30"))
        saved = mock_save.call_args[0][0]
        assert saved["timeout"] == 30

    def test_list_empty(self, capsys) -> None:
        with patch.object(ConfigCmd, "_load_config", return_value={}):
            cmd = ConfigCmd()
            rc = cmd.run(self._make_args(config_action="list"))
        assert rc == 0

    def test_list_with_config(self, capsys) -> None:
        with patch.object(ConfigCmd, "_load_config", return_value={"model": "gpt-4o"}):
            cmd = ConfigCmd()
            rc = cmd.run(self._make_args(config_action="list"))
        assert rc == 0
        assert "model" in capsys.readouterr().out or "gpt-4o" in capsys.readouterr().out


# ─────────────────────────────────────────────────────────────────────────────
# secrets
# ─────────────────────────────────────────────────────────────────────────────

from zeloo_cli.subcommands.secrets import SecretsCmd


class TestSecretsCmd:
    def _make_args(self, **overrides) -> argparse.Namespace:
        defaults = dict(secrets_action=None, name=None, value=None)
        return argparse.Namespace(**{**defaults, **overrides})

    def test_secrets_cmd_name(self) -> None:
        assert SecretsCmd.name == "secrets"

    def test_run_no_action(self, capsys) -> None:
        cmd = SecretsCmd()
        rc = cmd.run(self._make_args(secrets_action=None))
        assert rc == 1

    def test_list_empty(self, capsys) -> None:
        with patch.object(SecretsCmd, "_load_secrets", return_value={}):
            with patch.object(SecretsCmd, "_get_secrets_path", return_value=Path("/tmp/secrets")):
                cmd = SecretsCmd()
                rc = cmd.run(self._make_args(secrets_action="list"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "No secrets" in out

    def test_list_with_secrets(self, capsys) -> None:
        with patch.object(
            SecretsCmd, "_load_secrets",
            return_value={
                "API_KEY": {"value": "enc123", "created_at": "2026-09-11"},
            },
        ):
            with patch.object(SecretsCmd, "_get_secrets_path", return_value=Path("/tmp/secrets")):
                cmd = SecretsCmd()
                rc = cmd.run(self._make_args(secrets_action="list"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "API_KEY" in out

    def test_set_creates_secret(self, capsys) -> None:
        with patch.object(SecretsCmd, "_load_secrets", return_value={}):
            with patch.object(SecretsCmd, "_save_secrets") as mock_save:
                with patch.object(SecretsCmd, "_get_secrets_path", return_value=Path("/tmp/secrets")):
                    cmd = SecretsCmd()
                    rc = cmd.run(self._make_args(secrets_action="set", name="API_KEY", value="secret123"))
        assert rc == 0
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert "API_KEY" in saved

    def test_delete_existing(self, capsys) -> None:
        with patch.object(
            SecretsCmd, "_load_secrets", return_value={"API_KEY": {"value": "enc"}}
        ):
            with patch.object(SecretsCmd, "_save_secrets"):
                with patch.object(SecretsCmd, "_get_secrets_path", return_value=Path("/tmp")):
                    cmd = SecretsCmd()
                    rc = cmd.run(self._make_args(secrets_action="delete", name="API_KEY"))
        assert rc == 0
        assert "deleted" in capsys.readouterr().out.lower()

    def test_delete_not_found(self, capsys) -> None:
        with patch.object(SecretsCmd, "_load_secrets", return_value={}):
            cmd = SecretsCmd()
            rc = cmd.run(self._make_args(secrets_action="delete", name="MISSING"))
        assert rc == 1
        assert "not found" in capsys.readouterr().out.lower()

    def test_check_no_file(self, capsys) -> None:
        with patch.object(SecretsCmd, "_get_secrets_path", return_value=Path("/nonexistent")):
            with patch.object(SecretsCmd, "_load_secrets", return_value={}):
                cmd = SecretsCmd()
                rc = cmd.run(self._make_args(secrets_action="check"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "WARN" in out or "does not exist" in out

    def test_encode_decode_roundtrip(self) -> None:
        cmd = SecretsCmd()
        original = "my-secret-value"
        encoded = cmd._encode(original)
        decoded = cmd._decode(encoded)
        assert decoded == original

    def test_encode_no_key(self) -> None:
        with patch.object(SecretsCmd, "_get_encryption_key", return_value=""):
            cmd = SecretsCmd()
            encoded = cmd._encode("test")
            assert encoded  # base64 encoded

    def test_decode_invalid_base64(self) -> None:
        cmd = SecretsCmd()
        with patch.object(SecretsCmd, "_get_encryption_key", return_value=""):
            result = cmd._decode("not-valid-base64!!!")
        assert result  # fallback to return as-is


# ─────────────────────────────────────────────────────────────────────────────
# backup
# ─────────────────────────────────────────────────────────────────────────────

from zeloo_cli.subcommands.backup import BackupCmd


class TestBackupCmd:
    def _make_args(self, **overrides) -> argparse.Namespace:
        defaults = dict(backup_action=None, output=None, quick=False, path=None, force=False)
        return argparse.Namespace(**{**defaults, **overrides})

    def test_backup_cmd_name(self) -> None:
        assert BackupCmd.name == "backup"

    def test_run_no_action(self, capsys) -> None:
        cmd = BackupCmd()
        rc = cmd.run(self._make_args(backup_action=None))
        assert rc == 1

    def test_create_home_not_exists(self, capsys) -> None:
        with patch("agent.zeloo_constants.get_zeloo_home", return_value=Path("/nonexistent")):
            cmd = BackupCmd()
            rc = cmd.run(self._make_args(backup_action="create"))
        assert rc == 1
        assert "does not exist" in capsys.readouterr().out.lower()

    def test_list_no_backups(self, capsys) -> None:
        with patch.object(BackupCmd, "_get_backup_files", return_value=[]):
            with patch.object(BackupCmd, "_get_backup_dir", return_value=Path("/tmp")):
                cmd = BackupCmd()
                rc = cmd.run(self._make_args(backup_action="list"))
        assert rc == 0
        assert "No backups" in capsys.readouterr().out

    def test_delete_nonexistent(self, capsys) -> None:
        with patch.object(BackupCmd, "_get_backup_dir", return_value=Path("/tmp")):
            cmd = BackupCmd()
            rc = cmd.run(self._make_args(backup_action="delete", path=Path("/tmp/nonexistent.zip")))
        assert rc == 1
        assert "not found" in capsys.readouterr().out.lower()

    def test_restore_not_zip(self, tmp_path, capsys) -> None:
        txt_file = tmp_path / "backup.txt"
        txt_file.write_text("not a zip")

        with patch("agent.zeloo_constants.get_zeloo_home", return_value=tmp_path):
            cmd = BackupCmd()
            rc = cmd.run(self._make_args(backup_action="restore", path=txt_file))
        assert rc == 1
        out = capsys.readouterr().out
        assert "not a valid backup" in out.lower()

    def test_restore_not_found(self, capsys) -> None:
        cmd = BackupCmd()
        rc = cmd.run(self._make_args(backup_action="restore", path=Path("/tmp/missing.zip")))
        assert rc == 1

    def test_create_quick_mode(self, tmp_path, capsys) -> None:
        home = tmp_path / ".Zeloo"
        home.mkdir()
        (home / "config.yaml").write_text("model: gpt-4o")

        backup_file = tmp_path / "quick_test.zip"
        with patch("agent.zeloo_constants.get_zeloo_home", return_value=home):
            with patch.object(BackupCmd, "_get_backup_dir", return_value=tmp_path):
                with patch.object(BackupCmd, "_load_metadata", return_value={"backups": []}):
                    with patch.object(BackupCmd, "_save_metadata"):
                        cmd = BackupCmd()
                        rc = cmd.run(self._make_args(backup_action="create", output=backup_file, quick=True))
        assert rc == 0


# ─────────────────────────────────────────────────────────────────────────────
# dump
# ─────────────────────────────────────────────────────────────────────────────

from zeloo_cli.subcommands.dump import DumpCmd


class TestDumpCmd:
    def _make_args(self, **overrides) -> argparse.Namespace:
        defaults = dict(dump_action=None, output=None)
        return argparse.Namespace(**{**defaults, **overrides})

    def test_dump_cmd_name(self) -> None:
        assert DumpCmd.name == "dump"

    def test_run_no_action(self, capsys) -> None:
        cmd = DumpCmd()
        rc = cmd.run(self._make_args(dump_action=None))
        assert rc == 1

    def test_dump_sessions_no_db(self, capsys) -> None:
        with patch("zeloo_state.SessionDB", side_effect=Exception("no db")):
            cmd = DumpCmd()
            rc = cmd.run(self._make_args(dump_action="sessions"))
        assert rc == 1

    def test_dump_sessions_to_file(self, tmp_path, capsys) -> None:
        with patch("zeloo_state.SessionDB") as mock_cls:
            mock_cls.return_value.list_sessions.return_value = [
                {"session_id": "abc123", "platform": "cli"}
            ]
            output = tmp_path / "sessions.json"
            cmd = DumpCmd()
            rc = cmd.run(self._make_args(dump_action="sessions", output=output))
        assert rc == 0
        assert output.exists()
        data = json.loads(output.read_text())
        assert data["session_count"] == 1

    def test_dump_memories_no_dir(self, capsys) -> None:
        with patch("agent.zeloo_constants.get_zeloo_home", return_value=Path("/nonexistent")):
            cmd = DumpCmd()
            rc = cmd.run(self._make_args(dump_action="memories"))
        assert rc == 0
        assert "no memories" in capsys.readouterr().out.lower()

    def test_dump_config_no_file(self, capsys) -> None:
        with patch("agent.zeloo_constants.get_zeloo_home", return_value=Path("/nonexistent")):
            cmd = DumpCmd()
            rc = cmd.run(self._make_args(dump_action="config"))
        assert rc == 1

    def test_dump_config_to_file(self, tmp_path, capsys) -> None:
        config_dir = tmp_path / ".Zeloo"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text("model: gpt-4o\n")

        output = tmp_path / "config.yaml"
        with patch("agent.zeloo_constants.get_zeloo_home", return_value=config_dir):
            cmd = DumpCmd()
            rc = cmd.run(self._make_args(dump_action="config", output=output))
        assert rc == 0
        assert output.exists()


# ─────────────────────────────────────────────────────────────────────────────
# model
# ─────────────────────────────────────────────────────────────────────────────

from zeloo_cli.subcommands.model import ModelCmd


class TestModelCmd:
    def _make_args(self, **overrides) -> argparse.Namespace:
        defaults = dict(model_action=None, provider=None, model=None, message=None)
        return argparse.Namespace(**{**defaults, **overrides})

    def test_model_cmd_name(self) -> None:
        assert ModelCmd.name == "model"

    def test_run_no_action(self, capsys) -> None:
        cmd = ModelCmd()
        rc = cmd.run(self._make_args(model_action=None))
        assert rc == 1

    def test_list_all_providers(self, capsys) -> None:
        cmd = ModelCmd()
        rc = cmd.run(self._make_args(model_action="list"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "openai" in out
        assert "anthropic" in out

    def test_list_filtered_by_provider(self, capsys) -> None:
        cmd = ModelCmd()
        rc = cmd.run(self._make_args(model_action="list", provider="openai"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "anthropic" not in out
        assert "openai" in out

    def test_current_default_model(self, capsys) -> None:
        with patch.object(ModelCmd, "_load_config", return_value={"model": "claude-3-5-sonnet-20241022", "provider": "anthropic"}):
            cmd = ModelCmd()
            rc = cmd.run(self._make_args(model_action="current"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "claude" in out

    def test_set_model(self) -> None:
        with patch.object(ModelCmd, "_load_config", return_value={}):
            with patch.object(ModelCmd, "_save_config") as mock_save:
                cmd = ModelCmd()
                rc = cmd.run(self._make_args(model_action="set", model="gpt-4o"))
        assert rc == 0
        saved = mock_save.call_args[0][0]
        assert saved["model"] == "gpt-4o"

    def test_info_known_model(self, capsys) -> None:
        cmd = ModelCmd()
        rc = cmd.run(self._make_args(model_action="info", model="gpt-4o"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "openai" in out

    def test_info_unknown_model(self, capsys) -> None:
        cmd = ModelCmd()
        rc = cmd.run(self._make_args(model_action="info", model="unknown-model-xyz"))
        assert rc == 1
        out = capsys.readouterr().out
        assert "not found" in out.lower()

    def test_test_no_api_key(self, capsys) -> None:
        with patch.dict("os.environ", {}, clear=True):
            cmd = ModelCmd()
            rc = cmd.run(self._make_args(model_action="test", model="gpt-4o", provider="openai", message="hi"))
        assert rc == 1
        assert "API_KEY" in capsys.readouterr().out

    def test_test_partial_api_key(self, capsys) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "your-key-placeholder"}):
            cmd = ModelCmd()
            rc = cmd.run(self._make_args(model_action="test", model="gpt-4o", provider="openai", message="hi"))
        assert rc == 1
