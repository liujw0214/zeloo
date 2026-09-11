"""Tests for the P0 subcommands: status, sync, browser."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import platform
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)


# ─────────────────────────────────────────────────────────────────────────────
# status
# ─────────────────────────────────────────────────────────────────────────────

from zeloo_cli.subcommands.status import StatusCmd


class TestStatusCmd:
    def _make_args(self, **overrides) -> argparse.Namespace:
        defaults = dict(json=False, agent=False, gateway=False, system=False)
        return argparse.Namespace(**{**defaults, **overrides})

    def test_status_cmd_name(self) -> None:
        assert StatusCmd.name == "status"

    def test_status_cmd_help(self) -> None:
        assert "status" in StatusCmd.help.lower()

    def test_full_status_returns_zero(self, capsys) -> None:
        cmd = StatusCmd()
        rc = cmd.run(self._make_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert "System" in out or "Python" in out

    def test_system_status_output(self, capsys) -> None:
        cmd = StatusCmd()
        rc = cmd.run(self._make_args(system=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "Python" in out
        assert "OS" in out
        assert "Zeloo" in out

    def test_system_status_includes_config_dir(self, capsys) -> None:
        cmd = StatusCmd()
        cmd.run(self._make_args(system=True))
        out = capsys.readouterr().out
        assert "Config dir" in out

    def test_gateway_status_stopped(self, capsys) -> None:
        with patch("gateway.status.get_running_pid", return_value=None):
            with patch("gateway.status.read_gateway_state", return_value=None):
                cmd = StatusCmd()
                rc = cmd.run(self._make_args(gateway=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "Gateway" in out
        assert "stopped" in out.lower()

    def test_gateway_status_running(self, capsys) -> None:
        from gateway.status import GatewayState

        state = GatewayState(
            kind="zeloo-gateway",
            status="running",
            pid=12345,
            port=8765,
            version="0.16.0",
            profile="default",
            started_at="2026-09-11T10:00:00",
        )
        with patch("gateway.status.get_running_pid", return_value=12345):
            with patch("gateway.status.read_gateway_state", return_value=state):
                cmd = StatusCmd()
                rc = cmd.run(self._make_args(gateway=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "running" in out.lower()
        assert "12345" in out
        assert "8765" in out

    def test_agent_status_no_sessions(self, capsys) -> None:
        with patch("gateway.status.get_running_pid", return_value=None):
            with patch("gateway.status.read_gateway_state", return_value=None):
                with patch("zeloo_state.SessionDB") as mock_db_cls:
                    mock_db = MagicMock()
                    mock_db.list_sessions.return_value = []
                    mock_db_cls.return_value = mock_db
                    cmd = StatusCmd()
                    rc = cmd.run(self._make_args(agent=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "Agent" in out
        assert "No sessions" in out

    def test_agent_status_with_sessions(self, capsys) -> None:
        with patch("gateway.status.get_running_pid", return_value=None):
            with patch("gateway.status.read_gateway_state", return_value=None):
                with patch("zeloo_state.SessionDB") as mock_db_cls:
                    mock_db = MagicMock()
                    mock_db.list_sessions.return_value = [
                        {
                            "session_id": "abc123_xyz456",
                            "platform": "cli",
                            "created_at": "2026-09-11T03:46:33",
                            "message_count": 5,
                        }
                    ]
                    mock_db_cls.return_value = mock_db
                    cmd = StatusCmd()
                    rc = cmd.run(self._make_args(agent=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "abc123_xyz456" in out
        assert "cli" in out
        assert "5" in out

    def test_status_json_output(self, capsys) -> None:
        import json

        with patch("gateway.status.get_running_pid", return_value=None):
            with patch("gateway.status.read_gateway_state", return_value=None):
                with patch("zeloo_state.SessionDB") as mock_db_cls:
                    mock_db = MagicMock()
                    mock_db.list_sessions.return_value = []
                    mock_db_cls.return_value = mock_db
                    cmd = StatusCmd()
                    rc = cmd.run(self._make_args(json=True))
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "system" in data
        assert "gateway" in data
        assert "agent" in data
        assert "python" in data["system"]

    def test_system_status_format(self, capsys) -> None:
        cmd = StatusCmd()
        cmd.run(self._make_args(system=True))
        out = capsys.readouterr().out
        for key in ["Python", "OS", "Architecture", "Zeloo"]:
            assert key in out, f"{key} missing from system status"

    def test_status_section_separator_present(self, capsys) -> None:
        cmd = StatusCmd()
        cmd.run(self._make_args())
        out = capsys.readouterr().out
        assert "─" in out or "System" in out


# ─────────────────────────────────────────────────────────────────────────────
# sync
# ─────────────────────────────────────────────────────────────────────────────

from zeloo_cli.subcommands.sync import SyncCmd


class TestSyncCmd:
    def _make_args(self, sync_command: str | None = None, **overrides) -> argparse.Namespace:
        defaults = dict(sync_command=sync_command, by="date")
        return argparse.Namespace(**{**defaults, **overrides})

    def test_sync_cmd_name(self) -> None:
        assert SyncCmd.name == "sync"

    def test_sync_cmd_help(self) -> None:
        assert "sync" in SyncCmd.help.lower()

    def test_no_action_shows_help(self, capsys) -> None:
        cmd = SyncCmd()
        rc = cmd.run(self._make_args(sync_command=None))
        assert rc == 1
        out = capsys.readouterr().out
        assert "Usage" in out or "sync" in out

    def test_sync_status_shows_directories(self, capsys) -> None:
        cmd = SyncCmd()
        rc = cmd.run(self._make_args(sync_command="status"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "Memory" in out
        assert "Skills" in out

    def test_sync_status_shows_remote_not_configured(self, capsys) -> None:
        cmd = SyncCmd()
        cmd.run(self._make_args(sync_command="status"))
        out = capsys.readouterr().out
        assert "Remote sync" in out
        assert "not configured" in out

    def test_sync_push_not_configured(self, capsys) -> None:
        cmd = SyncCmd()
        rc = cmd.run(self._make_args(sync_command="push"))
        assert rc == 1
        out = capsys.readouterr().out
        assert "not configured" in out.lower()

    def test_sync_pull_not_configured(self, capsys) -> None:
        cmd = SyncCmd()
        rc = cmd.run(self._make_args(sync_command="pull"))
        assert rc == 1
        assert "not configured" in capsys.readouterr().out.lower()

    def test_sync_now_not_configured(self, capsys) -> None:
        cmd = SyncCmd()
        rc = cmd.run(self._make_args(sync_command="now"))
        assert rc == 1
        assert "not configured" in capsys.readouterr().out.lower()

    def test_sync_stats_returns_zero(self, capsys) -> None:
        cmd = SyncCmd()
        rc = cmd.run(self._make_args(sync_command="stats"))
        assert rc == 0

    def test_sync_stats_with_real_memory_dir(self, tmp_path, capsys) -> None:
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "test.md").write_text("hello")

        with patch.object(SyncCmd, "_memory_dir", return_value=mem_dir):
            with patch.object(SyncCmd, "_skills_dir", return_value=tmp_path / "skills"):
                cmd = SyncCmd()
                rc = cmd.run(self._make_args(sync_command="stats"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "Memory files" in out

    def test_sync_unknown_action_returns_error(self, capsys) -> None:
        cmd = SyncCmd()
        rc = cmd.run(self._make_args(sync_command="foobar"))
        assert rc == 1

    def test_sync_status_with_missing_dirs(self, tmp_path, capsys) -> None:
        nonexistent = tmp_path / "does_not_exist"

        with patch.object(SyncCmd, "_memory_dir", return_value=nonexistent):
            with patch.object(SyncCmd, "_skills_dir", return_value=nonexistent):
                cmd = SyncCmd()
                rc = cmd.run(self._make_args(sync_command="status"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "NO" in out

    def test_human_size_bytes(self) -> None:
        from zeloo_cli.subcommands.sync import SyncCmd

        cmd = SyncCmd()
        assert "0.0 B" in cmd._human_size(0)
        assert "1.0 B" in cmd._human_size(1)
        assert "KB" in cmd._human_size(2048)
        assert "MB" in cmd._human_size(5 * 1024 * 1024)


# ─────────────────────────────────────────────────────────────────────────────
# browser
# ─────────────────────────────────────────────────────────────────────────────

from zeloo_cli.subcommands.browser import BrowserCmd


class TestBrowserCmd:
    def _make_args(self, browser_action: str | None = None, **overrides) -> argparse.Namespace:
        defaults = dict(
            browser_action=browser_action,
            browser=None,
            dry_run=False,
        )
        return argparse.Namespace(**{**defaults, **overrides})

    def test_browser_cmd_name(self) -> None:
        assert BrowserCmd.name == "browser"

    def test_browser_cmd_help(self) -> None:
        assert "browser" in BrowserCmd.help.lower()

    def test_no_action_shows_help(self, capsys) -> None:
        cmd = BrowserCmd()
        rc = cmd.run(self._make_args(browser_action=None))
        assert rc == 1
        out = capsys.readouterr().out
        assert "browser" in out.lower()

    def test_list_browsers_none_found(self, capsys) -> None:
        with patch("shutil.which", return_value=None):
            cmd = BrowserCmd()
            rc = cmd.run(self._make_args(browser_action="list-browsers"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "No browsers" in out or "not found" in out.lower()

    def test_list_browsers_chrome_found(self, capsys) -> None:
        with patch("shutil.which", return_value="/usr/bin/google-chrome"):
            cmd = BrowserCmd()
            rc = cmd.run(self._make_args(browser_action="list-browsers"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "google-chrome" in out

    def test_check_profile_no_browser(self, capsys) -> None:
        with patch("shutil.which", return_value=None):
            cmd = BrowserCmd()
            rc = cmd.run(self._make_args(browser_action="check-profile"))
        assert rc == 1
        out = capsys.readouterr().out
        assert "No Chromium browser" in out

    def test_check_profile_browser_found(self, tmp_path, capsys) -> None:
        profile_dir = tmp_path / "Chrome" / "User Data"
        profile_dir.mkdir(parents=True)

        with patch("shutil.which", return_value="/usr/bin/chrome"):
            with patch.object(BrowserCmd, "_profile_data_dir", return_value=str(profile_dir)):
                cmd = BrowserCmd()
                rc = cmd.run(self._make_args(browser_action="check-profile"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "YES" in out or "exists" in out.lower()

    def test_check_profile_dir_not_exists(self, tmp_path, capsys) -> None:
        nonexistent = tmp_path / "does_not_exist"

        with patch("shutil.which", return_value="/usr/bin/chrome"):
            with patch.object(BrowserCmd, "_profile_data_dir", return_value=str(nonexistent)):
                cmd = BrowserCmd()
                rc = cmd.run(self._make_args(browser_action="check-profile"))
        assert rc == 1
        out = capsys.readouterr().out
        assert "NO" in out or "not exist" in out.lower()

    def test_close_profile_no_browser_found(self) -> None:
        with patch.object(BrowserCmd, "_detect_browser", return_value=None):
            with patch.object(BrowserCmd, "_profile_data_dir", return_value=None):
                cmd = BrowserCmd()
                rc = cmd.run(self._make_args(browser_action="close-profile", browser=None))
        assert rc == 1

    def test_close_profile_dry_run(self, tmp_path, capsys) -> None:
        profile_dir = tmp_path / "Chrome"
        profile_dir.mkdir()

        with patch.object(BrowserCmd, "_profile_data_dir", return_value=str(profile_dir)):
            cmd = BrowserCmd()
            rc = cmd.run(self._make_args(browser_action="close-profile", browser="chrome", dry_run=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "[dry-run]" in out

    def test_close_profile_dir_not_exists(self, tmp_path, capsys) -> None:
        nonexistent = str(tmp_path / "nonexistent")
        with patch.object(BrowserCmd, "_profile_data_dir", return_value=nonexistent):
            cmd = BrowserCmd()
            rc = cmd.run(self._make_args(browser_action="close-profile", browser="chrome"))
        assert rc == 1
        err = capsys.readouterr().err
        assert "does not exist" in err

    def test_close_profile_dispatcher_calls_current_platform_method(self, tmp_path, capsys) -> None:
        import sys

        platform_methods = {
            "win32": "_close_windows",
            "darwin": "_close_macos",
        }
        method_name = platform_methods.get(sys.platform, "_close_linux")
        with patch.object(BrowserCmd, method_name, return_value=0) as mock_close:
            cmd = BrowserCmd()
            rc = cmd.run(self._make_args(browser_action="close-profile", browser="chrome"))
        assert rc == 0
        mock_close.assert_called_once_with("chrome")

    def test_close_windows_returns_zero_on_success(self, tmp_path, capsys) -> None:
        cmd = BrowserCmd()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            rc = cmd._close_windows("chrome")
        assert rc == 0
        mock_run.assert_called()

    def test_close_windows_returns_one_on_failure(self, tmp_path, capsys) -> None:
        cmd = BrowserCmd()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="not found")
            rc = cmd._close_windows("chrome")
        assert rc == 1

    def test_close_macos_returns_zero_on_success(self, tmp_path, capsys) -> None:
        cmd = BrowserCmd()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            rc = cmd._close_macos("chrome")
        assert rc == 0

    def test_close_macos_returns_one_on_failure(self, tmp_path, capsys) -> None:
        cmd = BrowserCmd()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            rc = cmd._close_macos("chrome")
        assert rc == 1

    def test_close_linux_returns_zero_on_success(self, tmp_path, capsys) -> None:
        cmd = BrowserCmd()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            rc = cmd._close_linux("chrome")
        assert rc == 0

    def test_close_linux_returns_one_on_failure(self, tmp_path, capsys) -> None:
        cmd = BrowserCmd()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=2, stderr="error")
            rc = cmd._close_linux("chrome")
        assert rc == 1

    def test_detect_browser_priority(self) -> None:
        with patch("shutil.which", side_effect=lambda x: "/path/to/browser" if x == "msedge" else None):
            cmd = BrowserCmd()
            detected = cmd._detect_browser()
        assert detected == "msedge"

    def test_detect_browser_none(self) -> None:
        with patch("shutil.which", return_value=None):
            cmd = BrowserCmd()
            detected = cmd._detect_browser()
        assert detected is None

    def test_profile_data_dir_windows_chrome(self) -> None:
        with patch("sys.platform", "win32"):
            with patch.dict(os.environ, {"LOCALAPPDATA": "C:\\Users\\Test\\AppData\\Local"}):
                cmd = BrowserCmd()
                path = cmd._profile_data_dir("chrome")
        assert path is not None
        assert "Chrome" in path
        assert "User Data" in path

    def test_profile_data_dir_darwin_chrome(self) -> None:
        with patch("sys.platform", "darwin"):
            with patch("pathlib.Path.home", return_value=Path("/Users/test")):
                cmd = BrowserCmd()
                path = cmd._profile_data_dir("chrome")
        assert path is not None
        assert "Google" in path

    def test_profile_data_dir_linux_chrome(self) -> None:
        with patch("sys.platform", "linux"):
            with patch("pathlib.Path.home", return_value=Path("/home/test")):
                cmd = BrowserCmd()
                path = cmd._profile_data_dir("chrome")
        assert path is not None
        assert ".config" in path

    def test_profile_data_dir_unknown(self) -> None:
        cmd = BrowserCmd()
        path = cmd._profile_data_dir("unknown_browser")
        assert path is None

    def test_human_size(self) -> None:
        from zeloo_cli.subcommands.browser import BrowserCmd

        cmd = BrowserCmd()
        assert "0.0 B" in cmd._human_size(0)
        assert "1.0 KB" in cmd._human_size(1024)
        assert "1.0 MB" in cmd._human_size(1024 * 1024)

    def test_dir_size(self, tmp_path) -> None:
        from zeloo_cli.subcommands.browser import BrowserCmd

        (tmp_path / "file1.txt").write_text("x" * 100)
        (tmp_path / "file2.txt").write_text("y" * 200)

        cmd = BrowserCmd()
        size = cmd._dir_size(tmp_path)
        assert size >= 300
