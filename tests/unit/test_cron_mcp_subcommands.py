"""Tests for ``zeloo_cli.subcommands.cron`` and ``zeloo_cli.subcommands.mcp``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from zeloo_cli.subcommands.cron import (
    _parse_cron_field,
    build_cron_parser,
    cmd_cron,
    cmd_cron_add,
    cmd_cron_disable,
    cmd_cron_enable,
    cmd_cron_list,
    cmd_cron_remove,
    cmd_cron_run_due,
    cron_matches_now,
)
from zeloo_cli.subcommands.mcp import (
    build_mcp_parser,
    cmd_mcp,
    cmd_mcp_add,
    cmd_mcp_disable,
    cmd_mcp_enable,
    cmd_mcp_list,
    cmd_mcp_remove,
)


# ── helpers ────────────────────────────────────────────────────────


def _cron_args(tmp_path: Path, **overrides):
    defaults = dict(
        cron_action=None,
        name=None,
        schedule=None,
        task=None,
        home=str(tmp_path),
        all=False,
        json=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _mcp_args(tmp_path: Path, **overrides):
    defaults = dict(
        mcp_action=None,
        name=None,
        mcp_command=None,
        command=None,
        args=[],
        home=str(tmp_path),
        verbose=False,
        json=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ── cron: _parse_cron_field ────────────────────────────────────────


class TestCronFieldParser:
    def test_star_expands_full_range(self):
        assert _parse_cron_field("*", 0, 59) == list(range(0, 60))

    def test_single_value(self):
        assert _parse_cron_field("5", 0, 59) == [5]

    def test_comma_list(self):
        assert _parse_cron_field("1,3,5", 0, 59) == [1, 3, 5]

    def test_range(self):
        assert _parse_cron_field("9-12", 0, 23) == [9, 10, 11, 12]

    def test_step(self):
        assert _parse_cron_field("*/15", 0, 59) == [0, 15, 30, 45]


# ── cron: cron_matches_now ────────────────────────────────────────


class TestCronMatchesNow:
    def test_wildcards_match_any(self):
        from datetime import datetime

        now = datetime(2025, 1, 1, 12, 30)
        assert cron_matches_now("* * * * *", now) is True

    def test_specific_match(self):
        from datetime import datetime

        now = datetime(2025, 1, 1, 12, 30)
        assert cron_matches_now("30 12 * * *", now) is True

    def test_minute_mismatch(self):
        from datetime import datetime

        now = datetime(2025, 1, 1, 12, 30)
        assert cron_matches_now("0 12 * * *", now) is False

    def test_invalid_format_returns_false(self):
        assert cron_matches_now("bogus") is False
        assert cron_matches_now("") is False
        assert cron_matches_now("1 2 3") is False


# ── cron: cmd_cron_add ────────────────────────────────────────────


class TestCronAdd:
    def test_adds_task(self, tmp_path: Path, capsys):
        args = _cron_args(
            tmp_path,
            cron_action="add",
            name="backup",
            schedule="0 9 * * *",
            task=["echo", "hello"],
        )
        rc = cmd_cron_add(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Added task" in out

        assert (tmp_path / "cron.json").exists()
        data = json.loads((tmp_path / "cron.json").read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["name"] == "backup"
        assert data[0]["schedule"] == "0 9 * * *"
        assert data[0]["command"] == "echo hello"

    def test_invalid_schedule_returns_1(self, tmp_path: Path):
        args = _cron_args(
            tmp_path,
            cron_action="add",
            name="bad",
            schedule="bogus",
            task=["true"],
        )
        rc = cmd_cron_add(args)
        assert rc == 1

    def test_empty_command_returns_1(self, tmp_path: Path):
        args = _cron_args(
            tmp_path,
            cron_action="add",
            name="bad",
            schedule="0 9 * * *",
            task=[],
        )
        rc = cmd_cron_add(args)
        assert rc == 1

    def test_missing_name_returns_1(self, tmp_path: Path):
        args = _cron_args(
            tmp_path,
            cron_action="add",
            name=None,
            schedule="0 9 * * *",
            task=["true"],
        )
        rc = cmd_cron_add(args)
        assert rc == 1


# ── cron: cmd_cron_list ───────────────────────────────────────────


class TestCronList:
    def test_empty_list(self, tmp_path: Path, capsys):
        args = _cron_args(tmp_path, cron_action="list")
        rc = cmd_cron_list(args)
        assert rc == 0
        assert "No scheduled tasks" in capsys.readouterr().out

    def test_lists_existing(self, tmp_path: Path, capsys):
        (tmp_path / "cron.json").write_text(
            json.dumps([
                {"name": "a", "schedule": "0 9 * * *", "command": "echo a"},
                {"name": "b", "schedule": "*/5 * * * *", "command": "echo b"},
            ]),
            encoding="utf-8",
        )
        args = _cron_args(tmp_path, cron_action="list")
        rc = cmd_cron_list(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "a" in out
        assert "b" in out


# ── cron: cmd_cron_remove ─────────────────────────────────────────


class TestCronRemove:
    def test_removes_existing(self, tmp_path: Path):
        (tmp_path / "cron.json").write_text(
            json.dumps([
                {"name": "a", "schedule": "0 9 * * *", "command": "echo a"},
                {"name": "b", "schedule": "*/5 * * * *", "command": "echo b"},
            ]),
            encoding="utf-8",
        )
        args = _cron_args(tmp_path, cron_action="remove", name="a")
        rc = cmd_cron_remove(args)
        assert rc == 0
        data = json.loads((tmp_path / "cron.json").read_text(encoding="utf-8"))
        names = {t["name"] for t in data}
        assert "a" not in names
        assert "b" in names

    def test_missing_returns_1(self, tmp_path: Path):
        args = _cron_args(tmp_path, cron_action="remove", name="missing")
        rc = cmd_cron_remove(args)
        assert rc == 1


# ── cron: enable / disable ───────────────────────────────────────


class TestCronEnableDisable:
    def test_enable(self, tmp_path: Path):
        (tmp_path / "cron.json").write_text(
            json.dumps([
                {"name": "a", "schedule": "0 9 * * *", "command": "echo a", "enabled": False},
            ]),
            encoding="utf-8",
        )
        args = _cron_args(tmp_path, cron_action="enable", name="a")
        rc = cmd_cron_enable(args)
        assert rc == 0
        data = json.loads((tmp_path / "cron.json").read_text(encoding="utf-8"))
        assert data[0]["enabled"] is True

    def test_disable(self, tmp_path: Path):
        (tmp_path / "cron.json").write_text(
            json.dumps([
                {"name": "a", "schedule": "0 9 * * *", "command": "echo a", "enabled": True},
            ]),
            encoding="utf-8",
        )
        args = _cron_args(tmp_path, cron_action="disable", name="a")
        rc = cmd_cron_disable(args)
        assert rc == 0
        data = json.loads((tmp_path / "cron.json").read_text(encoding="utf-8"))
        assert data[0]["enabled"] is False


# ── cron: run-due ────────────────────────────────────────────────


class TestCronRunDue:
    def test_no_due_returns_0(self, tmp_path: Path, monkeypatch, capsys):
        from datetime import datetime

        (tmp_path / "cron.json").write_text(
            json.dumps([
                {"name": "future", "schedule": "0 0 1 1 *", "command": "echo future"},
            ]),
            encoding="utf-8",
        )
        class FakeNow:
            @staticmethod
            def now():
                return datetime(2025, 6, 15, 12, 0)

        import zeloo_cli.subcommands.cron as cron_mod
        monkeypatch.setattr(cron_mod, "datetime", FakeNow)

        args = _cron_args(tmp_path, cron_action="run-due")
        rc = cmd_cron_run_due(args)
        assert rc == 0


# ── cron: top-level dispatcher ────────────────────────────────────


class TestCronDispatcher:
    def test_unknown_action_returns_1(self, tmp_path: Path):
        args = _cron_args(tmp_path, cron_action="bogus")
        rc = cmd_cron(args)
        assert rc == 1

    def test_dispatch_add(self, tmp_path: Path):
        args = _cron_args(
            tmp_path,
            cron_action="add",
            name="test",
            schedule="* * * * *",
            task=["echo", "x"],
        )
        assert cmd_cron(args) == 0


class TestCronParser:
    def test_build_parser_attaches(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="cmd")
        captured = {}

        def handler(args):
            captured["called"] = args
            return 0

        build_cron_parser(sub, cmd_cron_handler=handler)
        args = parser.parse_args(["cron", "list"])
        assert args.func is handler

    def test_all_subactions_parse(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="cmd")
        build_cron_parser(sub, cmd_cron_handler=lambda a: 0)
        for argv in [
            ["cron", "list"],
            ["cron", "add", "x", "* * * * *", "echo", "x"],
            ["cron", "remove", "x"],
            ["cron", "run", "x"],
            ["cron", "run-due"],
            ["cron", "enable", "x"],
            ["cron", "disable", "x"],
        ]:
            args = parser.parse_args(argv)
            assert args.func is not None


# ── mcp: list ────────────────────────────────────────────────────


class TestMcpList:
    def test_empty(self, tmp_path: Path, capsys):
        args = _mcp_args(tmp_path, mcp_action="list")
        rc = cmd_mcp_list(args)
        assert rc == 0
        assert "No MCP servers" in capsys.readouterr().out

    def test_with_servers(self, tmp_path: Path, capsys):
        (tmp_path / "config.yaml").write_text(
            "mcp_servers:\n  github:\n    command: npx\n    args: [mcp-github]\n    enabled: true\n",
            encoding="utf-8",
        )
        args = _mcp_args(tmp_path, mcp_action="list")
        rc = cmd_mcp_list(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "github" in out

    def test_json_output(self, tmp_path: Path, capsys):
        (tmp_path / "config.yaml").write_text(
            "mcp_servers:\n  github:\n    command: npx\n",
            encoding="utf-8",
        )
        args = _mcp_args(tmp_path, mcp_action="list", json=True)
        rc = cmd_mcp_list(args)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "github" in data


# ── mcp: add ─────────────────────────────────────────────────────


class TestMcpAdd:
    def test_adds_server(self, tmp_path: Path, capsys):
        args = _mcp_args(
            tmp_path,
            mcp_action="add",
            name="github",
            mcp_command="npx",
            args=["mcp-github"],
        )
        rc = cmd_mcp_add(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Added" in out
        assert (tmp_path / "config.yaml").exists()
        data = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        assert "github" in data
        assert "npx" in data

    def test_missing_command_returns_1(self, tmp_path: Path):
        args = _mcp_args(
            tmp_path, mcp_action="add", name="x", mcp_command=None
        )
        rc = cmd_mcp_add(args)
        assert rc == 1

    def test_missing_name_returns_1(self, tmp_path: Path):
        args = _mcp_args(
            tmp_path, mcp_action="add", name=None, mcp_command="npx"
        )
        rc = cmd_mcp_add(args)
        assert rc == 1


# ── mcp: remove / enable / disable ───────────────────────────────


class TestMcpRemove:
    def test_removes(self, tmp_path: Path):
        (tmp_path / "config.yaml").write_text(
            "mcp_servers:\n  github:\n    command: npx\n",
            encoding="utf-8",
        )
        args = _mcp_args(tmp_path, mcp_action="remove", name="github")
        rc = cmd_mcp_remove(args)
        assert rc == 0
        data = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        assert "github" not in data

    def test_missing_returns_1(self, tmp_path: Path):
        args = _mcp_args(tmp_path, mcp_action="remove", name="missing")
        rc = cmd_mcp_remove(args)
        assert rc == 1


class TestMcpEnableDisable:
    def test_enable(self, tmp_path: Path):
        (tmp_path / "config.yaml").write_text(
            "mcp_servers:\n  g:\n    command: npx\n    enabled: false\n",
            encoding="utf-8",
        )
        args = _mcp_args(tmp_path, mcp_action="enable", name="g")
        rc = cmd_mcp_enable(args)
        assert rc == 0
        data = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        assert "enabled: true" in data

    def test_disable(self, tmp_path: Path):
        (tmp_path / "config.yaml").write_text(
            "mcp_servers:\n  g:\n    command: npx\n    enabled: true\n",
            encoding="utf-8",
        )
        args = _mcp_args(tmp_path, mcp_action="disable", name="g")
        rc = cmd_mcp_disable(args)
        assert rc == 0
        data = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        assert "enabled: false" in data


# ── mcp: top-level dispatcher ────────────────────────────────────


class TestMcpDispatcher:
    def test_unknown_action_returns_1(self, tmp_path: Path):
        args = _mcp_args(tmp_path, mcp_action="bogus")
        rc = cmd_mcp(args)
        assert rc == 1

    def test_dispatch_add(self, tmp_path: Path):
        args = _mcp_args(
            tmp_path,
            mcp_action="add",
            name="github",
            mcp_command="npx",
        )
        assert cmd_mcp(args) == 0


class TestMcpParser:
    def test_build_parser_attaches(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="cmd")
        captured = {}

        def handler(args):
            captured["called"] = args
            return 0

        build_mcp_parser(sub, cmd_mcp_handler=handler)
        args = parser.parse_args(["mcp", "list"])
        assert args.func is handler

    def test_all_subactions_parse(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="cmd")
        build_mcp_parser(sub, cmd_mcp_handler=lambda a: 0)
        for argv in [
            ["mcp", "list"],
            ["mcp", "add", "x", "--command", "npx"],
            ["mcp", "remove", "x"],
            ["mcp", "test", "x"],
            ["mcp", "enable", "x"],
            ["mcp", "disable", "x"],
            ["mcp", "serve"],
        ]:
            args = parser.parse_args(argv)
            assert args.func is not None