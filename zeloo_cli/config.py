"""Zeloo CLI configuration loader."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from agent.zeloo_constants import get_zeloo_home

logger = logging.getLogger(__name__)

_config_cache: dict[str, Any] | None = None


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load configuration from config.yaml.

    Returns an empty dict if the file doesn't exist.
    """
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    path = Path(config_path) if config_path else get_zeloo_home() / "config.yaml"
    if not path.is_file():
        logger.debug("Config file not found: %s", path)
        _config_cache = {}
        return _config_cache

    try:
        with open(path, encoding="utf-8") as f:
            _config_cache = yaml.safe_load(f) or {}
        return _config_cache
    except Exception:
        logger.exception("Failed to load config from %s", path)
        _config_cache = {}
        return _config_cache


def load_config_readonly() -> dict[str, Any]:
    """Load config without caching (for one-off reads)."""
    return load_config()


def reset_config_cache() -> None:
    """Reset the config cache (force reload on next read)."""
    global _config_cache
    _config_cache = None


def get_config_path(config_path: str | None = None) -> Path:
    """Return the path to config.yaml (may not exist yet)."""
    return Path(config_path) if config_path else get_zeloo_home() / "config.yaml"


def save_config(config: dict[str, Any], config_path: str | None = None) -> Path:
    """Save configuration to config.yaml.

    Creates the Zeloo home directory if missing. Resets the in-memory
    cache so subsequent ``load_config`` calls pick up the new values.
    """
    global _config_cache

    path = get_config_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    _config_cache = config
    logger.info("Saved config to %s", path)
    return path


def load_env_file() -> dict[str, str]:
    """Load key=value pairs from the Zeloo home ``.env`` file.

    Returns an empty dict if the file does not exist.
    """
    env_path = get_zeloo_home() / ".env"
    result: dict[str, str] = {}
    if not env_path.is_file():
        return result
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        logger.exception("Failed to load .env from %s", env_path)
    return result
