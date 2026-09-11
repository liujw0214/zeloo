"""Unit tests for the git worktree helper module."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from zeloo_cli.worktree_helper import (
    WorktreeInfo,
    cleanup_worktree,
    create_worktree,
    is_in_worktree,
    list_zeloo_worktrees,
    should_enable_worktree,
)


# ---------------------------------------------------------------------------
# should_enable_worktree
# ---------------------------------------------------------------------------


class TestShouldEnableWorktree:
    """Env-var / CLI-flag detection for the --worktree feature."""

    def test_env_var_1(self, monkeypatch):
        monkeypatch.setenv("zeloo_WORKTREE", "1")
        assert should_enable_worktree() is True

    def test_env_var_true(self, monkeypatch):
        monkeypatch.setenv("zeloo_WORKTREE", "true")
        assert should_enable_worktree() is True

    def test_env_var_yes(self, monkeypatch):
        monkeypatch.setenv("zeloo_WORKTREE", "yes")
        assert should_enable_worktree() is True

    def test_env_var_zero_is_false(self, monkeypatch):
        monkeypatch.setenv("zeloo_WORKTREE", "0")
        assert should_enable_worktree() is False

    def test_env_var_empty_is_false(self, monkeypatch):
        monkeypatch.setenv("zeloo_WORKTREE", "")
        assert should_enable_worktree() is False

    def test_env_var_random_is_false(self, monkeypatch):
        monkeypatch.setenv("zeloo_WORKTREE", "maybe")
        assert should_enable_worktree() is False

    def test_args_long_flag(self):
        assert should_enable_worktree(["--worktree"]) is True

    def test_args_short_flag(self):
        assert should_enable_worktree(["-w"]) is True

    def test_args_mixed(self):
        assert should_enable_worktree(["chat", "--worktree", "hi"]) is True

    def test_args_no_flag(self, monkeypatch):
        monkeypatch.delenv("zeloo_WORKTREE", raising=False)
        assert should_enable_worktree(["chat"]) is False

    def test_default(self, monkeypatch):
        monkeypatch.delenv("zeloo_WORKTREE", raising=False)
        assert should_enable_worktree() is False


# ---------------------------------------------------------------------------
# is_in_worktree
# ---------------------------------------------------------------------------


class TestIsInWorktree:
    """Detect whether the cwd is a linked worktree vs. main checkout."""

    @patch("subprocess.run")
    def test_in_main_repo(self, mock_run):
        # Same path returned → not in a worktree.
        mock_run.side_effect = [
            MagicMock(stdout="/path/.git\n", returncode=0),
            MagicMock(stdout="/path/.git\n", returncode=0),
        ]
        assert is_in_worktree() is False

    @patch("subprocess.run")
    def test_in_linked_worktree(self, mock_run):
        # Different git-dir than common-dir → inside a linked worktree.
        mock_run.side_effect = [
            MagicMock(stdout="/path/.git\n", returncode=0),
            MagicMock(stdout="/path/.git/worktrees/abc\n", returncode=0),
        ]
        assert is_in_worktree() is True

    @patch("subprocess.run")
    def test_git_failure_returns_false(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        assert is_in_worktree() is False

    @patch("subprocess.run")
    def test_git_missing_returns_false(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")
        assert is_in_worktree() is False


# ---------------------------------------------------------------------------
# create_worktree
# ---------------------------------------------------------------------------


class TestCreateWorktree:
    """End-to-end behavior of worktree creation (with mocked git)."""

    def test_raises_when_not_git_repo(self, tmp_path):
        # No .git directory under tmp_path.
        with pytest.raises(RuntimeError, match="Not a git repository"):
            create_worktree(tmp_path)

    @patch("zeloo_cli.worktree_helper.subprocess.run")
    def test_creates_with_auto_session_id(self, mock_run, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        wt_root = tmp_path / "wt"
        monkeypatch.setenv("ZELOO_WORKTREE_ROOT", str(wt_root))
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        info = create_worktree(tmp_path)

        assert isinstance(info, WorktreeInfo)
        assert info.session_id  # auto-generated
        assert info.branch_name.startswith("zeloo-")
        assert info.branch_name.startswith(f"zeloo-{info.session_id}-")
        assert info.worktree_path.parent == wt_root

        called_argv = mock_run.call_args[0][0]
        assert called_argv[0] == "git"
        assert "worktree" in called_argv
        assert "add" in called_argv
        assert "-b" in called_argv
        assert called_argv[-2] == info.branch_name

    @patch("zeloo_cli.worktree_helper.subprocess.run")
    def test_creates_with_explicit_session_id(self, mock_run, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        monkeypatch.setenv("ZELOO_WORKTREE_ROOT", str(tmp_path / "wt"))
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        info = create_worktree(tmp_path, session_id="deadbeef")

        assert info.session_id == "deadbeef"
        assert info.branch_name.startswith("zeloo-deadbeef-")
        assert info.worktree_path.name == "deadbeef"

    @patch("zeloo_cli.worktree_helper.subprocess.run")
    def test_propagates_git_error(self, mock_run, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        monkeypatch.setenv("ZELOO_WORKTREE_ROOT", str(tmp_path / "wt"))
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "git", stderr="fatal: bad ref\n",
        )

        with pytest.raises(RuntimeError, match="Failed to create worktree"):
            create_worktree(tmp_path)


# ---------------------------------------------------------------------------
# cleanup_worktree
# ---------------------------------------------------------------------------


class TestCleanupWorktree:
    """Both remove + branch -D should be invoked (and tolerated if missing)."""

    @patch("zeloo_cli.worktree_helper.subprocess.run")
    def test_cleanup_success(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        info = WorktreeInfo(
            worktree_path=tmp_path,
            branch_name="zeloo-abc-123",
            session_id="abc",
            created_at=0.0,
        )
        cleanup_worktree(info, tmp_path)
        assert mock_run.call_count == 2
        first_argv = mock_run.call_args_list[0][0][0]
        second_argv = mock_run.call_args_list[1][0][0]
        # subprocess.run received *args → first positional is a list.
        assert tuple(first_argv[:3]) == ("git", "worktree", "remove")
        assert "--force" in first_argv
        assert tuple(second_argv[:3]) == ("git", "branch", "-D")
        assert "zeloo-abc-123" in second_argv

    @patch("zeloo_cli.worktree_helper.subprocess.run")
    def test_cleanup_tolerates_failure(self, mock_run, tmp_path):
        # First call (worktree remove) fails, second (branch delete) also fails.
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="err")
        info = WorktreeInfo(
            worktree_path=tmp_path,
            branch_name="zeloo-x-y",
            session_id="x",
            created_at=0.0,
        )
        # Should NOT raise — cleanup is best-effort.
        cleanup_worktree(info, tmp_path)
        assert mock_run.call_count == 2


# ---------------------------------------------------------------------------
# list_zeloo_worktrees
# ---------------------------------------------------------------------------


class TestListZelooWorktrees:
    """Porcelain parser + filter that keeps only ``zeloo-*`` branches."""

    @patch("zeloo_cli.worktree_helper.subprocess.run")
    def test_filters_to_zeloo_only(self, mock_run, tmp_path):
        # Construct a realistic --porcelain payload.
        porcelain = (
            "worktree /main\n"
            "HEAD abcdef1234567890\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /wt-a\n"
            "HEAD 1111111111111111\n"
            "branch refs/heads/zeloo-aaa-1700000000\n"
            "\n"
            "worktree /wt-feature\n"
            "HEAD 2222222222222222\n"
            "branch refs/heads/feature/foo\n"
            "\n"
            "worktree /wt-b\n"
            "HEAD 3333333333333333\n"
            "branch refs/heads/zeloo-bbb-1700000099\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=porcelain, stderr="")

        result = list_zeloo_worktrees(tmp_path)

        assert len(result) == 2
        # git porcelain uses the "worktree" key for the path.
        paths = {r["worktree"] for r in result}
        assert paths == {"/wt-a", "/wt-b"}
        # Confirm the non-zeloo branch was excluded.
        assert all(r["branch"].startswith("refs/heads/zeloo-") for r in result)

    @patch("zeloo_cli.worktree_helper.subprocess.run")
    def test_returns_empty_on_git_error(self, mock_run, tmp_path):
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        assert list_zeloo_worktrees(tmp_path) == []

    @patch("zeloo_cli.worktree_helper.subprocess.run")
    def test_returns_empty_on_missing_git(self, mock_run, tmp_path):
        mock_run.side_effect = FileNotFoundError("git not found")
        assert list_zeloo_worktrees(tmp_path) == []

    @patch("zeloo_cli.worktree_helper.subprocess.run")
    def test_empty_porcelain(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        assert list_zeloo_worktrees(tmp_path) == []
