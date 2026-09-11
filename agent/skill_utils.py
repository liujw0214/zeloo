"""Skill utility helpers — frontmatter parsing, filtering, index iteration."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agent.zeloo_constants import get_skills_dir

EXCLUDED_SKILL_DIRS = {"__pycache__", ".git", "node_modules"}
SKILL_SUPPORT_DIRS = {"examples", "assets", "templates"}

# Patterns that indicate a skill candidate contains sensitive data.
_SECRET_PATTERNS = (
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?i)(password|secret|token|api_key)\s*[=:]\s*\S+"),
)


def parse_frontmatter(content: str) -> dict[str, Any]:
    """Parse YAML frontmatter from a SKILL.md string.

    Returns a dict of metadata. The body is stored under the "body" key.
    """
    result: dict[str, Any] = {}
    if not content.startswith("---"):
        result["body"] = content
        return result

    end = content.find("\n---", 3)
    if end == -1:
        result["body"] = content
        return result

    frontmatter_text = content[3:end].strip()
    body = content[end + 4 :].lstrip("\n")

    # Minimal YAML frontmatter parsing (name, description, platforms, toolsets)
    for line in frontmatter_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            # Handle list values like [cli, tui]
            if value.startswith("[") and value.endswith("]"):
                items = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
                result[key] = items
            else:
                result[key] = value.strip("'\"")

    result["body"] = body
    return result


def extract_skill_name(frontmatter: dict[str, Any], path: Path) -> str:
    """Extract skill name from frontmatter or directory name."""
    name = frontmatter.get("name")
    if name:
        return str(name)
    return path.parent.name


def extract_skill_description(frontmatter: dict[str, Any]) -> str:
    """Extract skill description from frontmatter."""
    return str(frontmatter.get("description", ""))


def extract_skill_conditions(frontmatter: dict[str, Any]) -> dict[str, Any]:
    """Extract platform/toolset conditions from frontmatter."""
    return {
        "platforms": frontmatter.get("platforms", []),
        "toolsets": frontmatter.get("toolsets", []),
    }


def skill_matches_platform(frontmatter: dict[str, Any], platform: str) -> bool:
    """Check if a skill is available on the given platform."""
    platforms = frontmatter.get("platforms", [])
    if not platforms:
        return True  # No restriction = available everywhere
    return platform in platforms


def skill_matches_platform_list(
    frontmatter: dict[str, Any], platforms: Iterable[str]
) -> bool:
    """Check if a skill is available on any of the given platforms."""
    skill_platforms = frontmatter.get("platforms", [])
    if not skill_platforms:
        return True
    return any(p in skill_platforms for p in platforms)


def skill_matches_environment(
    frontmatter: dict[str, Any], available_toolsets: set[str]
) -> bool:
    """Check if a skill's required toolsets are available."""
    required = frontmatter.get("toolsets", [])
    if not required:
        return True
    return all(t in available_toolsets for t in required)


def get_all_skills_dirs(home_override: Path | None = None) -> list[Path]:
    """Return all directories that may contain skills.

    Includes:
    1. The user's skills directory (``~/.Zeloo/skills``) — user-installed
       and auto-generated skills take precedence.
    2. The bundled skills directory (``<project>/skills``) — built-in skills
       shipped with the project.
    """
    dirs: list[Path] = []
    if home_override:
        dirs.append(home_override)
    else:
        dirs.append(get_skills_dir())
    # Bundled skills shipped with the project (read-only, lower precedence).
    bundled = Path(__file__).resolve().parent.parent / "skills"
    if bundled.is_dir():
        dirs.append(bundled)
    return [d for d in dirs if d.is_dir()]


