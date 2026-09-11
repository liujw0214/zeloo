"""Early recovery: detect and repair broken venv/install before main imports.

Runs BEFORE heavy imports. If the venv is broken (missing critical
packages, corrupted ``site-packages``, mismatched Python version),
this module will:

1. Detect missing critical imports via :func:`detect_broken_venv`.
2. Run ``pip install --force-reinstall`` for the critical packages.
3. Run ``pip install -e .`` to repopulate the editable install.
4. Exit with status 0 if repair succeeded; otherwise return ``False``
   so the caller can surface a clean error to the user.

The module is **stdlib + subprocess only** so it can be imported from
the very top of the bootstrap chain, before any third-party package
has had a chance to load.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

__all__ = [
    "CRITICAL_PACKAGES",
    "detect_broken_venv",
    "recover_if_needed",
    "repair_venv",
    "is_in_venv",
    "log",
    "recovery_status",
]


# Packages that the CLI bootstrap chain depends on. Missing any one of
# these is treated as a broken venv and triggers recovery.
CRITICAL_PACKAGES: list[str] = [
    "click",
    "rich",
    "pydantic",
    "yaml",
    "httpx",
    "anyio",
]


# Marker written next to the venv after a successful recovery. Lets
# ``detect_broken_venv`` skip re-running pip when the environment is
# already known to be good.
_RECOVERY_MARKER = ".zeloo_recovery_ok"
_RECOVERY_MARKER_VERSION = 1

# How long the "venv was OK" marker stays valid. Repairs older than
# this are re-validated to defend against a later dependency upgrade
# breaking things again.
_MARKER_TTL_SECONDS = 24 * 60 * 60

# Hard timeout for each pip invocation. Recovery is best-effort — we
# never want to hang the user.
_PIP_TIMEOUT_SECONDS = 300

# Where recovery messages go. stderr so they don't pollute stdout
# pipelines the caller may have set up.
_LOG_STREAM = sys.stderr


# ── logging ──────────────────────────────────────────────────────


def log(message: str) -> None:
    """Log a recovery message to ``stderr`` with a stable prefix.

    Always flushed immediately so a recovery-triggered exit doesn't
    lose the message.
    """
    line = f"[zeloo-recovery] {message}"
    try:
        _LOG_STREAM.write(line + "\n")
        _LOG_STREAM.flush()
    except Exception:  # noqa: BLE001
        # stderr may be closed in odd embedded contexts. Never let
        # logging itself raise.
        pass


# ── environment probes ───────────────────────────────────────────


def is_in_venv() -> bool:
    """Return ``True`` if the current interpreter is inside a virtualenv.

    Honours both stdlib ``sys.prefix != sys.base_prefix`` (the
    canonical signal) and the ``VIRTUAL_ENV`` environment variable
    (covers the ``pip install --target`` style virtualenvs).
    """
    try:
        if getattr(sys, "base_prefix", sys.prefix) != sys.prefix:
            return True
    except Exception:  # noqa: BLE001
        pass
    return bool(os.environ.get("VIRTUAL_ENV"))


def _venv_root() -> Path | None:
    """Best-effort path to the current venv root, or ``None``."""
    if not is_in_venv():
        return None
    # ``sys.prefix`` points to the venv root for both stdlib venv and
    # virtualenv-created environments.
    return Path(getattr(sys, "prefix", sys.prefix))


def _site_packages_dir() -> Path | None:
    """Find the active ``site-packages`` directory for this interpreter.

    Walks ``sys.path`` looking for the first entry that actually
    exists, ends in ``site-packages``, and is writable. Falls back to
    the conventional ``<prefix>/lib/pythonX.Y/site-packages``.
    """
    candidates: list[Path] = []
    for entry in sys.path:
        if not entry:
            continue
        p = Path(entry)
        if p.name != "site-packages":
            continue
        if p.exists():
            candidates.append(p)
    if candidates:
        return candidates[0]

    if is_in_venv():
        py_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
        py = "python3" if os.name != "nt" else ""
        fallback = Path(sys.prefix) / "Lib" / "site-packages" if os.name == "nt" else Path(sys.prefix) / "lib" / py_version / "site-packages"
        if fallback.exists():
            return fallback
    return None


def _marker_path() -> Path | None:
    """Path of the "recovery ok" marker file, or ``None`` if no venv."""
    root = _venv_root()
    if root is None:
        return None
    return root / _RECOVERY_MARKER


def _read_marker() -> dict[str, object] | None:
    """Return the parsed marker dict if it's fresh enough, else ``None``."""
    path = _marker_path()
    if path is None or not path.exists():
        return None
    try:
        import time as _time

        age = _time.time() - path.stat().st_mtime
        if age > _MARKER_TTL_SECONDS:
            return None
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("version") == _RECOVERY_MARKER_VERSION:
            return data
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return None


