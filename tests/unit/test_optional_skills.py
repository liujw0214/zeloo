"""Tests for optional_skills — skill_loader, modules, and @tool wrappers."""

from __future__ import annotations

import tempfile
from pathlib import Path

from optional_skills.skill_loader import (
    SkillInfo,
    _parse_skill_md,
    find_skill_by_name,
    load_skill_index,
)


class TestSkillInfo:
    def test_instantiation(self) -> None:
        info = SkillInfo(
            name="test_skill",
            category="devops",
            description="A test skill",
            triggers=["trigger1", "trigger2"],
            version="1.0.0",
            path=Path("/tmp/test_skill"),
        )
        assert info.name == "test_skill"
        assert info.category == "devops"
        assert len(info.triggers) == 2


class TestLoadSkillIndex:
    def test_load_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skills = load_skill_index(Path(tmp))
            assert skills == []

    def test_load_nonexistent_dir(self) -> None:
        skills = load_skill_index(Path("/nonexistent/path/xyz123"))
        assert skills == []

    def test_load_single_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cat_dir = tmp_path / "devops"
            skill_dir = cat_dir / "docker_build"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: docker_build\ndescription: Build Docker images\nversion: 2.0.0\n---\n\n## Triggers\n\n- \"build docker\"\n- \"docker build\"",
                encoding="utf-8",
            )
            skills = load_skill_index(tmp_path)
            assert len(skills) == 1
            assert skills[0].name == "docker_build"
            assert skills[0].category == "devops"
            assert skills[0].version == "2.0.0"
            assert "build docker" in skills[0].triggers
            assert "docker build" in skills[0].triggers

    def test_load_multiple_categories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for cat in ["devops", "security", "data_science"]:
                skill_dir = tmp_path / cat / f"sample_{cat}"
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text(
                    f"---\nname: sample_{cat}\ndescription: test\n---\n",
                    encoding="utf-8",
                )
            skills = load_skill_index(tmp_path)
            assert len(skills) == 3
            categories = {s.category for s in skills}
            assert categories == {"devops", "security", "data_science"}

    def test_skips_non_md_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cat_dir = tmp_path / "devops"
            skill_dir = cat_dir / "real_skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: real_skill\n---\n", encoding="utf-8"
            )
            fake_dir = cat_dir / "no_md"
            fake_dir.mkdir(parents=True)
            (fake_dir / "README.md").write_text("not a skill", encoding="utf-8")
            skills = load_skill_index(tmp_path)
            assert len(skills) == 1


class TestParseSkillMd:
    def test_minimal_frontmatter(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("---\nname: minimal\ndescription: Minimal skill\n---\n\n# Body\n")
            path = Path(f.name)
        info = _parse_skill_md(path, "test", "fallback")
        assert info is not None
        assert info.name == "minimal"
        assert info.description == "Minimal skill"
        assert info.version == "1.0.0"

    def test_fallback_name_used(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Body only, no frontmatter\n")
            path = Path(f.name)
        info = _parse_skill_md(path, "test", "my_fallback")
        assert info is not None
        assert info.name == "my_fallback"

    def test_triggers_parsed(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(
                "---\nname: t\n---\n\n## Triggers\n\n- foo\n- 'bar'\n- \"baz\"\n\n## Other\n\nskip\n"
            )
            path = Path(f.name)
        info = _parse_skill_md(path, "test", "t")
        assert info is not None
        assert "foo" in info.triggers
        assert "bar" in info.triggers
        assert "baz" in info.triggers


class TestFindSkillByName:
    def test_find_existing_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cat_dir = tmp_path / "devops"
            skill_dir = cat_dir / "unique_skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: unique_skill\ndescription: test\n---\n",
                encoding="utf-8",
            )
            info = find_skill_by_name("unique_skill", tmp_path)
            assert info is not None
            assert info.name == "unique_skill"

    def test_find_nonexistent_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            info = find_skill_by_name("nonexistent", Path(tmp))
            assert info is None


class TestOptionalSkillsModules:
    def test_software_development_importable(self) -> None:
        import optional_skills.software_development as mod

        assert hasattr(mod, "__all__")

    def test_devops_importable(self) -> None:
        import optional_skills.devops as mod

        assert hasattr(mod, "__all__")

    def test_data_science_importable(self) -> None:
        import optional_skills.data_science as mod

        assert hasattr(mod, "__all__")

    def test_mlops_importable(self) -> None:
        import optional_skills.mlops as mod

        assert hasattr(mod, "__all__")

    def test_research_importable(self) -> None:
        import optional_skills.research as mod

        assert hasattr(mod, "__all__")

    def test_security_importable(self) -> None:
        import optional_skills.security as mod

        assert hasattr(mod, "__all__")


class TestOptionalSkillsPackage:
    def test_all_exports(self) -> None:
        import optional_skills

        expected = {
            "skill_loader",
            "software_development",
            "devops",
            "data_science",
            "mlops",
            "research",
            "security",
        }
        actual = set(optional_skills.__all__)
        assert actual == expected

    def test_modules_have_functions(self) -> None:
        import optional_skills.devops as devops
        import optional_skills.security as sec
        import optional_skills.software_development as sd

        assert len(sd.__all__) >= 1
        assert len(devops.__all__) >= 1
        assert len(sec.__all__) >= 1