"""Zeloo Agent constants and path helpers."""

from __future__ import annotations

import os
from pathlib import Path

# Zeloo home directory resolution
_DEFAULT_HOME = Path.home() / ".Zeloo"

_home_override: str | None = None


def get_zeloo_home() -> Path:
    """Return the active Zeloo home directory.

    Resolution order:
    1. zeloo_HOME environment variable
    2. Programmatic override (set_zeloo_home_override)
    3. Default ~/.Zeloo
    """
    global _home_override
    env_home = os.environ.get("zeloo_HOME")
    if env_home:
        return Path(env_home).expanduser()
    if _home_override:
        return Path(_home_override).expanduser()
    return _DEFAULT_HOME


def set_zeloo_home_override(path: str) -> None:
    """Override the Zeloo home directory programmatically."""
    global _home_override
    _home_override = path


def reset_zeloo_home_override() -> None:
    """Clear the programmatic home override."""
    global _home_override
    _home_override = None


def get_zeloo_home_override() -> str | None:
    """Return the current programmatic home override, or None."""
    return _home_override


def get_default_zeloo_root() -> Path:
    """Return the default Zeloo root (ignoring overrides).

    This is the base directory under which profiles/ lives.
    """
    return _DEFAULT_HOME


def get_skills_dir() -> Path:
    """Return the skills directory under the active home."""
    return get_zeloo_home() / "skills"


def get_memories_dir() -> Path:
    """Return the memories directory under the active home."""
    return get_zeloo_home() / "memories"


def get_state_db_path() -> Path:
    """Return the SQLite state database path."""
    return get_zeloo_home() / "state.db"


def get_profiles_root() -> Path:
    """Return the directory that holds all named profiles.

    Profiles live under ``~/.Zeloo/profiles/<name>/`` and each contains
    its own config.yaml, skills/, memories/, and state.db. Activating a
    profile is equivalent to pointing zeloo_HOME at that directory.
    """
    return get_default_zeloo_root() / "profiles"


def get_profile_dir(name: str = "default") -> Path:
    """Return the directory for a named profile."""
    return get_profiles_root() / name


# Context file discovery order (highest priority first)
CONTEXT_FILE_NAMES = (".Zeloo.md", "Zeloo.md", "AGENTS.md", "CLAUDE.md", ".cursorrules")

# Default agent identity (used when SOUL.md is absent)
DEFAULT_AGENT_IDENTITY = (
    "You are Zeloo Agent, a self-hosted, self-evolving AI agent. "
    "Be direct: match the length of your reply to the weight of the ask. "
    "No filler, no restating the request, no narrating tool calls. "
    "Depth is earned — give it when the user asks for detail, not by default."
)

# Tool result length cap
MAX_TOOL_RESULT_LENGTH = 10000

# Default max iterations for the conversation loop
DEFAULT_MAX_ITERATIONS = 90

# Default parallel tool call workers
DEFAULT_MAX_WORKERS = 8

# Context compression thresholds
DEFAULT_CONTEXT_MAX_MESSAGES = 40        # trigger compression above this many messages
DEFAULT_CONTEXT_KEEP_RECENT = 10         # keep this many most-recent messages verbatim
DEFAULT_CONTEXT_SUMMARY_CHARS = 800      # max chars per summarized middle message
