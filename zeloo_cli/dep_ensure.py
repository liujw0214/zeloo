"""Zeloo dependency bootstrap — borrowed design from Hermes Agent.

This module is the **single source of truth** for "which non-Python tools
does Zeloo need, and how do we get them?" Both the PowerShell / Bash
installers and the runtime ``zeloo doctor`` / CLI bootstrap call into it.

Design (mirrors Hermes ``hermes_cli/dep_ensure.py``):

* Lazy by default — never blocks the user with prompts unless they ask
  for the feature that needs the dep.
* TTY-aware — in headless contexts (SSH / Docker / cron / CI) we skip
  the interactive prompt and return ``False`` so the calling code can
  raise a clear error instead of hanging.
* Install-method aware — we look up the install script that matches
  the platform + install method (git installer vs pip wheel) and shell
  out to it with ``--ensure <dep>``.
* Idempotent — calling :func:`ensure_dependency` for an already-present
  binary is a no-op (no install, no prompt).

Public surface
--------------

* :data:`KNOWN_DEPS` — dict of dep-name → ``DepSpec`` with install hints
* :func:`ensure_dependency` — entry point used by runtime code
* :func:`is_available` — pure check, no install
* :func:`missing_required` — list of deps the active profile needs but
  are not installed
* :func:`find_install_script` — returns ``(path, kind)`` for the
  active install method
"""
from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


# ── platform helpers ──────────────────────────────────────────────


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _is_macos() -> bool:
    return platform.system() == "Darwin"


# ── dependency spec ──────────────────────────────────────────────


@dataclass(frozen=True)
class DepSpec:
    """Static description of one external tool Zeloo can use."""

    name: str
    """The dep name as referenced from CLI / config (e.g. ``"ripgrep"``)."""

    binary: str
    """Binary name looked up via :func:`shutil.which`."""

    purpose: str
    """Human-readable one-liner shown in prompts / ``zeloo doctor``."""

    install_hint: str = ""
    """Hint string shown to the user when the dep is missing and we can't
    auto-install. Defaults to ``pip install`` or package-manager snippet."""

    optional: bool = False
    """When ``True``, ``missing_required`` will not include this dep."""

    package_check: tuple[str, ...] = field(default_factory=tuple)
    """Alternative binary names — any of them being on PATH means the dep
    is considered present (e.g. ``rg`` vs ``ripgrep``)."""


KNOWN_DEPS: dict[str, DepSpec] = {
    "ripgrep": DepSpec(
        name="ripgrep",
        binary="rg",
        purpose="Fast file search (used by tools.cron_tool, knowledge search).",
        install_hint=(
            "winget install BurntSushi.ripgrep  # Windows\n"
            "  brew install ripgrep                # macOS\n"
            "  apt install ripgrep                 # Debian/Ubuntu"
        ),
        package_check=("rg",),
    ),
    "ffmpeg": DepSpec(
        name="ffmpeg",
        binary="ffmpeg",
        purpose="Audio format conversion for TTS / voice messages.",
        optional=True,
        install_hint=(
            "winget install Gyan.FFmpeg           # Windows\n"
            "  brew install ffmpeg                 # macOS\n"
            "  apt install ffmpeg                  # Debian/Ubuntu"
        ),
    ),
    "git": DepSpec(
        name="git",
        binary="git",
        purpose="Git operations (terminal tool, skill cloning, worktrees).",
        optional=True,
        install_hint=(
            "winget install Git.Git               # Windows\n"
            "  brew install git                    # macOS\n"
            "  apt install git                     # Debian/Ubuntu"
        ),
    ),
    "node": DepSpec(
        name="node",
        binary="node",
        purpose="Browser tool (agent-browser) and the Web Chat bridge.",
        optional=True,
        install_hint=(
            "winget install OpenJS.NodeJS.LTS     # Windows\n"
            "  brew install node                   # macOS"
        ),
    ),
    "uv": DepSpec(
        name="uv",
        binary="uv",
        purpose="Fast Python package manager (used by the installer).",
        install_hint=(
            "irm https://astral.sh/uv/install.ps1 | iex   # Windows\n"
            "  curl -LsSf https://astral.sh/uv/install.sh | sh  # macOS/Linux"
        ),
    ),
    "bash": DepSpec(
        name="bash",
        binary="bash",
        purpose="Shell tool backend (Windows users get PortableGit).",
        optional=True,
        install_hint=(
            "Install Git for Windows: winget install Git.Git"
        ),
    ),
}


