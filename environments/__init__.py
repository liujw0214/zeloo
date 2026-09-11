"""Zeloo environment configuration loader.

Loads merged configuration with the following resolution order (later wins):

1. ``base.yaml`` — shared defaults inherited by every environment
2. ``<env>.yaml`` — environment-specific overlay (deep-merged over base)
3. ``zeloo_*`` environment variables — selective scalar overrides

The active environment is selected by the ``zeloo_ENV`` environment variable
(``dev`` / ``test`` / ``prod``), falling back to ``dev`` if unset or unknown.

Usage::

    from environments import load_environment, current_env_name

    env_name = current_env_name()  # "dev", "test", or "prod"
    config = load_environment()    # fully merged config dict
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ENVIRONMENTS_DIR = Path(__file__).resolve().parent

ENV_NAMES: tuple[str, ...] = ("dev", "test", "prod")

ENV_FILES: dict[str, str] = {
    "dev": "dev.yaml",
    "test": "test.yaml",
    "prod": "prod.yaml",
}

_DEFAULT_ENV = "dev"

#: Prefix for environment variables that override config values.
#: ``zeloo_MODEL`` overrides ``config["model"]``; ``zeloo_TERMINAL__BACKEND``
#: overrides ``config["terminal"]["backend"]`` (``__`` separates nested keys).
_ENV_VAR_PREFIX = "zeloo_"
_ENV_VAR_SEP = "__"

#: Base config file inherited by every environment before overlaying.
_BASE_FILE = "base.yaml"


def current_env_name() -> str:
    """Return the active environment name from ``zeloo_ENV``.

    Falls back to ``dev`` if unset or unknown.
    """
    raw = os.environ.get("zeloo_ENV", _DEFAULT_ENV).strip().lower()
    if raw not in ENV_NAMES:
        return _DEFAULT_ENV
    return raw


def _load_yaml_file(path: Path) -> str:
    """Read a YAML file from disk."""
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _parse_simple_yaml(content: str) -> dict[str, Any]:
    """Parse a small subset of YAML (no external dependencies).

    Supports:
    - key: value
    - key:  (then nested indented lines, dict or list)
    - lists (``- value`` and ``- key: value``)
    - inline ``[]`` / ``{}`` flow collections
    - ``#`` comments
    - string/int/float/bool/null scalars

    The parser uses a "pending key" model: a bare ``key:`` line does not
    immediately create a container. The *next* child line decides whether the
    value becomes a dict (``child: ...``) or a list (``- ...``). This avoids
    the dict-vs-list ambiguity that previously caused an infinite loop.
    """
    result: dict[str, Any] = {}
    lines = content.splitlines()
    # stack of (indent, container) where container is a dict or list
    stack: list[tuple[int, Any]] = [(-1, result)]
    # pending: (parent_dict, key, indent) for a bare "key:" awaiting children
    pending: tuple[dict[str, Any], str, int] | None = None

    def _resolve_pending(as_list: bool) -> None:
        """Materialize the pending key as a dict or list and push it."""
        nonlocal pending
        if pending is None:
            return
        parent, key, ind = pending
        container: Any = [] if as_list else {}
        parent[key] = container
        stack.append((ind, container))
        ctype = type(container).__name__
        logger.debug("resolve pending key=%r as %s at indent=%d", key, ctype, ind)
        pending = None

    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        indent = len(raw) - len(raw.lstrip(" "))
        logger.debug("line %d indent=%d stripped=%r", i, indent, stripped)

        # Pop stack back to the parent of the current indent level
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if not stack:
            stack = [(-1, result)]

        # A pending key at >= current indent never received children.
        if pending is not None and pending[2] >= indent:
            pending[0][pending[1]] = {}
            logger.debug("finalize pending key=%r as empty dict", pending[1])
            pending = None

        current = stack[-1][1]

        # --- List item ---
        if stripped.startswith("- "):
            value_part = _strip_inline_comment(stripped[2:].strip())
            _resolve_pending(as_list=True)
            current = stack[-1][1]
            if isinstance(current, list):
                if (
                    ":" in value_part
                    and not value_part.startswith(("http://", "https://", "ws://", "wss://"))
                ):
                    k, _, v = value_part.partition(":")
                    item: dict[str, Any] = {k.strip(): _parse_scalar(v.strip())}
                    current.append(item)
                    stack.append((indent, item))
                    logger.debug("append dict item %r to list", item)
                else:
                    scalar = _parse_scalar(value_part)
                    current.append(scalar)
                    logger.debug("append scalar %r to list", scalar)
            i += 1
            continue

        # --- Key: value ---
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = _strip_inline_comment(val.strip())
            _resolve_pending(as_list=False)
            current = stack[-1][1]
            if not val:
                # Bare key: defer dict-vs-list decision to the next child line
                pending = (current, key, indent)
                logger.debug("pending key=%r at indent=%d", key, indent)
            else:
                current[key] = _parse_scalar(val)
                logger.debug("set %r = %r", key, current[key])
            i += 1
            continue

        # Unrecognized line; advance to avoid infinite loop
        i += 1

    if pending is not None:
        pending[0][pending[1]] = {}

    return result


def _strip_inline_comment(text: str) -> str:
    """Remove an inline ``# comment`` from a scalar value.

    A ``#`` starts a comment only when preceded by whitespace and not inside
    single or double quotes. Quotes are tracked so ``"a # b"`` is preserved.
    """
    in_single = False
    in_double = False
    for idx, ch in enumerate(text):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if idx == 0 or text[idx - 1].isspace():
                return text[:idx].rstrip()
    return text


def _parse_scalar(text: str) -> Any:
    """Parse a simple scalar value.

    Handles quoted strings, booleans, null, ints, floats, and inline
    ``[]`` / ``{}`` flow collections. Anything else is returned as a string.
    """
    if text == "[]":
        return []
    if text == "{}":
        return {}
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    lower = text.lower()
    if lower in ("true", "yes"):
        return True
    if lower in ("false", "no"):
        return False
    if lower in ("null", "~", ""):
        return None
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` into ``base`` (overlay wins)."""
    for key, value in overlay.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """Override config values from ``zeloo_*`` environment variables.

    Mapping rules:
    - ``zeloo_MODEL`` → ``config["model"]``
    - ``zeloo_TERMINAL__BACKEND`` → ``config["terminal"]["backend"]``
      (``__`` separates nested keys)
    - Values are parsed with :func:`_parse_scalar` so ``zeloo_MAX_TOKENS=4096``
      yields an int, ``zeloo_ENABLED=true`` yields a bool, etc.

    Only existing top-level keys (or their nested children) are overridden;
    env vars that don't correspond to a known config path are ignored to avoid
    accidental key injection.

    Note: on Windows ``os.environ`` is case-insensitive but case-preserving;
    a variable set as ``zeloo_MODEL`` is stored as ``ZELOO_MODEL``. We
    therefore match the prefix case-insensitively.
    """
    prefix_lower = _ENV_VAR_PREFIX.lower()
    for env_key, raw_value in os.environ.items():
        if env_key.lower()[: len(prefix_lower)] != prefix_lower:
            continue
        # ``zeloo_ENV`` selects the environment, not a config value.
        if env_key.lower() == "zeloo_env":
            continue
        path = env_key[len(_ENV_VAR_PREFIX) :].lower().split(_ENV_VAR_SEP)
        if not path or not path[0]:
            continue
        if path[0] not in config:
            continue
        # Walk to the parent of the final key.
        node: Any = config
        for part in path[:-1]:
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
        if not isinstance(node, dict):
            continue
        final_key = path[-1]
        if final_key in node:
            node[final_key] = _parse_scalar(raw_value)
            logger.debug("env override %s = %r", env_key, node[final_key])
    return config


