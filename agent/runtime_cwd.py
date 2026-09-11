"""Runtime working-directory resolution for context discovery."""

from __future__ import annotations

import os
from pathlib import Path

_context_cwd: Path | None = None


def set_context_cwd(cwd: str) -> None:
    """Set the context working directory (e.g. from TERMINAL_CWD)."""
    global _context_cwd
    _context_cwd = Path(cwd).expanduser() if cwd else None


def resolve_context_cwd() -> Path | None:
    """Return the context cwd for context-file discovery.

    Priority: TERMINAL_CWD env var > programmatic override > launch cwd.
    """
    global _context_cwd
    env_cwd = os.environ.get("TERMINAL_CWD")
    if env_cwd:
        return Path(env_cwd).expanduser()
    if _context_cwd is not None:
        return _context_cwd
    cwd = os.getcwd()
    return Path(cwd) if cwd else None


def resolve_agent_cwd() -> Path:
    """Return the agent's working directory (never None)."""
    cwd = resolve_context_cwd()
    return cwd if cwd is not None else Path(os.getcwd())
