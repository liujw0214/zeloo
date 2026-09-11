"""Unit tests for `Zeloo workspace` subcommand."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from zeloo_cli.subcommands.workspace import WorkspaceCmd  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="Zeloo")
    WorkspaceCmd.configure_parser(parser)
    return parser


def _run_args(tmp_path, monkeypatch, *args):
    monkeypatch.setenv("zeloo_HOME", str(tmp_path))
    parser = _parser()
    ns = parser.parse_args(list(args))
    return WorkspaceCmd().run(ns)


def test_create_workspace(tmp_path, monkeypatch):
    """workspace create creates workspace directory and updates index."""
    rc = _run_args(tmp_path, monkeypatch, "create", "alpha")
    assert rc == 0
    ws_path = tmp_path / "workspace-alpha"
    assert ws_path.exists()
    assert (ws_path / "memory").exists()
    assert (ws_path / "skills").exists()


def test_create_duplicate_workspace(tmp_path, monkeypatch):
    """workspace create fails when name already exists."""
    assert _run_args(tmp_path, monkeypatch, "create", "beta") == 0
    rc = _run_args(tmp_path, monkeypatch, "create", "beta")
    assert rc != 0


def test_create_invalid_name(tmp_path, monkeypatch):
    """workspace create rejects names with invalid characters."""
    rc = _run_args(tmp_path, monkeypatch, "create", "bad name!")
    assert rc != 0


def test_list_workspaces_table(tmp_path, monkeypatch, capsys):
    """workspace list shows table with active marker."""
    _run_args(tmp_path, monkeypatch, "create", "gamma")
    _run_args(tmp_path, monkeypatch, "create", "delta")
    rc = _run_args(tmp_path, monkeypatch, "list")
    assert rc == 0
    out = capsys.readouterr().out
    assert "gamma" in out
    assert "delta" in out
    assert "*" in out


def test_list_workspaces_json(tmp_path, monkeypatch, capsys):
    """workspace list --format json emits valid JSON."""
    _run_args(tmp_path, monkeypatch, "create", "json-test")
    capsys.readouterr()  # clear create output
    _run_args(tmp_path, monkeypatch, "list", "--format", "json")
    out = capsys.readouterr().out
    import json
    parsed = json.loads(out)
    assert "workspaces" in parsed


def test_switch_workspace(tmp_path, monkeypatch, capsys):
    """workspace switch updates active workspace in index."""
    _run_args(tmp_path, monkeypatch, "create", "first")
    _run_args(tmp_path, monkeypatch, "create", "second")
    rc = _run_args(tmp_path, monkeypatch, "switch", "second")
    assert rc == 0
    out = capsys.readouterr().out
    assert "Switched" in out


def test_switch_unknown(tmp_path, monkeypatch):
    """workspace switch to unknown name returns non-zero."""
    rc = _run_args(tmp_path, monkeypatch, "switch", "nonexistent")
    assert rc != 0


def test_archive_creates_tar_zst(tmp_path, monkeypatch):
    """workspace archive creates a .tar.gz snapshot."""
    _run_args(tmp_path, monkeypatch, "create", "to-archive")
    rc = _run_args(tmp_path, monkeypatch, "archive", "to-archive")
    assert rc == 0
    archive_dir = tmp_path / "archive"
    assert archive_dir.exists()
    archives = list(archive_dir.glob("ws-to-archive.tar.gz"))
    assert len(archives) == 1


def test_archive_unknown(tmp_path, monkeypatch):
    """workspace archive to unknown name returns non-zero."""
    rc = _run_args(tmp_path, monkeypatch, "archive", "ghost")
    assert rc != 0


def test_restore_dry_run(tmp_path, monkeypatch, capsys):
    """workspace restore --dry-run prints plan without extracting."""
    _run_args(tmp_path, monkeypatch, "create", "restore-source")
    _run_args(tmp_path, monkeypatch, "archive", "restore-source")
    archive = tmp_path / "archive" / "ws-restore-source.tar.gz"
    assert archive.exists()
    rc = _run_args(tmp_path, monkeypatch, "restore", str(archive), "--dry-run")
    assert rc == 0
    out = capsys.readouterr().out
    assert "Would restore" in out


def test_restore_missing_archive(tmp_path, monkeypatch):
    """workspace restore with missing archive returns non-zero."""
    rc = _run_args(tmp_path, monkeypatch, "restore", "nonexistent.tar.gz")
    assert rc != 0


def test_no_action_returns_zero(monkeypatch, capsys):
    """workspace with no action returns 0 (help shown)."""
    monkeypatch.setenv("zeloo_HOME", str(Path(".") / "_tmp_no_action"))
    parser = _parser()
    ns = parser.parse_args([])
    assert WorkspaceCmd().run(ns) == 0


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))