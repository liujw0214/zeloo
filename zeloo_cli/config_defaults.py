"""Zeloo default configuration values.

Every user-visible configuration key has a default declared here.
The defaults intentionally mirror the schema version declared in
``zeloo_cli.config_migrations`` so that a fresh install matches
the latest migration target out-of-the-box.
"""

from __future__ import annotations

import copy
from typing import Any

#: Current configuration schema version. Mirrored here so other
#: modules can import a single constant without triggering the
#: heavier config_migrations module's side effects.
CONFIG_SCHEMA_VERSION: int = 2


DEFAULT_CONFIG: dict[str, Any] = {
    "version": CONFIG_SCHEMA_VERSION,
    "model": {
        "provider": "openai",
        "default": "gpt-4o",
        "temperature": 0.7,
        "max_tokens": 4096,
    },
    "voice": {
        "backend": "console",
        "tts_model": "tts-1",
        "stt_model": "whisper-1",
    },
    "terminal": {
        "backend": "local",
        "timeout": 30,
        "sandbox": False,
    },
    "approvals": {
        "mode": "interactive",
        "denial_breaker_threshold": 3,
    },
    "mcp_servers": {},
    "agents": {},
    "skills": {},
    "display": {
        "interface": "cli",  # cli | tui
        "skin": "default",
    },
    "logging": {
        "level": "INFO",
        "format": "text",  # text | json
    },
}


def get_default(path: str, default: Any = None) -> Any:
    """Look up a default value using a dotted path.

    Example::

        get_default("model.default")        # -> "gpt-4o"
        get_default("model.missing", "x")   # -> "x"

    Returns ``default`` (which itself defaults to ``None``) when
    any segment along the path does not exist.
    """
    if not path:
        return default
    cur: Any = DEFAULT_CONFIG
    for segment in path.split("."):
        if isinstance(cur, dict) and segment in cur:
            cur = cur[segment]
        else:
            return default
    return cur


def get_all_defaults() -> dict[str, Any]:
    """Return a deep copy of the full default configuration.

    Callers should use this whenever they want to seed a fresh
    config rather than mutating the module-level ``DEFAULT_CONFIG``
    constant.
    """
    return copy.deepcopy(DEFAULT_CONFIG)


def default_version() -> int:
    """Return the current default schema version."""
    return CONFIG_SCHEMA_VERSION


def merge_defaults(overrides: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge ``overrides`` on top of a copy of ``DEFAULT_CONFIG``.

    Existing scalar values are replaced by override values; existing
    mappings are merged recursively. Lists are replaced wholesale
    (no element-wise merge) which mirrors the YAML semantics that
    Zeloo uses elsewhere.
    """
    base = get_all_defaults()
    return _deep_merge(base, overrides)


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict-merge helper used by :func:`merge_defaults`."""
    for key, val in overrides.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(val, dict)
        ):
            base[key] = _deep_merge(base[key], val)
        else:
            base[key] = copy.deepcopy(val)
    return base


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "DEFAULT_CONFIG",
    "default_version",
    "get_all_defaults",
    "get_default",
    "merge_defaults",
]