def load_environment(name: str | None = None) -> dict[str, Any]:
    """Load the merged configuration for an environment.

    Resolution order (later wins):
    1. ``base.yaml`` — shared defaults
    2. ``<env>.yaml`` — environment-specific overlay (deep-merged over base)
    3. ``zeloo_*`` environment variables — selective scalar overrides

    Args:
        name: Environment name. If ``None``, uses ``current_env_name()``.

    Returns:
        A dict with the merged config. Empty dict if neither base nor the
        environment file exists.

    Raises:
        ValueError: If ``name`` is explicitly provided and not in ``ENV_NAMES``.
    """
    if name is None:
        name = current_env_name()
    elif name not in ENV_NAMES:
        raise ValueError(
            f"Unknown environment: {name!r}. Valid options: {', '.join(ENV_NAMES)}"
        )

    # 1. Base defaults
    base_content = _load_yaml_file(_ENVIRONMENTS_DIR / _BASE_FILE)
    config = _parse_simple_yaml(base_content)

    # 2. Environment overlay (deep merge, overlay wins)
    env_path = _ENVIRONMENTS_DIR / ENV_FILES[name]
    env_content = _load_yaml_file(env_path)
    env_config = _parse_simple_yaml(env_content)
    _deep_merge(config, env_config)

    # 3. Environment variable overrides
    _apply_env_overrides(config)

    return config


def load_all_environments() -> dict[str, dict[str, Any]]:
    """Load all known environments, keyed by name.

    Useful for ``Zeloo doctor``-style diagnostics.
    """
    result: dict[str, dict[str, Any]] = {}
    for name in ENV_NAMES:
        result[name] = load_environment(name)
    return result


def list_available_environments() -> list[str]:
    """Return a list of environments whose YAML file exists on disk."""
    return [
        name
        for name in ENV_NAMES
        if (_ENVIRONMENTS_DIR / ENV_FILES[name]).exists()
    ]