# ── pure checks ─────────────────────────────────────────────────


def is_available(dep_name: str) -> bool:
    """Return ``True`` when *any* of the dep's binaries is on PATH.

    No install is attempted. Safe to call from any context, including
    headless / non-interactive runs.
    """
    spec = KNOWN_DEPS.get(dep_name)
    if spec is None:
        return False
    for binary in (spec.binary, *spec.package_check):
        if shutil.which(binary) is not None:
            return True
    return False


def missing_required(*dep_names: str) -> list[str]:
    """Return the subset of *dep_names* that are NOT installed."""
    return [d for d in dep_names if not is_available(d)]


# ── install-script discovery ──────────────────────────────────────


InstallKind = Literal["git", "pip"]


def _read_install_method_marker(home: Path) -> InstallKind | None:
    """Read ``~/.zeloo/.install_method`` written by install.ps1 / install.sh.

    Returns ``"git"`` when the user ran the git installer, ``"pip"`` when
    they ran ``pip install zeloo``, or ``None`` when unknown / missing.
    """
    marker = home / ".install_method"
    if not marker.exists():
        return None
    try:
        return marker.read_text(encoding="utf-8").strip().lower() or None  # type: ignore[return-value]
    except OSError:
        return None


def _zeloo_home() -> Path:
    """Return the active Zeloo home directory."""
    from agent.zeloo_constants import get_zeloo_home

    return Path(get_zeloo_home())


def find_install_script(
    home: Path | None = None,
    kind: InstallKind | None = None,
) -> tuple[Path | None, InstallKind | None]:
    """Locate the install script that matches the active install method.

    Returns ``(path, kind)``. ``path`` is ``None`` when no script could
    be found (e.g. the user installed via ``pip install`` and the wheel
    doesn't include install scripts — they need to fetch them from
    the GitHub repo manually).
    """
    home = home or _zeloo_home()
    kind = kind or _read_install_method_marker(home)

    # Probe 1: install scripts bundled alongside the active checkout
    # (git installer puts them at the repo root). We walk up from this
    # module until we find install.ps1 / install.sh.
    if kind in (None, "git"):
        repo_root = _find_repo_root()
        if repo_root is not None:
            candidate = (
                repo_root / "install.ps1" if _is_windows()
                else repo_root / "install.sh"
            )
            if candidate.exists():
                return candidate, kind or "git"

    # Probe 2: pip-wheel path — scripts not bundled, must be fetched
    # from GitHub raw. We return a synthetic URL-based marker so the
    # caller can decide whether to fetch or surface a hint.
    if kind == "pip":
        return None, "pip"

    return None, kind


def _find_repo_root() -> Path | None:
    """Walk up from this file looking for a git checkout root."""
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / "cli.py").exists() and (candidate / "zeloo_cli").exists():
            return candidate
    return None


# ── interactive helpers ─────────────────────────────────────────


def _stdin_isatty() -> bool:
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except Exception:  # noqa: BLE001
        return False


def _is_headless_context(argv: list[str] | None = None) -> bool:
    """Return True when running where we should never prompt.

    gateway / cron / doctor are all "no TTY" entry points where an
    interactive ``Install? [Y/n]`` would hang forever.
    """
    argv = list(argv if argv is not None else sys.argv)
    headless_subcommands = {
        "gateway", "cron", "doctor",
    }
    for token in argv:
        if token in headless_subcommands:
            return True
        # `--non-interactive` / `-y` from anywhere short-circuits
        if token in ("--non-interactive", "--yes", "-y"):
            return True
    return not _stdin_isatty()


def _prompt_yes_no(question: str, default: bool = True) -> bool:
    """Single-line Y/n prompt. Falls back to ``default`` on EOF / SIGINT."""
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        raw = input(f"{question} {suffix}: ").strip().lower()
    except (EOFError, KeyboardInterrupt, OSError):
        return default
    if not raw:
        return default
    return raw in ("y", "yes")


# ── install dispatch ────────────────────────────────────────────


