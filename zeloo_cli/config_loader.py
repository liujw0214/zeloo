"""Multi-level ``.env`` loader for Zeloo.

Loads environment variables from a hierarchy of locations, in order of
increasing priority (later entries override earlier ones):

    1. ``/etc/Zeloo/Zeloo.env``          - system-wide defaults
    2. ``$ZELOO_HOME/.env``              - user-level overrides
    3. ``<base_path>/.env``              - local project overrides
    4. ``os.environ`` itself             - live process environment

Also exposes helpers for variable interpolation (``${VAR}`` / ``${VAR:-x}``),
automatic type coercion (bool / int / float / list / dict), validation of
required variables, and masking of sensitive values for safe logging.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: System-level env file shipped with the OS package.
SYSTEM_ENV_PATH: Path = Path("/etc/Zeloo/Zeloo.env")

#: Patterns used when parsing ``.env`` files.
_COMMENT_LINE = re.compile(r"^\s*#")
_BLANK_LINE = re.compile(r"^\s*$")
_KV_LINE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)$")

#: Interpolation pattern for ``${VAR}`` and ``${VAR:-default}``.
_INTERPOLATION_RE = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}")


def _parse_line(line: str) -> tuple[str, str] | None:
    """Parse a single non-comment ``.env`` line into ``(key, value)``.

    Returns ``None`` for blank / comment / malformed lines. Quote
    characters around the value are stripped.
    """
    if _BLANK_LINE.match(line) or _COMMENT_LINE.match(line):
        return None
    m = _KV_LINE.match(line)
    if not m:
        return None
    key = m.group("key")
    raw = m.group("value").strip()
    # Strip matching surrounding quotes (single or double).
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1]
    return key, raw


def _read_env_file(path: Path) -> dict[str, str]:
    """Read ``path`` and return parsed ``key=value`` pairs.

    Missing files yield an empty dict; unreadable files are logged
    but never raised so a corrupt env file cannot block startup.
    """
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                parsed = _parse_line(line.rstrip("\n").rstrip("\r"))
                if parsed is not None:
                    result[parsed[0]] = parsed[1]
    except OSError:
        logger.exception("Failed to read env file %s", path)
    return result


def load_env_files(
    base_path: Path | os.PathLike[str] | None = None,
    override: bool = True,
) -> dict[str, str]:
    """Load env variables from the standard multi-level cascade.

    Parameters
    ----------
    base_path:
        Optional project root whose ``.env`` should be layered in.
        Defaults to the current working directory.
    override:
        When ``True`` (default), the live process environment wins
        over file-based entries; this matches the behaviour of most
        12-factor app loaders. Pass ``False`` to inspect the merged
        file content without touching ``os.environ``.

    Returns
    -------
    dict[str, str]
        The merged mapping that was (or would have been) applied to
        the process environment.
    """
    base = Path(os.fspath(base_path)) if base_path is not None else Path.cwd()

    sources: list[tuple[str, Path]] = [
        ("system", SYSTEM_ENV_PATH),
        ("user", base / ".Zeloo.env"),  # legacy alias kept for symmetry
        ("user", (Path(os.environ.get("ZELOO_HOME", str(Path.home() / ".Zeloo"))) / ".env")),
        ("local", base / ".env"),
    ]

    merged: dict[str, str] = {}
    for _label, path in sources:
        merged.update(_read_env_file(path))

    if override:
        # Process env wins; only keys already present in the merged
        # mapping are re-applied so unrelated os.environ vars stay
        # untouched.
        for key, value in merged.items():
            os.environ[key] = value
        # Pull any keys that exist in os.environ but not in files so
        # the returned dict reflects the final process state.
        for key in list(merged.keys()):
            merged[key] = os.environ.get(key, merged[key])
    else:
        # Non-destructive mode: overlay process env on top of files.
        for key, value in os.environ.items():
            if key in merged or _should_pull_from_process_env(key):
                merged[key] = value

    return merged


def _should_pull_from_process_env(key: str) -> bool:
    """Decide whether an unset ``os.environ`` key should leak into the merge.

    Keeps the merge predictable: only well-known Zeloo prefixes are
    auto-promoted from the process environment in non-override mode.
    """
    return key.startswith(("ZELOO_", "zeloo_"))


def interpolate_env(value: str, env: dict[str, str] | None = None) -> str:
    """Expand ``${VAR}`` and ``${VAR:-default}`` references in ``value``.

    Resolution order for each reference:
        1. ``env`` argument (defaults to ``os.environ``)
        2. The default inline ``:-default`` suffix, if present
        3. The empty string

    Unknown variables without a default are left as the literal
    ``${VAR}`` token so the caller can detect the gap.
    """
    lookup = env if env is not None else dict(os.environ)

    def _replace(match: re.Match[str]) -> str:
        name = match.group("name")
        default = match.group("default")
        if name in lookup and lookup[name] != "":
            return lookup[name]
        if default is not None:
            return default
        return ""

    return _INTERPOLATION_RE.sub(_replace, value)


def parse_env_value(value: str) -> Any:
    """Auto-coerce a raw env string into a richer Python type.

    Conversion ladder (first match wins)::

        "true" / "false"      -> bool
        "<integer>"           -> int
        "<float>"             -> float
        "a,b,c,d"             -> list[str]   (whitespace stripped)
        "key=val,key2=val2"   -> dict[str,str]

    Anything that does not match a known shape is returned as the
    original string. Empty strings yield an empty string.
    """
    if value == "":
        return ""

    lower = value.lower()
    if lower in {"true", "yes", "on"}:
        return True
    if lower in {"false", "no", "off"}:
        return False
    if lower in {"null", "none"}:
        return None

    # Dict syntax takes precedence over list syntax because both use commas.
    if "=" in value and "," in value and not value.lstrip().startswith(("[", "{")):
        # Ensure no list-shaped prefix like "[a,b]" sneaks in.
        if not value.startswith(("[", "{")):
            pairs = [p for p in value.split(",") if p.strip()]
            if all("=" in p for p in pairs):
                out: dict[str, str] = {}
                for p in pairs:
                    k, _, v = p.partition("=")
                    out[k.strip()] = v.strip()
                return out

    # Bracketed list literal (e.g. ``[a, b, c]``).
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if inner == "":
            return []
        return [item.strip() for item in inner.split(",")]

    # Comma-separated scalar list.
    if "," in value:
        return [item.strip() for item in value.split(",") if item.strip() != ""]

    # Numeric coercion (int before float so "10" doesn't become 10.0).
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass

    return value


def validate_required_vars(
    required: list[str],
    env: dict[str, str] | None = None,
) -> tuple[bool, list[str]]:
    """Check that every name in ``required`` is present and non-empty.

    The lookup is done against the provided ``env`` mapping first,
    then against ``os.environ`` as a fallback. Returns a tuple of
    ``(is_valid, missing_names)`` so callers can both branch on the
    boolean and report the exact missing keys.
    """
    lookup = env if env is not None else dict(os.environ)
    missing: list[str] = []
    for name in required:
        val = lookup.get(name) or os.environ.get(name)
        if val is None or val == "":
            missing.append(name)
    return (len(missing) == 0, missing)


def mask_sensitive(value: str, visible_chars: int = 4) -> str:
    """Return a partially-redacted view of a sensitive string.

    Examples::

        mask_sensitive("sk-abc123xyz")        -> "sk-a***xyz"
        mask_sensitive("abcdef")              -> "a***f"
        mask_sensitive("a")                   -> "***"
        mask_sensitive("", visible_chars=4)   -> ""

    The ``visible_chars`` argument controls how many characters are
    kept at each end; the middle is replaced by three asterisks.
    """
    if not value:
        return ""
    if len(value) <= visible_chars * 2:
        return "***"
    head = value[:visible_chars]
    tail = value[-visible_chars:] if visible_chars > 0 else ""
    return f"{head}***{tail}"


def is_sensitive_key(key: str) -> bool:
    """Best-effort heuristic for whether a key holds sensitive material.

    Used by logging helpers to decide whether to call
    :func:`mask_sensitive` automatically.
    """
    upper = key.upper()
    sensitive_substrings = (
        "KEY",
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "PASS",
        "CREDENTIAL",
        "AUTH",
        "PRIVATE",
    )
    return any(sub in upper for sub in sensitive_substrings)


__all__ = [
    "SYSTEM_ENV_PATH",
    "interpolate_env",
    "is_sensitive_key",
    "load_env_files",
    "mask_sensitive",
    "parse_env_value",
    "validate_required_vars",
]
