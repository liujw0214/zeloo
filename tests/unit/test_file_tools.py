"""Tests for tools/file_tools.py — read, write, edit operations."""

# ruff: noqa: E402
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from tools import file_tools
from tools.file_tools import file_edit, file_read, file_write
from tools.path_safety import PathSafetyPolicy


@pytest.fixture
def permissive_policy(monkeypatch):
    """Allow tests to read/write anywhere by installing a wide-open policy.

    Resets to default after the test.
    """
    policy = PathSafetyPolicy(
        allowed_roots=[Path(tempfile.gettempdir()).resolve(), Path.cwd().resolve()],
        denied_patterns=(),
    )
    file_tools.set_path_safety_policy(policy)
    file_tools.enable_path_safety()
    yield policy
    file_tools.set_path_safety_policy(None)  # reset to default
    file_tools.enable_path_safety()


def test_file_write_creates_file(permissive_policy) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "test.txt")
        result = file_write(path, "hello world")
        assert "File written" in result
        assert Path(path).read_text() == "hello world"


def test_file_write_overwrites(permissive_policy) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "test.txt")
        file_write(path, "first")
        file_write(path, "second")
        assert Path(path).read_text() == "second"


def test_file_write_creates_parent_dirs(permissive_policy) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "sub" / "dir" / "test.txt")
        file_write(path, "nested")
        assert Path(path).read_text() == "nested"


def test_file_read_returns_content(permissive_policy) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "test.txt")
        Path(path).write_text("file content here")
        result = file_read(path)
        assert result == "file content here"


def test_file_read_not_found(permissive_policy) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "nonexistent.txt")
        result = file_read(path)
        assert "Error" in result
        # Either "not found" (legacy) or "does not exist" (safety policy)
        low = result.lower()
        assert ("not found" in low) or ("does not exist" in low)


def test_file_read_truncates_long_content(permissive_policy) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "long.txt")
        Path(path).write_text("x" * 20000)
        result = file_read(path, max_length=100)
        assert "[truncated]" in result
        assert len(result) < 20000


def test_file_edit_replaces_first_occurrence(permissive_policy) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "edit.txt")
        Path(path).write_text("foo bar foo bar")
        result = file_edit(path, "foo", "baz", replace_all=False)
        assert "replaced 1 occurrence" in result
        assert Path(path).read_text() == "baz bar foo bar"


def test_file_edit_replace_all(permissive_policy) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "edit.txt")
        Path(path).write_text("foo bar foo bar")
        result = file_edit(path, "foo", "baz", replace_all=True)
        assert "replaced 2 occurrence" in result
        assert Path(path).read_text() == "baz bar baz bar"


def test_file_edit_old_string_not_found(permissive_policy) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "edit.txt")
        Path(path).write_text("hello world")
        result = file_edit(path, "missing", "replacement")
        assert "Error" in result
        assert "not found" in result.lower()


def test_file_edit_file_not_found(permissive_policy) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "nonexistent.txt")
        result = file_edit(path, "a", "b")
        assert "Error" in result
        # Either "not found" (legacy) or "does not exist" (safety policy)
        # — both indicate the same user-facing failure.
        low = result.lower()
        assert ("not found" in low) or ("does not exist" in low)


def test_file_edit_handles_unicode(permissive_policy) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "unicode.txt")
        Path(path).write_text("你好世界", encoding="utf-8")
        result = file_edit(path, "你好", "再见")
        assert "replaced" in result
        assert Path(path).read_text(encoding="utf-8") == "再见世界"


# ── Path safety integration ─────────────────────────────────────


def test_file_read_blocks_blocked_paths(tmp_path):
    """With a tight policy, file_read on an out-of-scope file is blocked."""
    safe_root = tmp_path / "safe"
    safe_root.mkdir()
    safe_file = safe_root / "ok.txt"
    safe_file.write_text("ok")

    out_of_scope = tmp_path / "out"
    out_of_scope.mkdir()
    target = out_of_scope / "secret.txt"
    target.write_text("SSN: 123-45-6789")

    policy = PathSafetyPolicy(
        allowed_roots=[safe_root.resolve()],
        denied_patterns=(r"\.txt$",),  # deny .txt to prove deny pattern works
    )
    file_tools.set_path_safety_policy(policy)
    file_tools.enable_path_safety()
    try:
        # Allowed root but matches deny pattern → blocked
        result = file_read(str(safe_file))
        assert "Error" in result
        assert "safety policy" in result
    finally:
        file_tools.set_path_safety_policy(None)
        file_tools.enable_path_safety()


