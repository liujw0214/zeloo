"""Windows UTF-8 bootstrap for Zeloo / Hermes-style entry points.

Python on Windows has two long-standing text-encoding issues:

1. ``sys.stdout`` / ``sys.stderr`` are bound to the console code page
   (``cp1252`` on US-locale installs), so ``print("café")`` crashes with
   ``UnicodeEncodeError: 'charmap' codec can't encode character``.

2. Child processes spawned via ``subprocess`` don't know to use UTF-8
   unless ``PYTHONUTF8`` and/or ``PYTHONIOENCODING`` are set — so any
   Python subprocess inherits the same cp1252 defaults.

This module fixes both on Windows *only* — POSIX is untouched.

On Windows:
  - Sets ``PYTHONUTF8=1`` so every child process uses UTF-8 mode.
  - Sets ``PYTHONIOENCODING=utf-8`` as belt-and-suspenders.
  - Reconfigures ``sys.stdout`` / ``sys.stderr`` to UTF-8 in-place.

On POSIX: nothing — POSIX is already UTF-8 by default.

Idempotent: safe to call multiple times.  ``_bootstrap_applied`` guards
against double-reconfigure.
"""

from __future__ import annotations

import os
import sys

_IS_WINDOWS = sys.platform == "win32"
_bootstrap_applied = False

__all__ = [
    "apply_windows_utf8_bootstrap",
    "suppress_platform_ver_console",
    "harden_import_path",
    "activate_durable_lazy_target",
]


def apply_windows_utf8_bootstrap() -> bool:
    """Apply the Windows UTF-8 bootstrap if we're on Windows.

    Returns True if bootstrap was applied (i.e. we're on Windows and
    haven't already done this), False otherwise.

    Idempotent: subsequent calls after the first are a no-op.
    """
    global _bootstrap_applied

    if not _IS_WINDOWS:
        return False
    if _bootstrap_applied:
        return False

    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

    stdin = getattr(sys, "stdin", None)
    if stdin is not None:
        reconfigure = getattr(stdin, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    _bootstrap_applied = True
    return True


def suppress_platform_ver_console() -> None:
    """Stub ``platform._syscmd_ver`` on Windows — decode-crash + flash guard.

    CPython's ``platform.win32_ver()`` shells out ``cmd /c ver``.
    On PEP 540 UTF-8 mode, the OEM-code-page output raises
    UnicodeDecodeError on Python < 3.11.2.

    Stubbing ``_syscmd_ver`` to return its inputs makes ``win32_ver()``
    fall back to ``sys.getwindowsversion()`` — same data, in-process,
    no subprocess.
    """
    if not _IS_WINDOWS:
        return
    try:
        import platform

        if hasattr(platform, "_syscmd_ver"):

            def _quiet_syscmd_ver(
                system="", release="", version="", supported_platforms=("win32", "win16", "dos")
            ):
                return system, release, version

            platform._syscmd_ver = _quiet_syscmd_ver
    except Exception:
        pass


def harden_import_path(src_root: str | None = None) -> None:
    """Stop a package in the current directory from shadowing Zeloo modules.

    Python always seeds ``sys.path`` with the current directory, so launching
    from a project with its own ``utils/`` package can make
    ``from utils import ...`` resolve to the user's package and crash.

    We drop the relative forms (``""`` / ``"."``) outright, then force
    the real source root to the front of ``sys.path``.
    """
    root = src_root or os.environ.get(
        "ZELOO_PYTHON_SRC_ROOT"
    ) or os.path.dirname(os.path.abspath(__file__))

    sys.path[:] = [p for p in sys.path if p not in ("", ".")]

    root_abs = os.path.abspath(root)
    sys.path[:] = [p for p in sys.path if os.path.abspath(p) != root_abs]
    sys.path.insert(0, root)


def activate_durable_lazy_target() -> None:
    """Put the durable lazy-install dir on ``sys.path`` if one is configured.

    On immutable Docker images the agent venv is sealed and lazy installs
    are redirected to a writable dir on the data volume
    (``ZELOO_LAZY_INSTALL_TARGET``).
    Packages installed there on a previous run must be importable this run.
    """
    if not os.environ.get("ZELOO_LAZY_INSTALL_TARGET", "").strip():
        return
    try:
        from tools import lazy_deps

        lazy_deps.activate_durable_lazy_target()
    except Exception:
        pass


apply_windows_utf8_bootstrap()
suppress_platform_ver_console()
activate_durable_lazy_target()
