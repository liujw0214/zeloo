"""Zeloo worktree subcommand — Git worktree lifecycle management.

Wraps ``git worktree`` with five actions: ``list``, ``add``,
``remove``, ``prune`` and ``status``. All git calls go through
``subprocess`` and never raise — failures bubble back as ``return 1``.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
from pathlib import Path
from typing import Any

from zeloo_cli.rich_render import make_console, make_table
from zeloo_cli.subcommands import Subcommand, subcommand

logger = logging.getLogger(__name__)


@subcommand("worktree")
class WorktreeCommand(Subcommand):
    """Subcommand entry point for Git worktree management."""

    name = "worktree"
    help = "Manage git worktrees (list/add/remove/prune/status)"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Attach the five worktree sub-actions to *parser*."""
        sub = parser.add_subparsers(dest="worktree_action", help="Worktree action")

        sub.add_parser("list", help="List existing worktrees")

        add_p = sub.add_parser("add", help="Create a new worktree")
        add_p.add_argument("branch", help="Branch name (created if missing)")
        add_p.add_argument("--path", default=None, help="Filesystem path for new worktree")
        add_p.add_argument(
            "--create-branch", action="store_true",
            help="Create the branch if it does not exist yet",
        )

        rm_p = sub.add_parser("remove", help="Remove an existing worktree")
        rm_p.add_argument("path", help="Path of the worktree to remove")
        rm_p.add_argument("--force", action="store_true", help="Force removal")

        sub.add_parser("prune", help="Prune stale worktree metadata")
        sub.add_parser("status", help="Show the current worktree status")

    def run(self, args: argparse.Namespace) -> int:
        """Dispatch to the action-specific handler."""
        action = getattr(args, "worktree_action", None)
        if action == "list":
            return self._list()
        if action == "add":
            return self._add(
                args.branch,
                path=getattr(args, "path", None),
                create_branch=getattr(args, "create_branch", False),
            )
        if action == "remove":
            return self._remove(args.path, force=getattr(args, "force", False))
        if action == "prune":
            return self._prune()
        if action == "status":
            return self._status()
        console = make_console()
        console.print(
            "[yellow]Usage:[/yellow] Zeloo worktree "
            "[list|add <branch>|remove <path>|status]"
        )
        return 1

    # ----- action handlers ---------------------------------------------

    def _list(self) -> int:
        """Render every worktree as a rich table."""
        rc, out = self._git("worktree", "list", "--porcelain")
        console = make_console()
        if rc != 0:
            console.print(f"[red]Error:[/red] {out.strip() or 'git worktree list failed'}")
            return 1
        entries = _parse_porcelain(out)
        if not entries:
            console.print("[yellow]No worktrees registered.[/yellow]")
            return 0
        table = make_table(
            title=f"Git Worktrees ({len(entries)})",
            columns=[("Path", "bold cyan"), ("Commit", "white"), ("Branch", "green")],
        )
        for entry in entries:
            table.add_row(
                entry["path"],
                entry["commit"][:8] if entry["commit"] else "—",
                entry["branch"] or "(detached)",
            )
        console.print(table)
        return 0

    def _add(self, branch: str, *, path: str | None, create_branch: bool) -> int:
        """Create a new worktree on *branch*."""
        argv: list[str] = ["worktree", "add"]
        if path:
            argv.append(path)
        argv.append(branch)
        if create_branch and not self._branch_exists(branch):
            argv.insert(2, "-b")
        rc, out = self._git(*argv)
        console = make_console()
        if rc != 0:
            console.print(f"[red]Error:[/red] {out.strip() or 'git worktree add failed'}")
            return 1
        console.print(
            f"[green]✓[/green] Added worktree '[bold]{branch}[/bold]' "
            f"at [bold]{path or '(default path)'}[/bold]"
        )
        return 0

    def _remove(self, path: str, *, force: bool) -> int:
        """Remove the worktree at *path*."""
        argv: list[str] = ["worktree", "remove"]
        if force:
            argv.append("--force")
        argv.append(path)
        rc, out = self._git(*argv)
        console = make_console()
        if rc != 0:
            console.print(f"[red]Error:[/red] {out.strip() or 'git worktree remove failed'}")
            return 1
        console.print(f"[green]✓[/green] Removed worktree at '[bold]{path}[/bold]'")
        return 0

    def _prune(self) -> int:
        """Remove stale worktree metadata."""
        rc, out = self._git("worktree", "prune", "-v")
        console = make_console()
        if rc != 0:
            console.print(f"[red]Error:[/red] {out.strip() or 'git worktree prune failed'}")
            return 1
        if out.strip():
            console.print(out.rstrip())
        console.print("[green]✓[/green] Pruned stale worktree metadata")
        return 0

    def _status(self) -> int:
        """Show the current worktree's branch + dirty state."""
        rc_branch, branch_out = self._git("rev-parse", "--abbrev-ref", "HEAD")
        rc_status, status_out = self._git("status", "--porcelain")
        console = make_console()
        if rc_branch != 0:
            console.print(f"[red]Error:[/red] {branch_out.strip() or 'not a git repo'}")
            return 1
        branch = branch_out.strip() or "HEAD"
        dirty = [line for line in status_out.splitlines() if line.strip()]
        clean = not dirty
        console.print(
            f"Branch: [bold cyan]{branch}[/bold cyan]    "
            f"State: [{'green' if clean else 'yellow'}]"
            f"{'clean' if clean else f'dirty ({len(dirty)} change(s))'}[/]"
        )
        return 0

    # ----- helpers -----------------------------------------------------

    def _branch_exists(self, branch: str) -> bool:
        """Return True if *branch* already exists in the repo."""
        rc, _ = self._git("rev-parse", "--verify", f"refs/heads/{branch}")
        return rc == 0

    @staticmethod
    def _git(*args: str) -> tuple[int, str]:
        """Run ``git *args`` from the current directory and return (rc, stdout)."""
        try:
            completed = subprocess.run(
                ("git", *args), capture_output=True, text=True, check=False,
            )
        except FileNotFoundError:
            return 127, "git executable not found on PATH"
        return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def _parse_porcelain(raw: str) -> list[dict[str, str]]:
    """Parse ``git worktree list --porcelain`` into a list of dicts."""
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in raw.splitlines():
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        entries.append(current)
    return entries


def run(args: argparse.Namespace) -> int:  # pragma: no cover - thin wrapper
    """Programmatic entry point for the ``worktree`` subcommand."""
    return WorktreeCommand().run(args)


__all__ = ["WorktreeCommand", "run"]