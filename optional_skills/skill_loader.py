"""Skill loader — discovers and loads optional skills."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SkillInfo:
    """Metadata for a discovered skill."""

    name: str
    category: str
    description: str
    triggers: list[str]
    version: str
    path: Path


def load_skill_index(skill_dir: Path) -> list[SkillInfo]:
    """Scan *skill_dir* and return metadata for all SKILL.md files found."""
    skills: list[SkillInfo] = []

    if not skill_dir.is_dir():
        return skills

    for category_dir in sorted(skill_dir.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name

        for skill_dir_path in sorted(category_dir.iterdir()):
            if not skill_dir_path.is_dir():
                continue
            skill_md = skill_dir_path / "SKILL.md"
            if not skill_md.is_file():
                continue

            info = _parse_skill_md(skill_md, category, skill_dir_path.name)
            if info:
                skills.append(info)

    return skills


def _parse_skill_md(path: Path, category: str, fallback_name: str) -> SkillInfo | None:
    """Parse a SKILL.md file and extract frontmatter + triggers."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return None

    frontmatter: dict[str, Any] = {}
    body_lines: list[str] = []
    in_fm = False
    fm_lines: list[str] = []

    for raw in content.splitlines():
        stripped = raw.strip()
        if stripped == "---":
            if not in_fm:
                in_fm = True
            else:
                in_fm = False
            continue
        if in_fm:
            fm_lines.append(stripped)
        else:
            body_lines.append(raw)

    for line in fm_lines:
        if ":" in line:
            key, _, value = line.partition(":")
            frontmatter[key.strip()] = value.strip()

    name = frontmatter.get("name", fallback_name)
    description = frontmatter.get("description", "")
    version = frontmatter.get("version", "1.0.0")

    triggers: list[str] = []
    body = "\n".join(body_lines)
    trigger_section = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("## triggers"):
            trigger_section = True
            continue
        if trigger_section and stripped.startswith("#"):
            trigger_section = False
            continue
        if trigger_section and stripped.startswith("- "):
            triggers.append(stripped[2:].strip().strip('"').strip("'"))

    return SkillInfo(
        name=name,
        category=category,
        description=description,
        triggers=triggers,
        version=version,
        path=path.parent,
    )


def find_skill_by_name(name: str, skill_dir: Path) -> SkillInfo | None:
    """Find a skill by exact name across all categories."""
    for skill in load_skill_index(skill_dir):
        if skill.name == name:
            return skill
    return None
