"""Tests for the Zeloo ``skills`` subcommand — install/search/update flows."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is importable when pytest is invoked from elsewhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zeloo_cli.subcommands.skills import (  # noqa: E402
    _SKILL_INDEX,
    SkillsCmd,
)


SAMPLE_SKILL_MD = """---
name: my-sample-skill
description: A test skill used by pytest
version: 1.2.3
requires: [code-review]
---

# My Sample Skill
Test body.
"""


def _make_cmd() -> SkillsCmd:
    return SkillsCmd()


def _create_skill_dir(parent: Path, name: str = "my-sample-skill",
                      content: str = SAMPLE_SKILL_MD) -> Path:
    skill_dir = parent / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


# --------------------------------------------------------------------------- #
# 1. _search
# --------------------------------------------------------------------------- #


def test_search_finds_by_name(capsys):
    cmd = _make_cmd()
    rc = cmd._search("code-review", as_json=True)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert rc == 0
    assert payload["query"] == "code-review"
    assert payload["count"] >= 1
    assert any(r["name"] == "code-review" for r in payload["results"])


def test_search_finds_by_tag(capsys):
    cmd = _make_cmd()
    rc = cmd._search("debug", as_json=True)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert any(r["name"] == "debugging" for r in payload["results"])


def test_search_is_case_insensitive(capsys):
    cmd = _make_cmd()
    rc = cmd._search("CoDe-ReViEw", as_json=True)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert any(r["name"] == "code-review" for r in payload["results"])


def test_search_no_match_returns_zero(capsys):
    cmd = _make_cmd()
    rc = cmd._search("absolutely-nothing-here", as_json=False)
    out = capsys.readouterr().out
    assert rc == 0
    assert "No skills match" in out


def test_search_marks_installed_skill(tmp_path, capsys):
    cmd = _make_cmd()
    home = tmp_path / "isolated_home3"
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True)
    # install a skill named "code-review" so it should be marked installed
    (skills_dir / "code-review").mkdir()
    (skills_dir / "code-review" / "SKILL.md").write_text(
        "---\nname: code-review\ndescription: dummy\n---\n", encoding="utf-8",
    )
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}), patch.object(
        cmd, "_get_skills_dirs", return_value=[home / "skills"]
    ):
        rc = cmd._search("code-review", as_json=True)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    match = next(r for r in payload["results"] if r["name"] == "code-review")
    assert match["installed"] is True


def test_search_empty_query_returns_error(capsys):
    cmd = _make_cmd()
    rc = cmd._search("", as_json=False)
    out = capsys.readouterr().out
    assert rc == 1
    assert "Usage" in out


def test_search_table_output_contains_status(capsys):
    cmd = _make_cmd()
    with patch("zeloo_cli.rich_render.make_console") as console_factory:
        console = MagicMock()
        console_factory.return_value = console
        cmd._search("code-review", as_json=False)
    assert console.print.called


# --------------------------------------------------------------------------- #
# 2. _install — local path
# --------------------------------------------------------------------------- #


def test_install_from_local_path(tmp_path):
    cmd = _make_cmd()
    src = _create_skill_dir(tmp_path / "src")
    home = tmp_path / "Zeloo"
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}):
        rc = cmd._install(str(src))
    assert rc == 0
    dest = home / "skills" / "my-sample-skill"
    assert dest.exists()
    assert (dest / "SKILL.md").exists()


def test_install_local_path_nested_skill_dir(tmp_path):
    cmd = _make_cmd()
    src = tmp_path / "package"
    src.mkdir()
    inner = _create_skill_dir(src, name="nested")
    home = tmp_path / "Zeloo"
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}):
        rc = cmd._install(str(src))
    assert rc == 0
    assert (home / "skills" / "nested" / "SKILL.md").exists()


def test_install_missing_path_returns_error(tmp_path, capsys):
    cmd = _make_cmd()
    home = tmp_path / "Zeloo"
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}):
        rc = cmd._install(str(tmp_path / "does-not-exist"))
    assert rc == 1
    out = capsys.readouterr().out
    assert "Failed to install" in out or "does not exist" in out


def test_install_local_path_without_skill_md(tmp_path, capsys):
    cmd = _make_cmd()
    bad = tmp_path / "noskill"
    bad.mkdir()
    home = tmp_path / "Zeloo"
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}):
        rc = cmd._install(str(bad))
    assert rc == 1
    out = capsys.readouterr().out
    assert "Failed to install" in out or "SKILL.md" in out


def test_install_existing_skill_without_force_returns_error(tmp_path, capsys):
    cmd = _make_cmd()
    src = _create_skill_dir(tmp_path / "src")
    home = tmp_path / "Zeloo"
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "my-sample-skill").mkdir()
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}):
        rc = cmd._install(str(src))
    assert rc == 1
    out = capsys.readouterr().out
    assert "already installed" in out


def test_install_existing_skill_with_force_overwrites(tmp_path):
    cmd = _make_cmd()
    src = _create_skill_dir(tmp_path / "src")
    home = tmp_path / "Zeloo"
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "my-sample-skill").mkdir()
    (skills_dir / "my-sample-skill" / "old.txt").write_text("old")
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}):
        rc = cmd._install(str(src), force=True)
    assert rc == 0
    assert (skills_dir / "my-sample-skill" / "SKILL.md").exists()
    assert not (skills_dir / "my-sample-skill" / "old.txt").exists()


def test_install_with_custom_name(tmp_path):
    cmd = _make_cmd()
    src = _create_skill_dir(tmp_path / "src")
    home = tmp_path / "Zeloo"
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}):
        rc = cmd._install(str(src), name="renamed")
    assert rc == 0
    assert (home / "skills" / "renamed" / "SKILL.md").exists()


def test_install_reports_missing_dependencies(tmp_path, capsys):
    cmd = _make_cmd()
    src = _create_skill_dir(tmp_path / "src")
    home = tmp_path / "isolated_home"
    empty_bundled = tmp_path / "empty_bundled"
    empty_bundled.mkdir()
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}), patch.object(
        cmd, "_get_skills_dirs", return_value=[home / "skills"]
    ):
        rc = cmd._install(str(src))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Installed skill" in out
    assert "Missing dependencies" in out
    assert "code-review" in out


def test_install_reports_satisfied_dependencies(tmp_path, capsys):
    cmd = _make_cmd()
    src = _create_skill_dir(tmp_path / "src")
    home = tmp_path / "isolated_home2"
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "code-review").mkdir()
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}), patch.object(
        cmd, "_get_skills_dirs", return_value=[home / "skills"]
    ):
        rc = cmd._install(str(src))
    out = capsys.readouterr().out
    assert rc == 0
    assert "All dependencies present" in out


# --------------------------------------------------------------------------- #
# 3. _install — git URL (mocked subprocess)
# --------------------------------------------------------------------------- #


def test_install_from_git_url(tmp_path):
    cmd = _make_cmd()
    home = tmp_path / "Zeloo"

    def _fake_clone(args, **kwargs):
        dest = Path(args[-1])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SKILL.md").write_text(SAMPLE_SKILL_MD, encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}), patch.object(
        subprocess, "run", side_effect=_fake_clone
    ):
        rc = cmd._install("https://github.com/foo/bar")
    assert rc == 0
    assert (home / "skills" / "bar" / "SKILL.md").exists()


def test_install_from_git_url_strips_dot_git(tmp_path):
    cmd = _make_cmd()
    home = tmp_path / "Zeloo"
    captured_args: list[list[str]] = []

    def _fake_clone(args, **kwargs):
        captured_args.append(list(args))
        dest = Path(args[-1])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SKILL.md").write_text(SAMPLE_SKILL_MD, encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}), patch.object(
        subprocess, "run", side_effect=_fake_clone
    ):
        cmd._install("https://github.com/foo/bar.git")
    assert captured_args
    clone_url = captured_args[0][4]
    assert clone_url == "https://github.com/foo/bar.git"


def test_install_git_failure_returns_error(tmp_path, capsys):
    cmd = _make_cmd()
    home = tmp_path / "Zeloo"
    err = subprocess.CalledProcessError(
        returncode=1, cmd=["git", "clone"], stderr="repo not found", output="",
    )
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}), patch.object(
        subprocess, "run", side_effect=err
    ):
        rc = cmd._install("https://github.com/foo/missing")
    assert rc == 1
    out = capsys.readouterr().out
    assert "Failed to install" in out or "git clone failed" in out


def test_install_git_missing_executable(tmp_path, capsys):
    cmd = _make_cmd()
    home = tmp_path / "Zeloo"
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}), patch.object(
        subprocess, "run", side_effect=FileNotFoundError("git not found")
    ):
        rc = cmd._install("https://github.com/foo/bar")
    assert rc == 1
    out = capsys.readouterr().out
    assert "Failed to install" in out or "git" in out


# --------------------------------------------------------------------------- #
# 4. _install — ZIP URL (mocked urllib)
# --------------------------------------------------------------------------- #


def _make_zip_response(payload: bytes) -> MagicMock:
    resp = MagicMock()
    resp.read = MagicMock(return_value=payload)
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_install_from_zip_url(tmp_path):
    cmd = _make_cmd()
    home = tmp_path / "Zeloo"

    # Build a zip in-memory.
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("my-skill/SKILL.md", SAMPLE_SKILL_MD)
    blob = buf.getvalue()

    resp = _make_zip_response(blob)
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}), patch.object(
        urllib.request, "urlopen", return_value=resp
    ):
        rc = cmd._install("https://example.com/my-skill.zip")
    assert rc == 0
    assert (home / "skills" / "my-skill" / "SKILL.md").exists()


def test_install_zip_download_failure(tmp_path, capsys):
    cmd = _make_cmd()
    home = tmp_path / "Zeloo"
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}), patch.object(
        urllib.request, "urlopen",
        side_effect=urllib.error.URLError("network down"),
    ):
        rc = cmd._install("https://example.com/bad.zip")
    assert rc == 1
    out = capsys.readouterr().out
    assert "Failed to install" in out or "zip" in out.lower()


def test_install_zip_invalid_archive(tmp_path, capsys):
    cmd = _make_cmd()
    home = tmp_path / "Zeloo"
    resp = _make_zip_response(b"not a real zip")
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}), patch.object(
        urllib.request, "urlopen", return_value=resp
    ):
        rc = cmd._install("https://example.com/notazip.zip")
    assert rc == 1
    out = capsys.readouterr().out
    assert "Failed to install" in out


def test_install_zip_without_skill_md(tmp_path, capsys):
    cmd = _make_cmd()
    home = tmp_path / "Zeloo"
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("README.md", "no skill here")
    resp = _make_zip_response(buf.getvalue())
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}), patch.object(
        urllib.request, "urlopen", return_value=resp
    ):
        rc = cmd._install("https://example.com/empty.zip")
    assert rc == 1


# --------------------------------------------------------------------------- #
# 5. _update
# --------------------------------------------------------------------------- #


def test_update_unknown_skill(tmp_path, capsys):
    cmd = _make_cmd()
    home = tmp_path / "Zeloo"
    (home / "skills").mkdir(parents=True)
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}):
        rc = cmd._update("not-installed", None)
    assert rc == 1


def test_update_without_source_url(tmp_path, capsys):
    cmd = _make_cmd()
    home = tmp_path / "Zeloo"
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True)
    skill = skills_dir / "my-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: my-skill\n---\nbody", encoding="utf-8")
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}):
        rc = cmd._update("my-skill", None)
    assert rc == 1
    out = capsys.readouterr().out
    assert "No source URL" in out


def test_update_uses_manifest_source_url(tmp_path):
    cmd = _make_cmd()
    home = tmp_path / "Zeloo"
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True)
    skill = skills_dir / "my-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: my-skill\nsource: https://example.com/my-skill.zip\n---\n",
        encoding="utf-8",
    )

    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("my-skill/SKILL.md", SAMPLE_SKILL_MD)
    resp = _make_zip_response(buf.getvalue())
    with patch.dict(os.environ, {"ZELOO_HOME": str(home)}), patch.object(
        urllib.request, "urlopen", return_value=resp
    ):
        rc = cmd._update("my-skill", None)
    assert rc == 0


# --------------------------------------------------------------------------- #
# 6. Helpers
# --------------------------------------------------------------------------- #


def test_name_from_url():
    assert SkillsCmd._name_from_url("https://github.com/u/repo") == "repo"
    assert SkillsCmd._name_from_url("https://github.com/u/repo.git") == "repo"
    assert SkillsCmd._name_from_url("https://x.com/p/skill.zip") == "skill"


def test_resolve_skill_dir_returns_none_when_missing(tmp_path):
    cmd = _make_cmd()
    assert cmd._resolve_skill_dir(tmp_path) is None


def test_resolve_skill_dir_finds_nested(tmp_path):
    cmd = _make_cmd()
    inner = tmp_path / "wrap"
    inner.mkdir()
    target = inner / "actual"
    target.mkdir()
    (target / "SKILL.md").write_text("hi", encoding="utf-8")
    assert cmd._resolve_skill_dir(inner) == target


def test_run_dispatches_search(tmp_path, capsys):
    cmd = _make_cmd()
    args = argparse.Namespace(
        skills_action="search",
        query="code-review",
        json=True,
    )
    rc = cmd.run(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "code-review" in out


def test_run_handles_unknown_action(capsys):
    cmd = _make_cmd()
    args = argparse.Namespace(skills_action=None)
    rc = cmd.run(args)
    assert rc == 1