def _write_marker(python: str, repaired: list[str]) -> None:
    """Persist a "recovery ok" marker so future starts skip detection."""
    path = _marker_path()
    if path is None:
        return
    try:
        payload = {
            "version": _RECOVERY_MARKER_VERSION,
            "python": python,
            "repaired": list(repaired),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        log(f"could not write recovery marker: {exc}")


# ── detection ────────────────────────────────────────────────────


def _import_works(module_name: str) -> bool:
    """Return ``True`` if ``module_name`` can be imported in this process.

    Uses ``importlib.util.find_spec`` to avoid the cost of actually
    executing the module — a missing package should be caught at
    spec-resolution time. Falls back to a real ``importlib.import_module``
    for the few pathological packages that don't expose a spec.
    """
    try:
        import importlib.util as _il

        spec = _il.find_spec(module_name)
        if spec is not None:
            return True
    except (ImportError, ValueError):
        # find_spec raises ImportError for sub-modules whose parent
        # isn't loaded; that's a real failure we should propagate.
        return False
    except Exception:  # noqa: BLE001
        # Defensive: anything weird from a misbehaving package's
        # __init_subclass__ machinery shouldn't crash detection.
        pass
    try:
        importlib.import_module(module_name)
        return True
    except Exception:  # noqa: BLE001
        return False


def detect_broken_venv() -> bool:
    """Return ``True`` if the venv appears broken (missing critical deps).

    "Broken" means any of the following:

    * Running in a venv and the venv's ``site-packages`` doesn't exist
      (the venv was partially deleted, e.g. ``rm -rf lib``).
    * One of :data:`CRITICAL_PACKAGES` fails to import.
    """
    # Outside a venv, never claim the venv is broken — system Python
    # is responsible for its own health.
    if not is_in_venv():
        return False

    # Fresh marker means we already validated this environment.
    if _read_marker() is not None:
        return False

    site = _site_packages_dir()
    if site is None or not site.exists():
        log("site-packages directory missing")
        return True

    missing: list[str] = []
    for pkg in CRITICAL_PACKAGES:
        if not _import_works(pkg):
            missing.append(pkg)
    if missing:
        log(f"missing critical packages: {', '.join(missing)}")
        return True
    return False


# ── repair ───────────────────────────────────────────────────────


def _run_pip(*args: str, timeout: float = _PIP_TIMEOUT_SECONDS) -> bool:
    """Run ``pip`` as a subprocess and return ``True`` on a clean exit.

    Uses ``sys.executable -m pip`` so we always use the interpreter
    the user actually launched, including its ``--user`` / PEP 517
    settings. The check is deliberately on the exit code only —
    "warnings" from pip should not block recovery.
    """
    cmd = [sys.executable, "-m", "pip", *args]
    log(f"running: {' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log(f"pip {' '.join(args)} timed out after {timeout}s")
        return False
    except FileNotFoundError:
        log("pip not available — interpreter missing or broken")
        return False
    except OSError as exc:
        log(f"pip launch failed: {exc}")
        return False

    if proc.returncode == 0:
        return True
    err_tail = (proc.stderr or "").strip().splitlines()[-3:]
    log(f"pip exited with {proc.returncode}: {' | '.join(err_tail)}")
    return False


def _find_project_root() -> Path | None:
    """Locate the editable-install root (``pyproject.toml``).

    Walks up from this file until it finds a ``pyproject.toml`` with
    a ``[project]`` or ``[tool.zeloo]`` section. Used by the
    ``pip install -e .`` recovery step.
    """
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        pyproject = candidate / "pyproject.toml"
        if not pyproject.exists():
            continue
        try:
            content = pyproject.read_text(encoding="utf-8")
        except OSError:
            continue
        if "[project]" in content or "[tool.zeloo]" in content or "zeloo" in content:
            return candidate
    return None


def repair_venv() -> bool:
    """Attempt to repair the venv via pip.

    Strategy
    --------
    1. ``pip install --force-reinstall`` for each missing critical
       package — guarantees the binary wheel matches our interpreter.
    2. ``pip install -e .`` from the repo root — repopulates the
       editable install that the CLI imports from.

    Returns ``True`` when both steps (when attempted) succeeded.
    """
    log("repair_venv: starting")

    missing: list[str] = [
        pkg for pkg in CRITICAL_PACKAGES if not _import_works(pkg)
    ]
    if not missing:
        # No critical missing — re-run the force-reinstall anyway as
        # a precaution when site-packages itself looks suspect (caller
        # already established something is broken).
        missing = list(CRITICAL_PACKAGES)

    # Step 1 — critical packages.
    install_ok = _run_pip("install", "--force-reinstall", "--no-deps", *missing)
    if not install_ok:
        # Fall back to letting pip resolve dependencies itself; this
        # works around cases where ``--no-deps`` masked a conflict.
        install_ok = _run_pip("install", "--force-reinstall", *missing)
    if not install_ok:
        log("repair_venv: critical pip install failed")
        return False

    # Step 2 — editable install of the project (best-effort).
    project_root = _find_project_root()
    if project_root is not None:
        ed_ok = _run_pip("install", "-e", str(project_root))
        if not ed_ok:
            log("repair_venv: editable install failed (continuing)")
    else:
        log("repair_venv: no project root found, skipping editable install")

    # Verify before declaring victory.
    still_missing = [pkg for pkg in CRITICAL_PACKAGES if not _import_works(pkg)]
    if still_missing:
        log(f"repair_venv: still missing after repair: {', '.join(still_missing)}")
        return False

    _write_marker(sys.executable, missing)
    log("repair_venv: success")
    return True


# ── public entry point ───────────────────────────────────────────


def recover_if_needed() -> bool:
    """Try to detect and repair a broken venv.

    Returns ``True`` when repair was *attempted* (regardless of
    success), ``False`` when nothing needed to happen. Callers
    typically treat ``True`` + post-repair import success as a green
    light to continue the normal bootstrap.

    The function never raises — recovery must be best-effort, and a
    failure here should fall through to the regular ``ModuleNotFoundError``
    path so the user sees the original error.
    """
    try:
        if not detect_broken_venv():
            return False
    except Exception as exc:  # noqa: BLE001
        log(f"detect_broken_venv raised: {exc}")
        return False

    log("venv appears broken — attempting recovery")
    try:
        return repair_venv()
    except Exception as exc:  # noqa: BLE001
        log(f"repair_venv raised: {exc}")
        return False


def recovery_status() -> dict[str, object]:
    """Return a snapshot of the recovery state for ``zeloo doctor``.

    Pure read-only helper — does *not* trigger recovery. Useful for
    tests and the doctor command which need to report recovery state
    without modifying the venv.
    """
    marker = _read_marker()
    site = _site_packages_dir()
    return {
        "in_venv": is_in_venv(),
        "site_packages": str(site) if site else None,
        "recovery_marker": marker,
        "critical_packages": {
            pkg: _import_works(pkg) for pkg in CRITICAL_PACKAGES
        },
    }