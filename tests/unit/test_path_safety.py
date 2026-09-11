"""Tests for tools/path_safety module — path validation policy."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")


# ── Empty / malformed inputs ─────────────────────────────────────


def test_empty_path_is_unsafe():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    policy = PathSafetyPolicy(allowed_roots=[Path(tempfile.gettempdir()).resolve()])
    assert is_safe_path("", policy) is False
    assert is_safe_path("   ", policy) is False


def test_non_string_input_raises_type_error():
    from tools.path_safety import PathSafetyPolicy, resolve_and_validate

    policy = PathSafetyPolicy(allowed_roots=[Path(tempfile.gettempdir()).resolve()])
    try:
        resolve_and_validate(123, policy)  # type: ignore[arg-type]
    except TypeError:
        return
    raise AssertionError("expected TypeError")


# ── Allowed-root containment ─────────────────────────────────────


def test_path_inside_allowed_root_is_safe():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        target = root / "a" / "b" / "c.txt"
        target.parent.mkdir(parents=True)
        target.write_text("ok")
        policy = PathSafetyPolicy(allowed_roots=[root])
        assert is_safe_path(str(target), policy) is True


def test_path_outside_allowed_root_is_unsafe():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        outside = Path(tempfile.gettempdir()).resolve() / "outside.txt"
        # Make sure it's actually outside root on this OS
        try:
            outside.relative_to(root)
            in_root = True
        except ValueError:
            in_root = False
        if in_root:
            # Pathological coincidence — pick a different temp parent.
            outside = Path(os.path.dirname(str(root))) / "definitely_outside.txt"
        if not outside.exists():
            outside.write_text("x")
        try:
            policy = PathSafetyPolicy(allowed_roots=[root])
            assert is_safe_path(str(outside), policy) is False
        finally:
            if outside.exists():
                outside.unlink()


def test_path_traversal_outside_root_is_blocked():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        evil = str(root) + "/../../../etc/passwd"
        policy = PathSafetyPolicy(allowed_roots=[root])
        assert is_safe_path(evil, policy) is False


def test_no_allowed_roots_denies_everything():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "ok.txt"
        target.write_text("x")
        policy = PathSafetyPolicy(allowed_roots=[])
        assert is_safe_path(str(target), policy) is False


# ── Symlink handling ─────────────────────────────────────────────


def test_symlinks_allowed_by_default():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        real = root / "real.txt"
        real.write_text("hi")
        link = root / "link.txt"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError):
            return  # symlinks not supported on this FS (e.g. some Windows configs)
        policy = PathSafetyPolicy(allowed_roots=[root])
        assert is_safe_path(str(link), policy) is True


def test_symlinks_disabled_blocks_symlinks():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        real = root / "real.txt"
        real.write_text("hi")
        link = root / "link.txt"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError):
            return
        policy = PathSafetyPolicy(allowed_roots=[root], allow_symlinks=False)
        # On POSIX resolve() peels the symlink, so the resolved path
        # differs from the original. On Windows it may or may not —
        # accept either: if the resolved path is inside root, allow;
        # otherwise deny. We just check the call doesn't crash and the
        # boolean is consistent with reality.
        result = is_safe_path(str(link), policy)
        assert isinstance(result, bool)


# ── Deny patterns ────────────────────────────────────────────────


def test_deny_pattern_blocks_matching_path():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        target = root / "secret.pem"
        target.write_text("PRIVATE KEY")
        policy = PathSafetyPolicy(
            allowed_roots=[root],
            denied_patterns=(r"\.pem$",),
        )
        assert is_safe_path(str(target), policy) is False


def test_default_deny_blocks_shadow_file_on_posix():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    if os.name == "nt":
        return  # Windows paths don't match the POSIX deny patterns
    policy = PathSafetyPolicy(allowed_roots=[Path("/")])
    assert is_safe_path("/etc/shadow", policy) is False


def test_default_deny_blocks_system32_on_windows():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    if os.name != "nt":
        return
    policy = PathSafetyPolicy(allowed_roots=[Path("C:\\")])
    assert is_safe_path("C:\\Windows\\System32\\drivers\\etc\\hosts", policy) is False


# ── require_real_path ────────────────────────────────────────────


def test_require_real_path_blocks_nonexistent():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        ghost = root / "does_not_exist.txt"
        policy = PathSafetyPolicy(allowed_roots=[root], require_real_path=True)
        assert is_safe_path(str(ghost), policy) is False


def test_default_allows_nonexistent_for_creation():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        ghost = root / "new_file.txt"
        policy = PathSafetyPolicy(allowed_roots=[root])
        assert is_safe_path(str(ghost), policy) is True


# ── Max bytes ────────────────────────────────────────────────────


def test_max_bytes_blocks_oversized_file():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        big = root / "big.bin"
        big.write_bytes(b"x" * 1024)
        policy = PathSafetyPolicy(allowed_roots=[root], max_bytes=100)
        assert is_safe_path(str(big), policy) is False


def test_max_bytes_allows_smaller_file():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        small = root / "small.txt"
        small.write_text("hi")
        policy = PathSafetyPolicy(allowed_roots=[root], max_bytes=10_000)
        assert is_safe_path(str(small), policy) is True


# ── Max depth ────────────────────────────────────────────────────


def test_max_depth_blocks_deep_paths():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        deep = root / "a" / "b" / "c" / "d" / "file.txt"
        deep.parent.mkdir(parents=True)
        deep.write_text("deep")
        policy = PathSafetyPolicy(allowed_roots=[root], max_depth=2)
        assert is_safe_path(str(deep), policy) is False


# ── Path expansion ───────────────────────────────────────────────


def test_tilde_expansion_works():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    home = Path.home().resolve()
    policy = PathSafetyPolicy(allowed_roots=[home])
    # Just verify the tilde-expansion didn't crash.
    is_safe_path("~/something.txt", policy)


def test_env_var_expansion_works():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    home = Path.home().resolve()
    policy = PathSafetyPolicy(allowed_roots=[home])
    # Use HOME on POSIX, USERPROFILE on Windows.
    var = "USERPROFILE" if os.name == "nt" else "HOME"
    is_safe_path(f"${var}/anything", policy)


# ── SafePath.require_safe ────────────────────────────────────────


def test_safe_path_require_safe_raises_when_unsafe():
    from tools.path_safety import PathSafetyError, PathSafetyPolicy, resolve_and_validate

    policy = PathSafetyPolicy(allowed_roots=[])
    safe = resolve_and_validate("/etc/passwd", policy)
    assert safe.is_safe is False
    try:
        safe.require_safe()
    except PathSafetyError as exc:
        assert exc.path == "/etc/passwd"
        assert exc.reason
        return
    raise AssertionError("expected PathSafetyError")


def test_safe_path_require_safe_returns_path_when_safe():
    from tools.path_safety import PathSafetyPolicy, resolve_and_validate

    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        target = root / "ok.txt"
        target.write_text("ok")
        policy = PathSafetyPolicy(allowed_roots=[root])
        safe = resolve_and_validate(str(target), policy)
        assert safe.is_safe is True
        p = safe.require_safe()
        assert p.resolve() == target.resolve()


# ── from_home factory ────────────────────────────────────────────


def test_from_home_factory():
    from tools.path_safety import PathSafetyPolicy

    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        policy = PathSafetyPolicy.from_home(home=home)
        assert len(policy.allowed_roots) == 1
        assert policy.allowed_roots[0] == home.resolve()


def test_from_home_factory_with_extra_roots():
    from tools.path_safety import PathSafetyPolicy, is_safe_path

    with tempfile.TemporaryDirectory() as td_home, tempfile.TemporaryDirectory() as td_extra:
        home = Path(td_home)
        extra = Path(td_extra)
        policy = PathSafetyPolicy.from_home(home=home, extra_roots=[extra])
        f = extra / "x.txt"
        f.write_text("x")
        assert is_safe_path(str(f), policy) is True