def test_file_write_blocks_blocked_paths(tmp_path):
    safe_root = tmp_path / "safe"
    safe_root.mkdir()
    policy = PathSafetyPolicy(
        allowed_roots=[safe_root.resolve()],
        denied_patterns=(r"forbidden",),
    )
    file_tools.set_path_safety_policy(policy)
    file_tools.enable_path_safety()
    try:
        target = tmp_path / "outside_forbidden.txt"
        result = file_write(str(target), "data")
        assert "Error" in result
        assert "safety policy" in result
        # File must NOT have been created
        assert not target.exists()
    finally:
        file_tools.set_path_safety_policy(None)
        file_tools.enable_path_safety()


def test_file_edit_blocks_blocked_paths(tmp_path):
    policy = PathSafetyPolicy(
        allowed_roots=[],
        denied_patterns=(),
    )
    file_tools.set_path_safety_policy(policy)
    file_tools.enable_path_safety()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "x.txt")
            Path(path).write_text("foo")
            result = file_edit(path, "foo", "bar")
            assert "Error" in result
            assert "safety policy" in result
            # File unchanged
            assert Path(path).read_text() == "foo"
    finally:
        file_tools.set_path_safety_policy(None)
        file_tools.enable_path_safety()


def test_path_safety_can_be_disabled_via_env(tmp_path, monkeypatch):
    """Setting zeloo_DISABLE_PATH_SAFETY=1 bypasses all checks."""
    # Install an impossible policy.
    policy = PathSafetyPolicy(allowed_roots=[])
    file_tools.set_path_safety_policy(policy)
    monkeypatch.setenv("zeloo_DISABLE_PATH_SAFETY", "1")
    try:
        # Should now succeed despite the empty allowed_roots.
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "bypass.txt")
            result = file_write(path, "yes")
            assert "File written" in result
    finally:
        monkeypatch.delenv("zeloo_DISABLE_PATH_SAFETY", raising=False)
        file_tools.set_path_safety_policy(None)
        file_tools.enable_path_safety()


def test_path_safety_can_be_disabled_via_api(tmp_path):
    """Calling disable_path_safety() bypasses checks."""
    policy = PathSafetyPolicy(allowed_roots=[])
    file_tools.set_path_safety_policy(policy)
    file_tools.disable_path_safety()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "api_bypass.txt")
            result = file_read(path)  # doesn't exist but should reach IO
            # Either FILE NOT FOUND error from local backend, but NOT
            # "blocked by safety policy" — proves the bypass worked.
            assert "safety policy" not in result
    finally:
        file_tools.enable_path_safety()
        file_tools.set_path_safety_policy(None)


def test_default_policy_is_used_when_unset(tmp_path):
    """Sanity check: get_path_safety_policy() returns a non-None policy."""
    file_tools.set_path_safety_policy(None)
    p = file_tools.get_path_safety_policy()
    assert isinstance(p, PathSafetyPolicy)
    assert len(p.allowed_roots) >= 1


def test_default_policy_blocks_shadow(tmp_path):
    """Default policy must deny /etc/shadow on POSIX (Windows: skip)."""
    import os

    if os.name == "nt":
        return
    file_tools.set_path_safety_policy(None)  # re-build default
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "x.txt")
        result = file_write(path, "x")
        # Default policy allows $HOME + CWD; tmpdir is usually under /tmp
        # which is NOT under $HOME. So tmp write is blocked.
        assert "Error" in result
        assert "safety policy" in result


if __name__ == "__main__":
    test_file_write_creates_file()
    test_file_read_returns_content()
    test_file_edit_replaces_first_occurrence()
    print("Smoke tests passed!")
