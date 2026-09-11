"""Lightweight PyPI version checker for Zeloo.

Used by:
- ``zeloo update --check`` (synchronous, in-process)
- ``cli._background_version_check`` (background subprocess)

Supports two release channels:
- ``stable``: Only stable releases (e.g., 0.16.0)
- ``beta``: Includes pre-releases (e.g., 0.17.0-beta.1)

Controlled by ``ZELOO_UPDATE_CHANNEL`` environment variable.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from zeloo_cli.__about__ import __version__

logger = logging.getLogger(__name__)

_PYPI_URL = "https://pypi.org/pypi/Zeloo/json"
_TIMEOUT_SECONDS = 10.0

UpdateChannel = Literal["stable", "beta"]


@dataclass
class VersionInfo:
    version: str
    channel: UpdateChannel
    release_date: str | None
    changelog_url: str | None
    is_prerelease: bool


def _get_channel() -> UpdateChannel:
    """Return the current update channel from environment.

    Defaults to ``stable``. Accepts ``stable``, ``beta``, or ``1``/``true``.
    """
    val = os.environ.get("ZELOO_UPDATE_CHANNEL", "stable").lower().strip()
    if val in ("beta", "1", "true"):
        return "beta"
    return "stable"


def _is_prerelease(version: str) -> bool:
    """Return True if version is a pre-release (alpha/beta/rc).

    Follows PEP 440: X.Y.Za1, X.Y.Zb2, X.Y.Zrc1 are pre-releases.
    """
    try:
        from packaging.version import Version
        v = Version(version)
        return v.is_prerelease
    except Exception:
        return bool(re.search(r"[a-zA-Z]|\.rc\d+$|\.alpha|\.beta", version))


def _parse_pypi_json(payload: dict) -> list[VersionInfo]:
    """Parse full PyPI JSON response into sorted VersionInfo list.

    Returns versions newest-first using semantic version comparison.
    Stable releases sort before pre-releases of the same base version.
    """
    releases = payload.get("releases") or {}
    info = payload.get("info") or {}

    results = []
    for ver, files in releases.items():
        if not files:
            continue
        release_date = None
        changelog_url = None
        for f in files:
            if release_date is None:
                release_date = f.get("upload_time")
            if changelog_url is None and f.get("url"):
                changelog_url = f.get("url")

        results.append(VersionInfo(
            version=ver,
            channel="beta" if _is_prerelease(ver) else "stable",
            release_date=release_date,
            changelog_url=changelog_url,
            is_prerelease=_is_prerelease(ver),
        ))

    def _sort_key(v: VersionInfo) -> tuple:
        try:
            from packaging.version import Version
            pv = Version(v.version)
            base = (pv.base_version or v.version, 1 if not v.is_prerelease else 0, pv)
        except Exception:
            parts = []
            for chunk in v.version.split("."):
                try:
                    parts.append((0, int(chunk)))
                except ValueError:
                    parts.append((1, chunk))
            base = (tuple(parts), 1 if not v.is_prerelease else 0, v.version)
        return base

    results.sort(key=_sort_key, reverse=True)
    return results


def _query_pypi_versions() -> list[VersionInfo] | None:
    """Fetch all Zeloo versions from PyPI JSON API.

    Returns ``None`` on error.
    """
    try:
        with urllib.request.urlopen(_PYPI_URL, timeout=_TIMEOUT_SECONDS) as resp:
            payload = json.load(resp)
        return _parse_pypi_json(payload)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.debug("PyPI JSON query failed: %s", exc)
    return None


def _get_latest_for_channel(
    versions: list[VersionInfo],
    channel: UpdateChannel,
) -> VersionInfo | None:
    """Return the latest version for the given channel."""
    for v in versions:
        if channel == "beta" or not v.is_prerelease:
            return v
    return None


def _query_pypi_latest() -> str | None:
    """Return the latest Zeloo version string from PyPI, or ``None`` on error.

    Tries the JSON API first (cheap, ~5 KB payload). Falls back to
    ``pip index versions`` only when the HTTP fetch fails — that fallback
    is slower because ``pip`` warms up a non-trivial interpreter, but it
    is more robust against local proxy / TLS quirks.
    """
    try:
        with urllib.request.urlopen(_PYPI_URL, timeout=_TIMEOUT_SECONDS) as resp:
            payload = json.load(resp)
        info = payload.get("info") or {}
        latest = info.get("version")
        if isinstance(latest, str) and latest:
            return latest
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.debug("PyPI JSON query failed: %s", exc)

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "index", "versions", "Zeloo"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "Zeloo" in line and "(" in line and ")" in line:
                    start = line.index("(") + 1
                    end = line.index(")", start)
                    candidate = line[start:end].strip()
                    if candidate:
                        return candidate
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("pip index versions fallback failed: %s", exc)

    return None


def check_latest_version(
    channel: UpdateChannel | None = None,
) -> tuple[str, str | None, UpdateChannel]:
    """Return ``(current_version, latest_version, channel)``.

    The ``latest`` half is ``None`` whenever the PyPI query fails for any
    reason — callers should treat ``None`` as "unknown" and not as an error.

    ``channel`` defaults to the ``ZELOO_UPDATE_CHANNEL`` env var, or ``stable``.
    """
    if channel is None:
        channel = _get_channel()

    versions = _query_pypi_versions()
    if versions is None:
        return (__version__, None, channel)

    latest_info = _get_latest_for_channel(versions, channel)
    if latest_info is None:
        return (__version__, None, channel)

    return (__version__, latest_info.version, channel)


def get_version_info(
    version: str,
    channel: UpdateChannel | None = None,
) -> VersionInfo | None:
    """Return detailed VersionInfo for a specific version, or ``None``."""
    if channel is None:
        channel = _get_channel()

    versions = _query_pypi_versions()
    if versions is None:
        return None

    for v in versions:
        if v.version == version:
            return v
    return None


def get_update_command(version: str) -> str:
    """Return the pip install command for a specific version."""
    return f"pip install zeloo=={version}"


def _is_newer(latest: str, current: str) -> bool:
    """Return ``True`` iff ``latest`` is strictly greater than ``current``.

    Uses PEP 440-ish comparison via :mod:`packaging.version` when available,
    falling back to a tuple-based comparison of dotted numeric segments.
    """
    if latest == current:
        return False
    try:
        from packaging.version import Version  # type: ignore

        return Version(latest) > Version(current)
    except Exception:
        # Fallback: split on dots, compare numerically where possible.
        def _parts(v: str) -> tuple:
            out = []
            for chunk in v.split("."):
                try:
                    out.append((0, int(chunk)))
                except ValueError:
                    out.append((1, chunk))
            return tuple(out)

        return _parts(latest) > _parts(current)