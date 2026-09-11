"""Zeloo ``worktree-cleanup`` subcommand — clean up stale Zeloo worktrees.

This complements ``zeloo worktree`` (which manages arbitrary worktrees) by
focusing specifically on the ``zeloo-*`` branches/checkouts created by the
``--worktree`` global flag.
"""
from __future__ import annotations

import argparse
import logging
import re
import subprocess
import time
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand
from zeloo_cli.worktree_helper import list_zeloo_worktrees

logger = logging.getLogger(__name__)

# Branch naming convention used by worktree_helper.create_worktree().
_ZELOO_BRANCH_RE = re.compile(r"^refs/heads/zeloo-([0-9a-f]+)-(\d+)$")


@subcommand("worktree-cleanup")
class WorktreeCleanupCommand(Subcommand):
    """Clean up stale Zeloo-created worktrees."""

    name = "worktree-cleanup"
    help = "Remove all stale Zeloo worktrees (created via --worktree)"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--dry-run", action="store_true",
            help="List candidates without removing them",
        )
        parser.add_argument(
            "--older-than-hours", type=int, default=24,
            help="Only remove worktrees older than N hours (default: 24)",
        )
        parser.add_argument(
            "--yes", action="store_true",
            help="Skip interactive confirmation",
        )
        parser.add_argument(
            "--repo-root", default=None,
            help="Path to the git repo root (defaults to current directory)",
        )

    def run(self, args: argparse.Namespace) -> int:
        repo_root = Path(args.repo_root).resolve() if args.repo_root else Path.cwd()
        if not (repo_root / ".git").exists():
            print(f"Error: not a git repository: {repo_root}", flush=True)
            return 1

        entries = list_zeloo_worktrees(repo_root)
        if not entries:
            print("No Zeloo worktrees found.", flush=True)
            return 0

        now = time.time()
        cutoff = now - (args.older_than_hours * 3600)

        candidates: list[dict[str, str]] = []
        for entry in entries:
            branch = entry.get("branch", "")
            m = _ZELOO_BRANCH_RE.match(branch)
            if not m:
                continue
            try:
                created_ts = int(m.group(2))
            except ValueError:
                continue
            if created_ts >= cutoff:
                continue
            candidates.append(entry)

        if not candidates:
            print(
                f"No Zeloo worktrees older than {args.older_than_hours}h "
                f"({len(entries)} active).",
                flush=True,
            )
            return 0

        print(
            f"Found {len(candidates)} stale Zeloo worktree(s) "
            f"(older than {args.older_than_hours}h):",
            flush=True,
        )
        for entry in candidates:
            branch_short = entry.get("branch", "").replace("refs/heads/", "")
            print(f"  - {entry.get('path', '?')}  ({branch_short})", flush=True)

        if args.dry_run:
            print("\nDry-run; no changes made.", flush=True)
            return 0

        if not args.yes:
            try:
                answer = input("\nRemove these worktrees? [y/N] ").strip().lower()
            except EOFError:
                answer = "n"
            if answer not in ("y", "yes"):
                print("Aborted.", flush=True)
                return 1

        removed = 0
        failed = 0
        for entry in candidates:
            path = entry.get("path", "")
            branch = entry.get("branch", "").replace("refs/heads/", "")
            try:
                self._git(*["worktree", "remove", "--force", path], cwd=repo_root)
            except subprocess.CalledProcessError as exc:
                logger.warning("worktree remove failed for %s: %s", path, exc.stderr)
                failed += 1
                continue
            try:
                self._git(*["branch", "-D", branch], cwd=repo_root)
            except subprocess.CalledProcessError as exc:
                logger.warning("branch delete failed for %s: %s", branch, exc.stderr)
            removed += 1

        # Prune any stale metadata left behind.
        try:
            self._git("worktree", "prune", cwd=repo_root)
        except subprocess.CalledProcessError:
            pass

        print(
            f"\nDone: removed {removed} worktree(s); {failed} failure(s).",
            flush=True,
        )
        return 0 if failed == 0 else 1

    @staticmethod
    def _git(*args: str, cwd: Path) -> None:
        """Run ``git *args`` from *cwd* and raise on non-zero exit."""
        subprocess.run(
            ("git", *args), cwd=cwd, capture_output=True, text=True, check=True,
        )


__all__ = ["WorktreeCleanupCommand"]
