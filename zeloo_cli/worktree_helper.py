"""Git worktree helper for --worktree global flag.

Provides automatic worktree creation/cleanup for the ``--worktree`` CLI flag.
When enabled, each Zeloo session runs in an isolated git worktree, allowing
multiple parallel agent runs without interfering with each other.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)


class WorktreeInfo(NamedTuple):
    """Information about a created worktree."""
    worktree_path: Path
    branch_name: str
    session_id: str
    created_at: float


def create_worktree(repo_root: Path, session_id: str | None = None) -> WorktreeInfo:
    """Create an isolated git worktree for the current session.

    Args:
        repo_root: Path to the git repository root.
        session_id: Optional session identifier. Auto-generated if None.

    Returns:
        WorktreeInfo with path, branch, and session ID.

    Raises:
        RuntimeError: If git is not available or worktree creation fails.
    """
    if not (repo_root / ".git").exists():
        raise RuntimeError(f"Not a git repository: {repo_root}")

    session_id = session_id or uuid.uuid4().hex[:8]
    branch_name = f"zeloo-{session_id}-{int(time.time())}"
    default_wt_root = "/tmp/zeloo-wt" if sys.platform != "win32" else str(
        Path(os.environ.get("TEMP", "C:/Windows/Temp")) / "zeloo-wt"
    )
    wt_root = Path(os.environ.get("ZELOO_WORKTREE_ROOT", default_wt_root))
    wt_root.mkdir(parents=True, exist_ok=True)
    wt_path = wt_root / session_id

    try:
        subprocess.run(
            ["git", "worktree", "add", "-b", branch_name, str(wt_path)],
            cwd=repo_root, check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error("git worktree add failed: %s", e.stderr)
        raise RuntimeError(f"Failed to create worktree: {e.stderr}") from e

    return WorktreeInfo(
        worktree_path=wt_path, branch_name=branch_name,
        session_id=session_id, created_at=time.time(),
    )


def cleanup_worktree(info: WorktreeInfo, repo_root: Path) -> None:
    """Remove a worktree and its branch."""
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(info.worktree_path)],
            cwd=repo_root, check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        logger.warning("Worktree remove failed: %s", e.stderr)
    try:
        subprocess.run(
            ["git", "branch", "-D", info.branch_name],
            cwd=repo_root, check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        logger.warning("Branch delete failed: %s", e.stderr)


def is_in_worktree() -> bool:
    """Check if current directory is inside a git worktree (not main checkout)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        )
        common = Path(result.stdout.strip()).resolve()
        result2 = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, check=True,
        )
        git_dir = Path(result2.stdout.strip()).resolve()
        return common != git_dir
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False


def should_enable_worktree(args: list[str] | None = None) -> bool:
    """Check if --worktree flag is set or env var is true."""
    if os.environ.get("zeloo_WORKTREE", "").lower() in ("1", "true", "yes"):
        return True
    if args and ("--worktree" in args or "-w" in args):
        return True
    return False


def list_zeloo_worktrees(repo_root: Path) -> list[dict[str, str]]:
    """List all Zeloo-created worktrees (branches matching ``zeloo-*``).

    Returns a list of dicts with keys: path, commit, branch.
    Empty list if git porcelain output cannot be parsed.
    """
    try:
        completed = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo_root, capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if not line:
            if current and current.get("branch", "").startswith("refs/heads/zeloo-"):
                entries.append(current)
            current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current and current.get("branch", "").startswith("refs/heads/zeloo-"):
        entries.append(current)
    return entries


__all__ = [
    "WorktreeInfo",
    "create_worktree",
    "cleanup_worktree",
    "is_in_worktree",
    "should_enable_worktree",
    "list_zeloo_worktrees",
]