def get_disabled_skill_names() -> set[str]:
    """Return the set of disabled skill names (from config).

    Reads ``skills.disabled`` from config.yaml. Falls back to the
    ``zeloo_DISABLED_SKILLS`` env var (comma-separated).
    """
    disabled: set[str] = set()

    # Env var override
    env_val = os.environ.get("zeloo_DISABLED_SKILLS", "")
    if env_val:
        disabled.update(s.strip() for s in env_val.split(",") if s.strip())

    # Config file
    try:
        from zeloo_cli.config import load_config

        config = load_config()
        if isinstance(config, dict):
            skills_cfg = config.get("skills", {})
            if isinstance(skills_cfg, dict):
                disabled_list = skills_cfg.get("disabled", [])
                if isinstance(disabled_list, list):
                    disabled.update(str(s) for s in disabled_list)
    except Exception:
        pass

    return disabled


class SkillRegistrar:
    """Helper passed to plugin ``register()`` so plugins can install skills.

    Writes a ``<name>/SKILL.md`` file into the user skills directory.
    """

    def __init__(self, home_override: Path | None = None) -> None:
        self._base = home_override if home_override else get_skills_dir()

    def register_skill(self, name: str, content: str) -> Path:
        """Create a skill directory with a SKILL.md file.

        Args:
            name: Skill name (used as the directory name).
            content: Full SKILL.md content (including frontmatter).

        Returns:
            Path to the created SKILL.md file.
        """
        skill_dir = self._base / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(content, encoding="utf-8")
        return skill_file

    def unregister_skill(self, name: str) -> bool:
        """Remove a skill directory. Returns True if it existed."""
        import shutil

        skill_dir = self._base / name
        if skill_dir.is_dir():
            shutil.rmtree(skill_dir)
            return True
        return False


def iter_skill_index_files(home_override: Path | None = None) -> Iterable[Path]:
    """Iterate over all SKILL.md files in the skills directories.

    User-installed skills (earlier directories) take precedence over
    bundled skills on name conflict — only the first occurrence of each
    skill name is yielded.
    """
    seen: set[str] = set()
    for skills_dir in get_all_skills_dirs(home_override):
        if not skills_dir.is_dir():
            continue
        for child in skills_dir.iterdir():
            if not child.is_dir() or child.name in EXCLUDED_SKILL_DIRS:
                continue
            if child.name in seen:
                continue
            skill_md = child / "SKILL.md"
            if skill_md.is_file():
                seen.add(child.name)
                yield skill_md


# ── Skill candidate validation (used by background review) ──────────

def contains_secrets(content: str) -> bool:
    """Return True if *content* matches any known secret pattern.

    Used to reject skill candidates that may have captured API keys,
    passwords, or private keys from the conversation.
    """
    return any(p.search(content) for p in _SECRET_PATTERNS)


def has_valid_frontmatter(content: str) -> bool:
    """Return True if *content* has parseable YAML frontmatter with a name.

    A valid SKILL.md starts with ``---``, ends the frontmatter block with
    ``---``, and contains at least a ``name`` field.
    """
    if not content.startswith("---"):
        return False
    end = content.find("\n---", 3)
    if end == -1:
        return False
    fm = parse_frontmatter(content)
    return bool(fm.get("name"))


def validate_skill_candidate(name: str, content: str) -> tuple[bool, str]:
    """Validate an auto-extracted skill candidate before persisting.

    Checks (in order):
      1. Content is non-empty.
      2. Name does not conflict with an existing skill.
      3. Content does not contain secrets.
      4. Content has valid frontmatter with a ``name`` field.

    Returns:
        ``(ok, reason)`` — ``ok`` is True when the candidate passes all
        checks; ``reason`` is an empty string on success or a human-readable
        explanation on failure.
    """
    if not content or not content.strip():
        return False, "skill content is empty"

    if skill_exists(name):
        return False, f"skill '{name}' already exists"

    if contains_secrets(content):
        return False, "skill content contains potential secrets"

    if not has_valid_frontmatter(content):
        return False, "skill content is missing valid frontmatter (name field required)"

    return True, ""


def skill_exists(name: str) -> bool:
    """Return True if a skill directory named *name* already exists."""
    skills_dir = get_skills_dir()
    return (skills_dir / name / "SKILL.md").is_file()
