"""Tests for the profile management system."""

# ruff: noqa: E402
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from zeloo_cli import profiles as profiles_mod
from zeloo_cli.profiles import (
    activate_profile,
    create_profile,
    delete_profile,
    get_active_profile_name,
    list_profiles,
)


def _make_tmp_profiles_root() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="Zeloo-profiles-test-"))
    (tmp / "profiles").mkdir(parents=True, exist_ok=True)
    return tmp


# ── list_profiles ────────────────────────────────────────────────────


def test_list_profiles_includes_default_when_empty():
    tmp = _make_tmp_profiles_root()
    with patch.object(profiles_mod, "get_profiles_root", return_value=tmp / "profiles"):
        assert list_profiles() == ["default"]


def test_list_profiles_lists_created():
    tmp = _make_tmp_profiles_root()
    (tmp / "profiles" / "alpha").mkdir()
    (tmp / "profiles" / "beta").mkdir()
    with patch.object(profiles_mod, "get_profiles_root", return_value=tmp / "profiles"):
        result = list_profiles()
    assert "default" in result
    assert "alpha" in result
    assert "beta" in result


# ── create_profile ───────────────────────────────────────────────────


def test_create_profile_makes_subdirs():
    tmp = _make_tmp_profiles_root()
    with patch.object(profiles_mod, "get_profile_dir", return_value=tmp / "profiles" / "newp"):
        path = create_profile("newp")
    assert path.is_dir()
    assert (path / "skills").is_dir()
    assert (path / "memories").is_dir()
    assert (path / "trajectories").is_dir()


def test_create_profile_rejects_invalid_name():
    try:
        create_profile("bad name!")
        raise AssertionError("Expected ValueError")
    except ValueError:
        pass


def test_create_profile_rejects_duplicate():
    tmp = _make_tmp_profiles_root()
    (tmp / "profiles" / "dup").mkdir()
    with patch.object(profiles_mod, "get_profile_dir", return_value=tmp / "profiles" / "dup"):
        try:
            create_profile("dup")
            raise AssertionError("Expected FileExistsError")
        except FileExistsError:
            pass


def test_create_profile_copies_config_from_source():
    tmp = _make_tmp_profiles_root()
    src = tmp / "profiles" / "src"
    src.mkdir()
    (src / "config.yaml").write_text("model: gpt-4o\n")

    newp = tmp / "profiles" / "dest"

    def fake_profile_dir(name: str) -> Path:
        return tmp / "profiles" / name

    with patch.object(profiles_mod, "get_profile_dir", side_effect=fake_profile_dir):
        create_profile("dest", copy_from="src")

    assert (newp / "config.yaml").read_text() == "model: gpt-4o\n"


# ── activate_profile ─────────────────────────────────────────────────


def test_activate_profile_sets_home_override():
    tmp = _make_tmp_profiles_root()
    pdir = tmp / "profiles" / "myprof"
    pdir.mkdir()
    with patch.object(profiles_mod, "get_profile_dir", return_value=pdir):
        with patch.object(profiles_mod, "set_zeloo_home_override") as mock_set:
            activate_profile("myprof")
    mock_set.assert_called_once_with(str(pdir))


def test_activate_profile_sets_env_var():
    tmp = _make_tmp_profiles_root()
    pdir = tmp / "profiles" / "myprof"
    pdir.mkdir()
    with patch.object(profiles_mod, "get_profile_dir", return_value=pdir):
        with patch.object(profiles_mod, "set_zeloo_home_override"):
            activate_profile("myprof")
    assert os.environ.get("zeloo_HOME") == str(pdir)


def test_activate_profile_raises_on_missing():
    tmp = _make_tmp_profiles_root()
    with patch.object(profiles_mod, "get_profile_dir", return_value=tmp / "profiles" / "nope"):
        try:
            activate_profile("nope")
            raise AssertionError("Expected FileNotFoundError")
        except FileNotFoundError:
            pass


# ── delete_profile ───────────────────────────────────────────────────


def test_delete_profile_removes_directory():
    tmp = _make_tmp_profiles_root()
    pdir = tmp / "profiles" / "todelete"
    pdir.mkdir()
    with patch.object(profiles_mod, "get_profile_dir", return_value=pdir):
        delete_profile("todelete")
    assert not pdir.exists()


def test_delete_profile_rejects_default():
    try:
        delete_profile("default")
        raise AssertionError("Expected ValueError")
    except ValueError:
        pass


def test_delete_profile_raises_on_missing():
    tmp = _make_tmp_profiles_root()
    with patch.object(profiles_mod, "get_profile_dir", return_value=tmp / "profiles" / "ghost"):
        try:
            delete_profile("ghost")
            raise AssertionError("Expected FileNotFoundError")
        except FileNotFoundError:
            pass


# ── get_active_profile_name ──────────────────────────────────────────


def test_get_active_profile_name_default_when_outside_profiles():
    with patch.object(
        profiles_mod, "get_zeloo_home", return_value=Path("/some/other/path")
    ):
        with patch.object(
            profiles_mod, "get_profiles_root", return_value=Path("/home/.Zeloo/profiles")
        ):
            assert get_active_profile_name() == "default"


if __name__ == "__main__":
    test_list_profiles_includes_default_when_empty()
    test_list_profiles_lists_created()
    test_create_profile_makes_subdirs()
    test_create_profile_rejects_invalid_name()
    test_create_profile_rejects_duplicate()
    test_create_profile_copies_config_from_source()
    test_activate_profile_sets_home_override()
    test_activate_profile_sets_env_var()
    test_activate_profile_raises_on_missing()
    test_delete_profile_removes_directory()
    test_delete_profile_rejects_default()
    test_delete_profile_raises_on_missing()
    test_get_active_profile_name_default_when_outside_profiles()
    print("All profiles tests passed!")