def _run_install_script(script: Path, dep_name: str, kind: InstallKind) -> bool:
    """Invoke the install script's ``--ensure`` / ``-Ensure`` entry point."""
    cmd: list[str]
    if _is_windows():
        # PowerShell entry point — matches ``install.ps1 -Ensure <dep>``.
        cmd = [
            "powershell", "-ExecutionPolicy", "Bypass", "-NoProfile",
            "-File", str(script), "-Ensure", dep_name,
        ]
    else:
        cmd = ["bash", str(script), "--ensure", dep_name]

    logger.info("Bootstrapping %s via %s …", dep_name, " ".join(cmd))
    try:
        result = subprocess.run(
            cmd, check=False, capture_output=True, text=True,
            timeout=600,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("Install dispatch failed: %s", exc)
        return False

    if result.returncode != 0:
        logger.warning(
            "Install script returned %d for %s.\nstderr:\n%s",
            result.returncode, dep_name, (result.stderr or "").strip(),
        )
        return False

    # Re-check after install — most installers put the binary on PATH
    # for the *current* shell only, so the next probe is the source of
    # truth.
    return is_available(dep_name)


# ── public entry point ──────────────────────────────────────────


def ensure_dependency(
    dep_name: str,
    *,
    interactive: bool = True,
    argv: list[str] | None = None,
) -> bool:
    """Return ``True`` when *dep_name* is on PATH (installing if needed).

    Parameters
    ----------
    dep_name
        Key into :data:`KNOWN_DEPS`.
    interactive
        When ``False``, skip the prompt and only auto-install when an
        install script can be found. Useful for ``zeloo doctor --fix``.
    argv
        Override ``sys.argv`` for headless detection. Tests pass this.
    """
    spec = KNOWN_DEPS.get(dep_name)
    if spec is None:
        raise KeyError(f"Unknown dependency: {dep_name!r}")

    if is_available(dep_name):
        return True

    headless = _is_headless_context(argv)

    # ── 1. If we have an install script, run it (works in headless too).
    script, kind = find_install_script()
    if script is not None and kind in ("git", "pip"):
        return _run_install_script(script, dep_name, kind)

    # ── 2. No install script available → maybe prompt (interactive only).
    if headless or not interactive:
        # Surface a clean error so the calling code can render it nicely.
        logger.warning(
            "Missing required dep %s and no installer available.\n%s",
            dep_name, spec.install_hint,
        )
        return False

    if not _prompt_yes_no(
        f"{spec.name} ({spec.purpose}) is not installed. Install now?",
        default=True,
    ):
        logger.info("User declined to install %s", dep_name)
        return False

    # We promised the user we'd install — try the script first, then
    # surface the manual hint if even that fails.
    if script is not None:
        if _run_install_script(script, dep_name, kind or "git"):
            return True

    print(spec.install_hint)
    return False


# ── doctor integration ──────────────────────────────────────────


def doctor_report(*, include_optional: bool = True) -> dict[str, dict[str, object]]:
    """Return a structured "what's installed / what's missing" report.

    Used by :mod:`zeloo_cli.subcommands.doctor` and the install repair
    command to render a one-screen status table.
    """
    report: dict[str, dict[str, object]] = {}
    for name, spec in KNOWN_DEPS.items():
        if spec.optional and not include_optional:
            continue
        report[name] = {
            "available": is_available(name),
            "purpose": spec.purpose,
            "binary": spec.binary,
            "optional": spec.optional,
        }
    return report


# ── install-method stamping ─────────────────────────────────────


def stamp_install_method(
    kind: InstallKind,
    *,
    home: Path | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    """Persist the install method so future dep_ensure calls can find the script.

    Writes a tiny JSON file at ``~/.zeloo/.install_method`` containing
    both the kind and the extra metadata (e.g. commit SHA, ref). The
    marker is also a useful breadcrumb when an end-user opens a ticket.
    """
    home = home or _zeloo_home()
    marker = home / ".install_method"
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"kind": kind}
    if extra:
        payload.update(extra)
    marker.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_install_marker(home: Path | None = None) -> dict[str, object]:
    """Read the install-method marker written by :func:`stamp_install_method`."""
    home = home or _zeloo_home()
    marker = home / ".install_method"
    if not marker.exists():
        return {}
    try:
        result = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return result if isinstance(result, dict) else {}


__all__ = [
    "DepSpec",
    "KNOWN_DEPS",
    "InstallKind",
    "ensure_dependency",
    "is_available",
    "missing_required",
    "doctor_report",
    "find_install_script",
    "stamp_install_method",
    "read_install_marker",
]
