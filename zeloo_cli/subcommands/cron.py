"""``zeloo cron`` subcommand — Hermes-style scheduled task management.

Supports the Hermes-style sub-actions:
* ``cron list`` — show all scheduled tasks
* ``cron add <name> <schedule> <command...>`` — create a task
* ``cron remove <name>`` — delete a task
* ``cron run <name>`` — execute a task immediately (for testing)
* ``cron enable <name>`` / ``cron disable <name>`` — toggle
* ``cron run-due`` — run any tasks whose schedule matches now

Schedule format: standard 5-field cron (e.g. "0 9 * * *").
Storage: ``~/.zeloo/cron.json`` via :class:`zeloo_cli.cron_store.CronStore`.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from zeloo_cli.cron_store import CronStore

logger = logging.getLogger(__name__)


def _get_store(home: Path | str | None = None) -> CronStore:
    if home is None:
        return CronStore()
    if isinstance(home, str):
        home = Path(home)
    return CronStore(path=home / "cron.json")


def _parse_cron_field(field: str, min_val: int, max_val: int) -> list[int]:
    """Expand a single cron field into a sorted list of allowed values.

    Supports ``*``, ``5``, ``1,3,5``, and ``*/n``.
    """
    if field == "*":
        return list(range(min_val, max_val + 1))
    if field.startswith("*/"):
        step = int(field[2:])
        return list(range(min_val, max_val + 1, step))
    values = []
    for part in field.split(","):
        if "-" in part:
            start_s, end_s = part.split("-")
            values.extend(range(int(start_s), int(end_s) + 1))
        else:
            values.append(int(part))
    return sorted(set(values))


def cron_matches_now(schedule: str, now: datetime | None = None) -> bool:
    """Return True if a 5-field cron expression matches ``now``.

    All five fields must match. Day-of-week uses 0=Monday to match Python's
    ``weekday()``.
    """
    if not schedule or not schedule.strip():
        return False
    parts = schedule.strip().split()
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    if now is None:
        now = datetime.now()

    minutes = _parse_cron_field(minute, 0, 59)
    hours = _parse_cron_field(hour, 0, 23)
    doms = _parse_cron_field(dom, 1, 31)
    months = _parse_cron_field(month, 1, 12)
    dows = _parse_cron_field(dow, 0, 6)

    if "*" in dom and "*" in dow:
        pass
    elif "*" in dom:
        if now.weekday() not in dows:
            return False
    elif "*" in dow:
        if now.day not in doms:
            return False
    else:
        if now.day not in doms and now.weekday() not in dows:
            return False

    return (
        now.minute in minutes
        and now.hour in hours
        and now.month in months
    )


def cmd_cron_list(args: argparse.Namespace) -> int:
    """``zeloo cron list`` — print all tasks."""
    store = _get_store(home=getattr(args, "home", None))
    tasks = store.list_tasks()
    if not tasks:
        print("No scheduled tasks.")
        return 0
    print(f"{'NAME':<24} {'SCHEDULE':<16} COMMAND")
    print("-" * 72)
    for t in tasks:
        print(f"{t['name']:<24} {t['schedule']:<16} {t['command']}")
    return 0


def cmd_cron_add(args: argparse.Namespace) -> int:
    """``zeloo cron add <name> <schedule> <command...>``."""
    name = getattr(args, "name", None)
    schedule = getattr(args, "schedule", None)
    task = getattr(args, "task", None) or []

    if not name or not schedule:
        print("Usage: zeloo cron add <name> <schedule> <command...>")
        return 1

    parts = schedule.split()
    if len(parts) != 5:
        print(
            f"Invalid cron expression: {schedule!r}\n"
            "Expected 5 fields (minute hour day-of-month month day-of-week), "
            "e.g. '0 9 * * *'"
        )
        return 1

    command = " ".join(task)
    if not command.strip():
        print("Command cannot be empty.")
        return 1

    store = _get_store(home=getattr(args, "home", None))
    store.add_task(name=name, schedule=schedule, command=command)
    print(f"Added task {name!r} ({schedule}): {command}")
    return 0


def cmd_cron_remove(args: argparse.Namespace) -> int:
    """``zeloo cron remove <name>``."""
    name = getattr(args, "name", None)
    if not name:
        print("Usage: zeloo cron remove <name>")
        return 1
    store = _get_store(home=getattr(args, "home", None))
    tasks = store.list_tasks()
    target = next((t for t in tasks if t["name"] == name), None)
    if target is None:
        print(f"Task {name!r} not found.")
        return 1
    store.remove_task(name)
    print(f"Removed task {name!r}.")
    return 0


def cmd_cron_run(args: argparse.Namespace) -> int:
    """``zeloo cron run <name>`` — execute a single task immediately."""
    name = getattr(args, "name", None)
    if not name:
        print("Usage: zeloo cron run <name>")
        return 1
    store = _get_store(home=getattr(args, "home", None))
    target = next((t for t in store.list_tasks() if t["name"] == name), None)
    if target is None:
        print(f"Task {name!r} not found.")
        return 1
    print(f"Running task {name!r}: {target['command']}")
    return _execute_command(target["command"])


def cmd_cron_run_due(args: argparse.Namespace) -> int:
    """``zeloo cron run-due`` — run all tasks matching the current time."""
    store = _get_store(home=getattr(args, "home", None))
    now = datetime.now()
    due = [t for t in store.list_tasks() if cron_matches_now(t["schedule"], now)]
    if not due:
        print(f"No tasks due at {now.strftime('%H:%M')}.")
        return 0
    print(f"Running {len(due)} due task(s) at {now.isoformat()}:")
    rc = 0
    for t in due:
        print(f"  - {t['name']}: {t['command']}")
        rc = max(rc, _execute_command(t["command"]))
    return rc


def cmd_cron_enable(args: argparse.Namespace) -> int:
    """``zeloo cron enable <name>`` — set enabled=true."""
    name = getattr(args, "name", None)
    if not name:
        print("Usage: zeloo cron enable <name>")
        return 1
    store = _get_store(home=getattr(args, "home", None))
    target = next((t for t in store.list_tasks() if t["name"] == name), None)
    if target is None:
        print(f"Task {name!r} not found.")
        return 1
    target["enabled"] = True
    _persist_task(store, target)
    print(f"Enabled task {name!r}.")
    return 0


def cmd_cron_disable(args: argparse.Namespace) -> int:
    """``zeloo cron disable <name>`` — set enabled=false."""
    name = getattr(args, "name", None)
    if not name:
        print("Usage: zeloo cron disable <name>")
        return 1
    store = _get_store(home=getattr(args, "home", None))
    target = next((t for t in store.list_tasks() if t["name"] == name), None)
    if target is None:
        print(f"Task {name!r} not found.")
        return 1
    target["enabled"] = False
    _persist_task(store, target)
    print(f"Disabled task {name!r}.")
    return 0


def _persist_task(store: CronStore, task: dict) -> None:
    """Re-add a task dict to the store, preserving extra fields like 'enabled'."""
    store._tasks[task["name"]] = dict(task)
    if hasattr(store, "_flush"):
        store._flush()


def cmd_cron(args: argparse.Namespace) -> int:
    """Top-level dispatcher for ``zeloo cron``."""
    action = getattr(args, "cron_action", None)
    if action is None:
        return cmd_cron_list(args)
    handler = {
        "list": cmd_cron_list,
        "add": cmd_cron_add,
        "create": cmd_cron_add,
        "remove": cmd_cron_remove,
        "rm": cmd_cron_remove,
        "run": cmd_cron_run,
        "run-due": cmd_cron_run_due,
        "enable": cmd_cron_enable,
        "disable": cmd_cron_disable,
    }.get(action)
    if handler is None:
        print(f"Unknown cron action: {action}")
        return 1
    return handler(args)


def _execute_command(command: str) -> int:
    """Execute a shell command and stream its output.

    Returns the process return code.

    Security: parses the command via shlex so user-controlled cron tasks
    cannot inject additional shell tokens. Callers that need full shell
    semantics (pipes, redirects, globs) should pass the command through
    ``shell=True`` explicitly via the cron entry's ``shell`` flag.
    """
    import shlex

    # Allow opt-in to shell mode via leading "shell:" prefix for backward
    # compatibility with cron entries that previously relied on shell=True.
    use_shell = False
    cmd_str = command
    if isinstance(command, str) and command.startswith("shell:"):
        use_shell = True
        cmd_str = command[len("shell:"):]
        if not cmd_str:
            print("Empty shell command")
            return 1

    try:
        if use_shell:
            argv = cmd_str
        else:
            try:
                argv = shlex.split(cmd_str)
            except ValueError as exc:
                print(f"Invalid command syntax: {exc}")
                return 2
            if not argv:
                print("Empty command after parsing")
                return 2

        result = subprocess.run(
            argv,
            shell=use_shell,
            capture_output=False,
            text=True,
            timeout=300,
        )
        return result.returncode
    except subprocess.TimeoutExpired:
        print(f"Task timed out after 300s: {command}")
        return 124
    except FileNotFoundError as exc:
        print(f"Command not found: {exc}")
        return 127
    except Exception as exc:
        print(f"Task failed: {exc}")
        return 1


def build_cron_parser(subparsers: Any, *, cmd_cron_handler: Any) -> None:
    """Attach the Hermes-style ``cron`` subparser."""
    cron_parser = subparsers.add_parser(
        "cron", help="Cron job management", description="Manage scheduled tasks"
    )
    cron_subparsers = cron_parser.add_subparsers(dest="cron_action")

    # cron list
    cron_list = cron_subparsers.add_parser("list", help="List scheduled jobs")
    cron_list.add_argument("--all", action="store_true", help="Include disabled jobs")
    cron_list.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )

    # cron add / create
    cron_add = cron_subparsers.add_parser(
        "add", aliases=["create"], help="Create a scheduled job"
    )
    cron_add.add_argument("name", help="Task name (unique)")
    cron_add.add_argument(
        "schedule",
        help="5-field cron expression (e.g. '0 9 * * *' for 9am daily)",
    )
    cron_add.add_argument(
        "task",
        nargs="+",
        help="Command to execute (multi-word)",
    )

    # cron remove / rm
    cron_rm = cron_subparsers.add_parser(
        "remove", aliases=["rm"], help="Remove a scheduled job"
    )
    cron_rm.add_argument("name", help="Task name")

    # cron run
    cron_run = cron_subparsers.add_parser(
        "run", help="Run a scheduled job immediately (for testing)"
    )
    cron_run.add_argument("name", help="Task name")

    # cron run-due
    cron_subparsers.add_parser(
        "run-due", help="Run all jobs that match the current time"
    )

    # cron enable / disable
    cron_enable = cron_subparsers.add_parser("enable", help="Enable a task")
    cron_enable.add_argument("name", help="Task name")
    cron_disable = cron_subparsers.add_parser("disable", help="Disable a task")
    cron_disable.add_argument("name", help="Task name")

    cron_parser.set_defaults(func=cmd_cron_handler)