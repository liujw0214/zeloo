"""System prompt building blocks — identity, skills index, context files.

All functions are stateless. AIAgent._build_system_prompt() calls these to
assemble pieces, then combines them with memory and ephemeral prompts.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from agent.runtime_cwd import resolve_agent_cwd
from agent.skill_utils import (
    extract_skill_description,
    extract_skill_name,
    get_disabled_skill_names,
    iter_skill_index_files,
    parse_frontmatter,
    skill_matches_environment,
    skill_matches_platform,
)
from agent.zeloo_constants import (
    CONTEXT_FILE_NAMES,
    DEFAULT_AGENT_IDENTITY,  # noqa: F401  re-exported for agent.system_prompt
    get_skills_dir,
)
from tools.threat_patterns import scan_for_threats as _scan_for_threats

logger = logging.getLogger(__name__)


def _scan_context_content(content: str, filename: str) -> str:
    """Scan context file content for injection. Returns sanitized content."""
    if content.startswith("\ufeff"):
        content = content[1:]
    findings = _scan_for_threats(content, scope="context")
    if findings:
        logger.warning("Context file %s blocked: %s", filename, ", ".join(findings))
        return (
            f"[BLOCKED: {filename} contained potential prompt injection "
            f"({', '.join(findings)}). Content not loaded.]"
        )
    return content


def _find_git_root(start: Path) -> Path | None:
    """Walk *start* and its parents looking for a ``.git`` directory."""
    current = start.resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def _find_context_file(cwd: Path) -> Path | None:
    """Discover the nearest context file by priority order."""
    stop_at = _find_git_root(cwd)
    current = cwd.resolve()
    search_dirs = [current, *current.parents] if stop_at else [current]
    for directory in search_dirs:
        for name in CONTEXT_FILE_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        if stop_at and directory == stop_at:
            break
    return None


def load_soul_md(
    context_length: int | None = None, home_override: Path | None = None
) -> str | None:
    """Load SOUL.md from the agent's home. Returns None if absent."""
    home = home_override if home_override else get_skills_dir().parent
    soul_path = home / "SOUL.md"
    if not soul_path.is_file():
        return None
    try:
        content = soul_path.read_text(encoding="utf-8")
        return _scan_context_content(content, "SOUL.md")
    except Exception:
        logger.exception("Failed to load SOUL.md")
        return None


def build_context_files_prompt(
    cwd: Path | None = None,
    skip_soul: bool = False,
    context_length: int | None = None,
    home_override: Path | None = None,
) -> str:
    """Build the context-files prompt segment for the context tier."""
    if cwd is None:
        cwd = resolve_agent_cwd()

    context_file = _find_context_file(cwd)
    if not context_file:
        return ""

    # Don't double-load SOUL.md if it's already in the stable tier
    if skip_soul and context_file.name.upper() == "SOUL.MD":
        return ""

    try:
        content = context_file.read_text(encoding="utf-8")
        sanitized = _scan_context_content(content, context_file.name)
        if not sanitized:
            return ""
        return f"## Project Context ({context_file.name})\n{sanitized}"
    except Exception:
        logger.exception("Failed to read context file %s", context_file)
        return ""


# ── Skills index cache (LRU-style + manifest) ────────────────────────

_skills_cache: dict[tuple[Any, ...], str] = {}
_skills_cache_max_entries = 16


def _compute_skills_manifest(skills_dir_override: Path | None) -> str:
    """Return a stable hash of the current skill files' mtime + size.

    Used as part of the cache key so that added/removed/modified skills
    invalidate the cached prompt.
    """
    parts: list[str] = []
    for skill_file in iter_skill_index_files(skills_dir_override):
        try:
            stat = skill_file.stat()
            parts.append(f"{skill_file}:{stat.st_mtime_ns}:{stat.st_size}")
        except OSError:
            parts.append(f"{skill_file}:missing")
    raw = "|".join(sorted(parts))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def invalidate_skills_cache() -> None:
    """Clear the in-memory skills index cache."""
    _skills_cache.clear()


def build_skills_system_prompt(
    available_tools: set[str],
    available_toolsets: set[str],
    compact_categories: set[str] | None = None,
    skills_dir_override: Path | None = None,
    platform: str = "cli",
) -> str:
    """Build the skills index for the volatile tier.

    Only includes name + description (Progressive Disclosure).
    Results are cached in-memory keyed by (platform, disabled skills,
    available toolsets, skill-file manifest).
    """
    disabled = get_disabled_skill_names()
    manifest = _compute_skills_manifest(skills_dir_override)
    cache_key = (
        platform,
        frozenset(disabled),
        frozenset(available_toolsets),
        manifest,
    )

    cached = _skills_cache.get(cache_key)
    if cached is not None:
        return cached

    entries: list[str] = []

    for skill_file in iter_skill_index_files(skills_dir_override):
        try:
            content = skill_file.read_text(encoding="utf-8")
            frontmatter = parse_frontmatter(content)
            name = extract_skill_name(frontmatter, skill_file)
            if name in disabled:
                continue
            if not skill_matches_platform(frontmatter, platform):
                continue
            if not skill_matches_environment(frontmatter, available_toolsets):
                continue
            description = extract_skill_description(frontmatter)
            entries.append(f"- {name}: {description}")
        except Exception:
            logger.exception("Failed to read skill %s", skill_file)

    if not entries:
        result = ""
    else:
        result = "## Available Skills\n" + "\n".join(entries)

    # Simple LRU eviction: drop oldest entries when over capacity
    if len(_skills_cache) >= _skills_cache_max_entries:
        # Remove the first (oldest) key
        oldest = next(iter(_skills_cache))
        _skills_cache.pop(oldest, None)
    _skills_cache[cache_key] = result

    return result


def build_environment_hints() -> str:
    """Build a one-line environment hint (OS, Python version)."""
    import platform
    import sys

    os_name = platform.system()
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return f"Environment: {os_name}, Python {py_version}"


# Guidance constants
TASK_COMPLETION_GUIDANCE = (
    "When you have completed the user's request, give a concise summary of "
    "what was done, what was verified, and what remains. Do not replay the "
    "entire process."
)

PARALLEL_TOOL_CALL_GUIDANCE = (
    "When multiple tool calls are independent, issue them in parallel to "
    "save time. Do not serialize calls that have no data dependency."
)

MEMORY_GUIDANCE = (
    "You have persistent memory, carried across sessions. Save durable facts "
    "proactively. Write entries as declarative facts, not instructions to "
    "yourself."
)

SKILLS_GUIDANCE = (
    "When you work out a non-trivial workflow, record it with skill_manage "
    "for future reuse.\n\n"
    "## Skill Safety Rule\n"
    "A skill placeholder containing `[SKILL_PRUNED]` lost its content in "
    "context compression — reload it with skill_view(name='...') before "
    "acting on anything that depends on it."
)

PLATFORM_HINTS: dict[str, str] = {
    "cli": "You are in an interactive terminal. Output supports ANSI colors.",
    "tui": "You are in a TUI. Output is rendered in a scrollable pane.",
    "telegram": "You are chatting via Telegram. Messages have a 4096 char limit.",
    "discord": "You are chatting via Discord. Use markdown for formatting.",
    "api": "You are accessed via API. Return structured responses.",
}
