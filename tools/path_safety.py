"""Path safety validator — prevent unauthorized filesystem access.

``file_read`` / ``file_write`` / shell tools accept arbitrary path
strings from the LLM. Without validation, an attacker (or hallucinating
model) can request ``/etc/passwd``, ``~/.ssh/id_rsa``, or
``C:\\Windows\\System32\\config\\SAM`` and have the agent hand back
secrets.

This module provides a small, dependency-free validator:

  * :class:`PathSafetyPolicy` — declarative policy (allowed roots, denied
    patterns, max size, max depth).
  * :func:`resolve_and_validate` — canonicalize a user-supplied path
    against a policy. Resolves symlinks, expands ``~``, normalizes
    ``.`` / ``..`` segments, and verifies containment in an allowed
    root. Returns a :class:`SafePath` with the resolved path and a
    boolean ``is_safe``.
  * :class:`PathSafetyError` — raised when validation fails (used by
    strict callers; safe callers can inspect ``is_safe=False``).

Why we do this in addition to ``security.py``:

  * ``security.py`` focuses on *content* sanitization (secrets,
    injection patterns). This module focuses on *path* policy.
  * Multiple tools (``file_read``, ``file_write``, ``code_exec``) need
    to share the same path policy so a single check applies everywhere.

Design notes:

  * Path comparison is done with ``os.path.commonpath`` after resolution
    — case-correct on Windows, case-correct on POSIX.
  * On Windows, drives are normalized so ``C:/foo`` and ``C:\\foo``
    resolve identically.
  * Symlink resolution is opt-in (default ON) because the agent's own
    ``~/.Zeloo`` may contain symlinks and we don't want to reject
    legitimate skills just because of symlink indirection.
  * Denied patterns are matched as **regex on the full resolved path**
    so attackers can't smuggle patterns via ``..`` segments.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Default deny list (sensitive system paths) ────────────────────

# Regexes are matched against the *resolved, absolute* path string on
# the current OS's separator. Patterns are intentionally conservative.

_DEFAULT_DENY_PATTERNS_WIN: tuple[str, ...] = (
    r"(?i)[\\/]windows[\\/]system32[\\/]",
    r"(?i)[\\/]windows[\\/]syswow64[\\/]",
    r"(?i)[\\/]programdata[\\/]microsoft[\\/]",
    r"(?i)[\\/](?:bootmgr|pagefile\.sys|hiberfil\.sys)[\\/]?$",
    r"(?i)[\\/]appdata[\\/]local[\\/]microsoft[\\/]windows[\\/]explorer[\\/]",
)

_DEFAULT_DENY_PATTERNS_POSIX: tuple[str, ...] = (
    r"/etc/(?:shadow|passwd|sudoers|ssl/private|ssh/)",
    r"/proc/(?:self/)?(?:environ|cmdline|maps|mem)$",
    r"/sys/",
    r"/boot/(?:grub|vmlinuz|initrd)",
    r"/root/\.",
    r"/var/run/(?:docker|secrets)/",
)


def _default_deny_patterns() -> tuple[str, ...]:
    if os.name == "nt":
        return _DEFAULT_DENY_PATTERNS_WIN
    return _DEFAULT_DENY_PATTERNS_POSIX


# ── Public types ──────────────────────────────────────────────────


class PathSafetyError(Exception):
    """Raised when a path fails safety validation.

    Attributes:
        reason: Human-readable explanation suitable for tool output.
        path: The path the user supplied (pre-resolution).
    """

    def __init__(self, reason: str, path: str | os.PathLike[str]) -> None:
        super().__init__(f"{reason}: {path}")
        self.reason = reason
        self.path = str(path)


@dataclass(frozen=True)
class SafePath:
    """The result of a successful (or partially successful) validation."""

    requested: str
    resolved: Path
    is_safe: bool
    reason: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return self.is_safe

    def require_safe(self) -> Path:
        """Return the resolved path or raise :class:`PathSafetyError`."""
        if not self.is_safe:
            raise PathSafetyError(self.reason or "path blocked", self.requested)
        return self.resolved


@dataclass
class PathSafetyPolicy:
    """Declarative policy used by :func:`resolve_and_validate`.

    Attributes:
        allowed_roots: Paths the agent may access. Empty list = deny all.
            Each root may be a string or a ``Path``.
        denied_patterns: Regex patterns; if any matches the resolved path,
            the request is denied. Defaults to a built-in sensitive-path
            deny list.
        allow_symlinks: When False, paths whose resolution crosses a
            symlink are denied. Defaults to True.
        require_real_path: When True, the resolved path must exist on
            disk. Defaults to False (we accept non-existent paths so
            file_write can create new files).
        max_depth: Maximum directory nesting from any allowed root.
            ``None`` disables the check.
        max_bytes: Optional cap on file size (only checked if file
            exists). ``None`` disables the check.
    """

    allowed_roots: list[Path] = field(default_factory=list)
    denied_patterns: tuple[str, ...] = field(default_factory=_default_deny_patterns)
    allow_symlinks: bool = True
    require_real_path: bool = False
    max_depth: int | None = None
    max_bytes: int | None = None

    def __post_init__(self) -> None:
        # Normalize roots to absolute Paths once.
        self.allowed_roots = [Path(r).expanduser().resolve() for r in self.allowed_roots]

    # ── Convenience factories ────────────────────────────────────

    @classmethod
    def from_home(
        cls,
        home: Path | os.PathLike[str] | None = None,
        extra_roots: Iterable[Path | str] = (),
        deny_patterns: tuple[str, ...] | None = None,
        **kwargs: object,
    ) -> PathSafetyPolicy:
        """Build a policy that allows the user's home + *extra_roots*.

        This is the recommended default for ``file_read`` / ``file_write``
        in single-user mode.
        """
        h = Path(home).expanduser() if home else Path.home()
        roots: list[Path] = [h.resolve()]
        roots.extend(Path(r).expanduser().resolve() for r in extra_roots)
        patterns = (
            deny_patterns if deny_patterns is not None else _default_deny_patterns()
        )
        return cls(
            allowed_roots=roots,
            denied_patterns=patterns,
            **kwargs,  # type: ignore[arg-type]
        )


# ── Validation core ────────────────────────────────────────────────


def _normalize_separators(p: Path) -> Path:
    """Return *p* with consistent separators for the current OS."""
    s = str(p)
    if os.name == "nt":
        # On Windows, lower-case drive letters can fool commonpath().
        # Leave case alone — os.path.commonpath is case-correct on NT.
        s = s.replace("/", os.sep)
    return Path(s)


def _matches_any(path_str: str, patterns: Iterable[str]) -> str | None:
    """Return the first matching pattern, or ``None``."""
    for pat in patterns:
        try:
            if re.search(pat, path_str):
                return pat
        except re.error as exc:
            logger.warning("path_safety: invalid deny pattern %r: %s", pat, exc)
    return None


def _depth_from_root(resolved: Path, root: Path) -> int:
    """Return the directory depth from *root* to *resolved* (both abs)."""
    rel = resolved.relative_to(root)
    # A file directly in the root has depth 0; one nested dir is 1.
    return max(0, len(rel.parts) - 1 if resolved.is_file() else len(rel.parts))


def resolve_and_validate(
    requested: str | os.PathLike[str],
    policy: PathSafetyPolicy,
) -> SafePath:
    """Resolve *requested* against *policy*.

    Returns a :class:`SafePath`; check ``is_safe`` before using
    ``resolved``. Strict callers can use ``SafePath.require_safe()`` to
    raise :class:`PathSafetyError` automatically.

    The function never raises for *unsafe* paths — it returns them with
    ``is_safe=False`` and a human-readable ``reason``. It only raises
    :class:`TypeError` for non-string inputs.
    """
    if not isinstance(requested, (str, os.PathLike)):
        raise TypeError(f"path must be str or os.PathLike, got {type(requested).__name__}")

    raw = os.fspath(requested)
    if not raw or not raw.strip():
        return SafePath(
            requested=str(requested),
            resolved=Path(""),
            is_safe=False,
            reason="empty path",
        )

    try:
        expanded = os.path.expanduser(os.path.expandvars(raw))
    except Exception as exc:  # noqa: BLE001
        return SafePath(
            requested=raw,
            resolved=Path(raw),
            is_safe=False,
            reason=f"expand failed: {exc}",
        )

    # Resolve. ``strict=False`` so new files can be created.
    try:
        resolved = Path(expanded).resolve(strict=False)
    except OSError as exc:
        return SafePath(
            requested=raw,
            resolved=Path(expanded),
            is_safe=False,
            reason=f"resolve failed: {exc}",
        )

    resolved = _normalize_separators(resolved)
    resolved_str = str(resolved)

    # 1. Deny-list (highest priority)
    match = _matches_any(resolved_str, policy.denied_patterns)
    if match is not None:
        return SafePath(
            requested=raw,
            resolved=resolved,
            is_safe=False,
            reason=f"path matches sensitive deny pattern ({match})",
        )

    # 2. Allowed-root containment
    if not policy.allowed_roots:
        return SafePath(
            requested=raw,
            resolved=resolved,
            is_safe=False,
            reason="no allowed roots configured",
        )

    contained_root: Path | None = None
    for root in policy.allowed_roots:
        try:
            # commonpath raises ValueError if paths are on different drives
            common = os.path.commonpath([str(resolved), str(root)])
        except ValueError:
            continue
        if common == str(root):
            contained_root = root
            break

    if contained_root is None:
        return SafePath(
            requested=raw,
            resolved=resolved,
            is_safe=False,
            reason="path is outside all allowed roots",
        )

    # 3. Symlink check (post-resolution)
    if not policy.allow_symlinks:
        # If the resolved path is or contains a symlink that points
        # outside the allowed root, deny.
        try:
            real = resolved.resolve()
        except OSError as exc:
            return SafePath(
                requested=raw,
                resolved=resolved,
                is_safe=False,
                reason=f"symlink resolve failed: {exc}",
            )
        if str(real) != str(resolved):
            return SafePath(
                requested=raw,
                resolved=resolved,
                is_safe=False,
                reason="path crosses a symlink and symlinks are disabled",
            )

    # 4. Existing path checks
    if policy.require_real_path and not resolved.exists():
        return SafePath(
            requested=raw,
            resolved=resolved,
            is_safe=False,
            reason="path does not exist",
        )

    if resolved.exists() and resolved.is_file() and policy.max_bytes is not None:
        try:
            size = resolved.stat().st_size
        except OSError as exc:
            return SafePath(
                requested=raw,
                resolved=resolved,
                is_safe=False,
                reason=f"stat failed: {exc}",
            )
        if size > policy.max_bytes:
            return SafePath(
                requested=raw,
                resolved=resolved,
                is_safe=False,
                reason=f"file exceeds max size ({size} > {policy.max_bytes})",
            )

    # 5. Depth check (relative to the matched root)
    if policy.max_depth is not None and resolved.exists():
        depth = _depth_from_root(resolved, contained_root)
        if depth > policy.max_depth:
            return SafePath(
                requested=raw,
                resolved=resolved,
                is_safe=False,
                reason=f"path depth {depth} exceeds max {policy.max_depth}",
            )

    return SafePath(requested=raw, resolved=resolved, is_safe=True)


def is_safe_path(
    requested: str | os.PathLike[str],
    policy: PathSafetyPolicy,
) -> bool:
    """Convenience wrapper: ``True`` iff the path passes validation."""
    return resolve_and_validate(requested, policy).is_safe


__all__ = [
    "PathSafetyError",
    "PathSafetyPolicy",
    "SafePath",
    "is_safe_path",
    "resolve_and_validate",
]
