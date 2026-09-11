"""Unit tests for the background version-check hook in ``cli``.

These exercise the small `_background_version_check` function added to
``cli.py`` so that we don't accidentally regress the env-var / TTY /
timeout / failure-swallowing semantics that make the check safe to
fire-and-forget at startup.
"""
from __future__ import annotations

import io
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from cli import _background_version_check


class TestBackgroundVersionCheck:
    @patch("subprocess.Popen")
    def test_skipped_when_disabled(self, mock_popen, monkeypatch):
        """zeloo_DISABLE_UPDATE_CHECK=1 short-circuits the check."""
        monkeypatch.setenv("zeloo_DISABLE_UPDATE_CHECK", "1")
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        _background_version_check()
        mock_popen.assert_not_called()

    @patch("subprocess.Popen")
    def test_skipped_when_disabled_truthy(self, mock_popen, monkeypatch):
        """'true' is treated the same as '1'."""
        monkeypatch.setenv("zeloo_DISABLE_UPDATE_CHECK", "true")
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        _background_version_check()
        mock_popen.assert_not_called()

    @patch("subprocess.Popen")
    def test_skipped_when_no_tty(self, mock_popen, monkeypatch):
        """Non-tty stdout (CI, piped, cron) skips unless force-flag set."""
        monkeypatch.delenv("zeloo_FORCE_UPDATE_CHECK", raising=False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
        _background_version_check()
        mock_popen.assert_not_called()

    @patch("subprocess.Popen")
    def test_runs_when_interactive(self, mock_popen, monkeypatch):
        """Tty + no disable flag → Popen is invoked."""
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("New version: 0.2.0", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        _background_version_check()
        mock_popen.assert_called_once()

    @patch("subprocess.Popen")
    def test_force_flag_overrides_no_tty(self, mock_popen, monkeypatch):
        """zeloo_FORCE_UPDATE_CHECK=1 runs even when not a tty."""
        monkeypatch.setenv("zeloo_FORCE_UPDATE_CHECK", "1")
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("Already up to date (0.16.0)", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        _background_version_check()
        mock_popen.assert_called_once()

    @patch("subprocess.Popen")
    def test_timeout_handled(self, mock_popen, monkeypatch):
        """A hung subprocess is killed and the exception is swallowed."""
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(
            cmd="python", timeout=30
        )
        mock_popen.return_value = mock_proc

        # Should not raise — timeout is normal background behaviour.
        _background_version_check()
        mock_proc.kill.assert_called()

    @patch("subprocess.Popen", side_effect=Exception("network error"))
    def test_exceptions_swallowed(self, mock_popen, monkeypatch):
        """Popen blowing up never crashes the main program."""
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

        # Should not raise.
        _background_version_check()

    @patch("subprocess.Popen")
    def test_nonzero_return_silent(self, mock_popen, monkeypatch, capsys):
        """Non-zero exit code from the subprocess is treated as a no-op."""
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("some error", "")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        _background_version_check()
        # Nothing should be printed on either stream.
        captured = capsys.readouterr()
        assert "new version" not in captured.err.lower()
        assert "update available" not in captured.err.lower()

    @patch("subprocess.Popen")
    def test_new_version_triggers_notification(self, mock_popen, monkeypatch, capsys):
        """stdout containing 'new version' prints a friendly stderr note."""
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (
            "New version available: 0.17.0 (current: 0.16.0)\n",
            "",
        )
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        _background_version_check()
        captured = capsys.readouterr()
        assert "new version" in captured.err.lower()
        assert "zeloo update" in captured.err.lower()

    @patch("subprocess.Popen")
    def test_popen_failure_swallowed(self, mock_popen, monkeypatch):
        """If Popen() itself raises (e.g. FileNotFoundError), we exit cleanly."""
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        mock_popen.side_effect = OSError("python not found")
        # Should not raise.
        _background_version_check()