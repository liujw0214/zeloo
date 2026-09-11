"""Tests for Round 66 — Hermes Agent v0.16.0 feature parity.

Covers the new top-level flags (``--tui``, ``--resume``, ``--continue``,
``--yolo``, ``--checkpoints``, ``--pass-session-id``,
``--ignore-user-config``, ``--ignore-rules``, ``--quiet``,
``--worktree``, ``--in``, ``--version``) and the new subcommands
(``version``, ``plugins``, ``cron``).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Top-level flag parsing
# ---------------------------------------------------------------------------


def _parse(argv: list[str]) -> argparse.Namespace:
    """Parse argv via :func:`cli.parse_args`."""
    from cli import parse_args

    # ``parse_args`` reads sys.argv, so swap it for the duration of
    # the call. We can't use monkeypatch here because the helper is
    # also called by other tests.
    import sys

    saved = sys.argv
    try:
        sys.argv = ["zeloo", *argv]
        return parse_args()
    finally:
        sys.argv = saved


class TestGlobalFlags:
    """Hermes Agent global flag parity."""

    def test_version_flag_parsed(self) -> None:
        args = _parse(["--version"])
        assert args.version is True

    def test_tui_flag_parsed(self) -> None:
        args = _parse(["--tui"])
        assert args.tui is True

    def test_cli_force_flag_parsed(self) -> None:
        args = _parse(["--cli"])
        assert args.force_cli is True

    def test_resume_flag_parsed(self) -> None:
        args = _parse(["--resume", "abc123"])
        assert args.resume == "abc123"

    def test_continue_flag_with_value(self) -> None:
        args = _parse(["--continue", "mysession"])
        # argparse maps ``--continue`` → ``args.continue_`` (the
        # trailing underscore avoids the Python keyword).
        assert getattr(args, "continue_", None) == "mysession"

    def test_continue_flag_without_value_defaults_to_latest(self) -> None:
        args = _parse(["--continue"])
        assert getattr(args, "continue_", None) == "latest"

    def test_in_dir_flag_parsed(self) -> None:
        args = _parse(["--in", "/tmp/work"])
        assert args.in_dir == "/tmp/work"

    def test_worktree_flag_parsed(self) -> None:
        args = _parse(["--worktree"])
        assert args.worktree is True

    def test_yolo_flag_parsed(self) -> None:
        args = _parse(["--yolo"])
        assert args.yolo is True

    def test_checkpoints_flag_parsed(self) -> None:
        args = _parse(["--checkpoints"])
        assert args.checkpoints is True

    def test_pass_session_id_flag_parsed(self) -> None:
        args = _parse(["--pass-session-id"])
        assert args.pass_session_id is True

    def test_ignore_user_config_flag_parsed(self) -> None:
        args = _parse(["--ignore-user-config"])
        assert args.ignore_user_config is True

    def test_ignore_rules_flag_parsed(self) -> None:
        args = _parse(["--ignore-rules"])
        assert args.ignore_rules is True

    def test_quiet_flag_short_alias(self) -> None:
        args = _parse(["-Q"])
        assert args.quiet is True

    def test_quiet_flag_long_alias(self) -> None:
        args = _parse(["--quiet"])
        assert args.quiet is True

    def test_multiple_global_flags_combine(self) -> None:
        args = _parse(["--yolo", "--quiet", "--checkpoints", "status"])
        assert args.yolo is True
        assert args.quiet is True
        assert args.checkpoints is True
        assert args.command == "status"


# ---------------------------------------------------------------------------
# Chat subcommand extensions
# ---------------------------------------------------------------------------


class TestChatSubcommandFlags:
    """Hermes Agent ``hermes chat`` parity."""

    def test_query_flag_parsed(self) -> None:
        args = _parse(["chat", "-q", "hello world"])
        assert args.query == "hello world"

    def test_query_long_flag_parsed(self) -> None:
        args = _parse(["chat", "--query", "hi"])
        assert args.query == "hi"

    def test_query_file_flag_parsed(self) -> None:
        args = _parse(["chat", "--query-file", "prompt.txt"])
        assert args.query_file == "prompt.txt"

    def test_resume_flag_on_chat_parsed(self) -> None:
        args = _parse(["chat", "--resume", "sess_42"])
        assert args.resume == "sess_42"

    def test_continue_short_alias(self) -> None:
        args = _parse(["chat", "-c", "name"])
        assert getattr(args, "continue_", None) == "name"


# ---------------------------------------------------------------------------
# Helpers in cli.py
# ---------------------------------------------------------------------------


class TestApplyGlobalFlags:
    """``_apply_global_flags`` translates flags to env vars."""

    def setup_method(self) -> None:
        # Snapshot env so each test can clean up after itself.
        self._env_keys = (
            "zeloo_YOLO", "zeloo_QUIET", "zeloo_CHECKPOINTS",
            "zeloo_IGNORE_USER_CONFIG", "zeloo_IGNORE_RULES",
            "zeloo_WORKTREE", "zeloo_PASS_SESSION_ID",
        )
        self._saved = {k: os.environ.get(k) for k in self._env_keys}

    def teardown_method(self) -> None:
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_yolo_sets_env(self) -> None:
        from cli import _apply_global_flags

        args = argparse.Namespace(
            yolo=True, quiet=False, checkpoints=False,
            ignore_user_config=False, ignore_rules=False,
            worktree=False, pass_session_id=False, in_dir=None,
            command="chat", resume=None, _continue_global=None,
        )
        _apply_global_flags(args)
        assert os.environ.get("zeloo_YOLO") == "1"

    def test_all_flags_combine(self) -> None:
        from cli import _apply_global_flags

        args = argparse.Namespace(
            yolo=True, quiet=True, checkpoints=True,
            ignore_user_config=True, ignore_rules=True,
            worktree=True, pass_session_id=True, in_dir=None,
            command="status", resume=None, _continue_global=None,
        )
        _apply_global_flags(args)
        for key in self._env_keys:
            assert os.environ.get(key) == "1"


class TestResolveResumeTarget:
    """``_resolve_resume_target`` honours Hermes precedence."""

    def test_returns_none_when_no_candidate(self) -> None:
        from cli import _resolve_resume_target

        args = argparse.Namespace(
            resume=None, continue_=None, _continue_global=None,
        )
        assert _resolve_resume_target(args) is None

    def test_uses_resume_value(self) -> None:
        from cli import _resolve_resume_target

        args = argparse.Namespace(
            resume="abc123", continue_=None, _continue_global=None,
        )
        assert _resolve_resume_target(args) == "abc123"

    def test_latest_keyword_returns_most_recent(self) -> None:
        from cli import _resolve_resume_target

        args = argparse.Namespace(
            resume="latest", continue_=None, _continue_global=None,
        )
        result = _resolve_resume_target(args)
        # ``latest`` should resolve to either a session ID or None
        # (when no sessions exist); both are acceptable outcomes.
        assert result is None or isinstance(result, str)


class TestReadQueryText:
    """``_read_query_text`` reads verbatim from --query / --query-file."""

    def test_query_takes_precedence(self) -> None:
        from cli import _read_query_text

        args = argparse.Namespace(query="from --query", query_file="missing.txt")
        assert _read_query_text(args) == "from --query"

    def test_query_file_reads_from_disk(self, tmp_path: Path) -> None:
        from cli import _read_query_text

        prompt = tmp_path / "prompt.txt"
        prompt.write_text("hello $(echo world)", encoding="utf-8")
        args = argparse.Namespace(query=None, query_file=str(prompt))
        assert _read_query_text(args) == "hello $(echo world)"

    def test_query_file_dash_reads_stdin(self, monkeypatch) -> None:
        from cli import _read_query_text
        import sys

        monkeypatch.setattr(sys, "stdin", type("S", (), {"read": staticmethod(lambda: "from stdin")})())
        args = argparse.Namespace(query=None, query_file="-")
        assert _read_query_text(args) == "from stdin"

    def test_returns_none_when_neither_set(self) -> None:
        from cli import _read_query_text

        args = argparse.Namespace(query=None, query_file=None)
        assert _read_query_text(args) is None


# ---------------------------------------------------------------------------
# New subcommands
# ---------------------------------------------------------------------------


class TestVersionSubcommand:
    """``zeloo version`` and ``zeloo --version`` parity."""

    def test_version_subcommand_help(self) -> None:
        args = _parse(["version"])
        assert args.command == "version"

    def test_version_function_prints_release_codename(self, capsys) -> None:
        from cli import _cmd_version

        rc = _cmd_version()
        captured = capsys.readouterr()
        assert rc == 0
        assert "0.16.0" in captured.out
        assert "Surface Release" in captured.out


class TestCronStore:
    """In-memory cron store basic contract."""

    def test_add_then_list(self, tmp_path: Path) -> None:
        from zeloo_cli.cron_store import CronStore

        store = CronStore(path=tmp_path / "cron.json")
        store.add_task("nightly", "0 3 * * *", "zeloo backup")
        tasks = store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["name"] == "nightly"
        assert tasks[0]["schedule"] == "0 3 * * *"
        assert tasks[0]["command"] == "zeloo backup"

    def test_persistence_round_trip(self, tmp_path: Path) -> None:
        from zeloo_cli.cron_store import CronStore

        path = tmp_path / "cron.json"
        s1 = CronStore(path=path)
        s1.add_task("hourly", "0 * * * *", "echo hi")

        # Read back via a fresh store instance.
        s2 = CronStore(path=path)
        names = [t["name"] for t in s2.list_tasks()]
        assert names == ["hourly"]

    def test_remove_task(self, tmp_path: Path) -> None:
        from zeloo_cli.cron_store import CronStore

        store = CronStore(path=tmp_path / "cron.json")
        store.add_task("a", "* * * * *", "echo a")
        store.add_task("b", "* * * * *", "echo b")
        store.remove_task("a")
        names = [t["name"] for t in store.list_tasks()]
        assert names == ["b"]


class TestPluginsSubcommand:
    """``zeloo plugins list`` returns the registered plugins."""

    def test_plugins_list_runs(self, capsys) -> None:
        from cli import _cmd_plugins

        args = argparse.Namespace(plugins_action="list", name=None, no_enable=False)
        rc = _cmd_plugins(args)
        assert rc in (0, 1)  # 0 if any plugins are loaded, 1 only if manager fails
        # Either prints "(no plugins found)" OR a Rich table — both
        # are acceptable.
        out = capsys.readouterr().out
        assert out  # some output must have been emitted

    def test_plugins_help(self) -> None:
        with pytest.raises(SystemExit):
            # ``--help`` causes argparse to call ``sys.exit(0)`` after
            # printing the usage. Wrap to confirm the subparser is
            # wired up correctly.
            _parse(["plugins", "--help"])


class TestCronSubcommand:
    """``zeloo cron`` exercises the parser & dispatch."""

    def test_cron_list_parser(self) -> None:
        args = _parse(["cron", "list"])
        assert args.command == "cron"
        assert args.cron_action == "list"

    def test_cron_remove_parser(self) -> None:
        args = _parse(["cron", "remove", "old-task"])
        assert args.cron_action == "remove"
        assert args.name == "old-task"


# ---------------------------------------------------------------------------
# Round 66 about + status parity
# ---------------------------------------------------------------------------


class TestAboutModule:
    """``zeloo_cli.__about__`` exposes the version metadata."""

    def test_version_constant_is_string(self) -> None:
        from zeloo_cli.__about__ import __version__

        assert isinstance(__version__, str)
        assert len(__version__.split(".")) == 3

    def test_codename_is_set(self) -> None:
        from zeloo_cli.__about__ import __codename__

        assert isinstance(__codename__, str)
        assert __codename__


class TestStatusJson:
    """``zeloo status --json`` returns machine-readable snapshot."""

    def test_status_json_contains_expected_keys(self) -> None:
        from cli import _cmd_status

        args = argparse.Namespace(as_json=True, watch=False)
        # Call into the snapshot function directly so we don't depend
        # on whether the test runner has a TTY.
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = _cmd_status(args)
        assert rc is None  # returns early
        payload = json.loads(buf.getvalue())
        for key in ("provider", "model", "profile", "platform_flags", "timestamp"):
            assert key in payload


class TestUndoSlashCommand:
    """``/undo`` is wired into the interactive handler."""

    def test_undo_pops_history(self) -> None:
        # Build a fake agent with a 4-message history.
        class _FakeAgent:
            _turn_count = 1
            _history = [
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
                {"role": "assistant", "content": "a2"},
            ]

        from cli import _undo_last_turn

        agent = _FakeAgent()
        before = len(agent._history)
        _undo_last_turn(agent)
        after = len(agent._history)
        # Should have removed at least the last assistant message.
        assert after < before
        # The remaining history ends with a synthetic [undone] marker.
        assert agent._history[-1]["role"] == "system"
        assert "[undone]" in agent._history[-1]["content"]

    def test_undo_handles_empty_history(self, capsys) -> None:
        class _FakeAgent:
            _turn_count = 0
            _history = []

        from cli import _undo_last_turn

        _undo_last_turn(_FakeAgent())
        captured = capsys.readouterr()
        assert "Nothing to undo" in captured.out
