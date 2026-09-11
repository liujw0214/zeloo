"""Skills tools — view, create, patch, delete."""

from __future__ import annotations

import os
from pathlib import Path

from agent.skill_utils import parse_frontmatter
from agent.zeloo_constants import get_skills_dir
from tools.base import tool


def _get_curator():
    """Lazily return a Curator instance for the skills directory."""
    from agent.curator import Curator

    skills_dir = os.environ.get("zeloo_HOME") or str(Path.home() / ".Zeloo")
    return Curator(skills_dir=str(Path(skills_dir) / "skills"))


@tool(name="skill_view", description="Load a skill's full content by name", toolset="skills")
def skill_view(name: str) -> str:
    """Load a skill's full SKILL.md content.

    Args:
        name: The skill name (directory name).
    """
    skill_path = get_skills_dir() / name / "SKILL.md"
    if not skill_path.is_file():
        return f"Skill '{name}' not found."
    try:
        content = skill_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading skill '{name}': {e}"
    # Track usage with the curator (reactivates stale/archived skills)
    try:
        _get_curator().track_usage(name)
    except Exception:
        pass
    return content


@tool(name="skills_list", description="List all available skills", toolset="skills")
def skills_list() -> str:
    """List all available skills with their descriptions."""
    from agent.skill_utils import (
        extract_skill_description,
        extract_skill_name,
        iter_skill_index_files,
    )

    entries = []
    for skill_file in iter_skill_index_files():
        try:
            content = skill_file.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            name = extract_skill_name(fm, skill_file)
            desc = extract_skill_description(fm)
            entries.append(f"- {name}: {desc}")
        except Exception:
            pass
    return "\n".join(entries) if entries else "(no skills)"


@tool(name="skill_manage", description="Create, patch, or delete a skill", toolset="skills")
def skill_manage(action: str, name: str, content: str = "") -> str:
    """Manage skills.

    Args:
        action: "create", "patch", or "delete".
        name: The skill name.
        content: Skill content (for create/patch). Should include YAML frontmatter.
    """
    skill_dir = get_skills_dir() / name
    skill_file = skill_dir / "SKILL.md"

    if action == "create":
        if skill_file.exists():
            return f"Error: Skill '{name}' already exists. Use 'patch' to update."
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(content, encoding="utf-8")
        _invalidate_skills_cache()
        return f"Skill '{name}' created."

    elif action == "patch":
        if not skill_file.exists():
            return f"Error: Skill '{name}' not found. Use 'create' first."
        skill_file.write_text(content, encoding="utf-8")
        _invalidate_skills_cache()
        return f"Skill '{name}' patched."

    elif action == "delete":
        if not skill_file.exists():
            return f"Error: Skill '{name}' not found."
        import shutil

        shutil.rmtree(skill_dir)
        _invalidate_skills_cache()
        return f"Skill '{name}' deleted."

    else:
        return f"Error: Unknown action '{action}'"


def _invalidate_skills_cache() -> None:
    """Clear the in-memory skills index cache after a mutation."""
    try:
        from agent.prompt_builder import invalidate_skills_cache

        invalidate_skills_cache()
    except Exception:
        pass
