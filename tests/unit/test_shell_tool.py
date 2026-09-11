"""Tests for tools/shell_tool.py — shell_unsafe security checks."""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from unittest.mock import MagicMock, patch

from tools.shell_tool import shell, shell_unsafe

# ── shell_unsafe rejection tests (no command execution needed) ───────


def test_shell_unsafe_rejects_rm() -> None:
    result = shell_unsafe("rm -rf /tmp/test")
    assert "Error" in result
    assert "destructive" in result.lower()


def test_shell_unsafe_rejects_sudo() -> None:
    result = shell_unsafe("sudo apt install")
    assert "Error" in result


def test_shell_unsafe_rejects_kill() -> None:
    result = shell_unsafe("kill 1234")
    assert "Error" in result


def test_shell_unsafe_rejects_redirect() -> None:
    result = shell_unsafe("echo hello > out.txt")
    assert "Error" in result
    assert "redirection" in result.lower()


def test_shell_unsafe_rejects_background() -> None:
    result = shell_unsafe("sleep 10 &")
    assert "Error" in result


def test_shell_unsafe_rejects_chaining() -> None:
    result = shell_unsafe("ls ; rm -rf /")
    assert "Error" in result


def test_shell_unsafe_rejects_backtick() -> None:
    result = shell_unsafe("echo `whoami`")
    assert "Error" in result


def test_shell_unsafe_rejects_non_whitelisted() -> None:
    result = shell_unsafe("python script.py")
    assert "Error" in result
    assert "whitelist" in result.lower()


def test_shell_unsafe_rejects_empty() -> None:
    result = shell_unsafe("")
    assert "Error" in result
    assert "empty" in result.lower()


def test_shell_unsafe_allows_ls() -> None:
    """ls is whitelisted and should execute (or at least not be rejected)."""
    result = shell_unsafe("ls")
    # Should not be a rejection error
    assert not result.startswith("Error:")


def test_shell_unsafe_allows_echo() -> None:
    result = shell_unsafe("echo hello")
    assert "hello" in result


def test_shell_unsafe_allows_prefixed_path() -> None:
    """/usr/bin/echo should be stripped to echo and pass the whitelist check."""
    mock_backend = MagicMock()
    mock_backend.execute.return_value = MagicMock(
        stdout="test", stderr="", returncode=0
    )
    with patch("tools.shell_tool._get_backend", return_value=mock_backend):
        result = shell_unsafe("/usr/bin/echo test")
    assert "test" in result
    # Verify the backend received the original command (path stripping is
    # only for the whitelist check, not the execution).
    mock_backend.execute.assert_called_once()


def test_shell_unsafe_rejects_pipe_to_destructive() -> None:
    """ls | rm is rejected because rm matches dangerous patterns."""
    result = shell_unsafe("ls | rm")
    assert "Error" in result


def test_shell_unsafe_timeout_capped() -> None:
    """timeout > 30 is capped to 30."""
    # Just verify it doesn't error out on the timeout cap
    result = shell_unsafe("echo test", timeout=100)
    assert "test" in result


# ── shell tool basic execution ───────────────────────────────────────


def test_shell_executes_echo() -> None:
    result = shell("echo hello world")
    assert "hello world" in result


def test_shell_returns_exit_code_on_failure() -> None:
    result = shell("exit 1")
    assert "exit code" in result


if __name__ == "__main__":
    test_shell_unsafe_rejects_rm()
    test_shell_unsafe_rejects_sudo()
    test_shell_unsafe_rejects_kill()
    test_shell_unsafe_rejects_redirect()
    test_shell_unsafe_rejects_background()
    test_shell_unsafe_rejects_chaining()
    test_shell_unsafe_rejects_backtick()
    test_shell_unsafe_rejects_non_whitelisted()
    test_shell_unsafe_rejects_empty()
    test_shell_unsafe_allows_ls()
    test_shell_unsafe_allows_echo()
    test_shell_unsafe_allows_prefixed_path()
    test_shell_unsafe_rejects_pipe_to_destructive()
    test_shell_unsafe_timeout_capped()
    test_shell_executes_echo()
    test_shell_returns_exit_code_on_failure()
    print("All shell_tool tests passed!")
