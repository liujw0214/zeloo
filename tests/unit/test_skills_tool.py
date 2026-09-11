"""Tests for skills_tool (skill_view, skills_list, skill_manage)."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, ".")

SKILL_CONTENT = """---
name: test-skill
description: A test skill
platforms: [cli]
toolsets: [file]
---

# Test Skill
Content here.
"""


def _make_skills_dir(tmp: Path, name: str, content: str = SKILL_CONTENT) -> Path:
    skill_dir = tmp / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return tmp


def test_skill_view_not_found(tmp_path):
    with patch("tools.skills_tool.get_skills_dir", return_value=tmp_path):
        from tools.skills_tool import skill_view

        assert "not found" in skill_view("nonexistent")


def test_skill_view_found(tmp_path):
    _make_skills_dir(tmp_path, "test-skill")
    with patch("tools.skills_tool.get_skills_dir", return_value=tmp_path):
        from tools.skills_tool import skill_view

        content = skill_view("test-skill")
        assert "# Test Skill" in content


def test_skill_manage_create(tmp_path):
    with patch("tools.skills_tool.get_skills_dir", return_value=tmp_path), patch(
        "tools.skills_tool._invalidate_skills_cache"
    ):
        from tools.skills_tool import skill_manage

        result = skill_manage("create", "new-skill", SKILL_CONTENT)
        assert "created" in result
        assert (tmp_path / "new-skill" / "SKILL.md").is_file()


def test_skill_manage_create_duplicate(tmp_path):
    _make_skills_dir(tmp_path, "existing")
    with patch("tools.skills_tool.get_skills_dir", return_value=tmp_path), patch(
        "tools.skills_tool._invalidate_skills_cache"
    ):
        from tools.skills_tool import skill_manage

        result = skill_manage("create", "existing", SKILL_CONTENT)
        assert "already exists" in result


def test_skill_manage_patch(tmp_path):
    _make_skills_dir(tmp_path, "patchable")
    with patch("tools.skills_tool.get_skills_dir", return_value=tmp_path), patch(
        "tools.skills_tool._invalidate_skills_cache"
    ):
        from tools.skills_tool import skill_manage

        new_content = "---\nname: patchable\ndescription: patched\n---\nPatched."
        result = skill_manage("patch", "patchable", new_content)
        assert "patched" in result
        assert "Patched." in (tmp_path / "patchable" / "SKILL.md").read_text()


def test_skill_manage_patch_missing(tmp_path):
    with patch("tools.skills_tool.get_skills_dir", return_value=tmp_path), patch(
        "tools.skills_tool._invalidate_skills_cache"
    ):
        from tools.skills_tool import skill_manage

        result = skill_manage("patch", "ghost", "content")
        assert "not found" in result


def test_skill_manage_delete(tmp_path):
    _make_skills_dir(tmp_path, "deletable")
    with patch("tools.skills_tool.get_skills_dir", return_value=tmp_path), patch(
        "tools.skills_tool._invalidate_skills_cache"
    ):
        from tools.skills_tool import skill_manage

        result = skill_manage("delete", "deletable")
        assert "deleted" in result or "removed" in result
        assert not (tmp_path / "deletable").exists()


def test_skill_manage_invalid_action(tmp_path):
    with patch("tools.skills_tool.get_skills_dir", return_value=tmp_path):
        from tools.skills_tool import skill_manage

        result = skill_manage("bogus", "x", "")
        assert "Error" in result


def test_skills_list(tmp_path):
    skills_dir = tmp_path / "skills"
    _make_skills_dir(
        skills_dir,
        "listed-skill",
        content=(
            "---\nname: listed-skill\ndescription: A listed skill\n"
            "platforms: [cli]\ntoolsets: [file]\n---\n\n# Listed Skill\n"
        ),
    )
    with patch.dict("os.environ", {"zeloo_HOME": str(tmp_path)}):
        from tools.skills_tool import skills_list

        result = skills_list()
        assert "code-review" in result
        assert "listed-skill" in result


if __name__ == "__main__":
    import shutil
    from pathlib import Path

    base = Path(__file__).parent / "_tmp_skills"
    tests = [
        test_skill_view_not_found,
        test_skill_view_found,
        test_skill_manage_create,
        test_skill_manage_create_duplicate,
        test_skill_manage_patch,
        test_skill_manage_patch_missing,
        test_skill_manage_delete,
        test_skill_manage_invalid_action,
        test_skills_list,
    ]
    for t in tests:
        if base.exists():
            shutil.rmtree(base)
        base.mkdir(parents=True, exist_ok=True)
        t(base)
    if base.exists():
        shutil.rmtree(base)
    print("All skills_tool tests passed!")
