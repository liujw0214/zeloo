"""Configuration home path resolution for Zeloo.

Resolves the Zeloo configuration root and common sub-paths.
Supports multiple environment variable overrides for portable
deployments (CI runners, containers, dev sandboxes).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

# Environment variable names accepted as Zeloo home overrides.
# Order matters: first non-empty wins.
_ZELOO_HOME_ENV_VARS: Final[tuple[str, ...]] = (
    "ZELOO_HOME",
    "zeloo_HOME",
    "zelooHOME",
)

# Default Zeloo home directory (used when no override is set).
_DEFAULT_HOME: Final[Path] = Path.home() / ".Zeloo"

# Sub-directory layout under Zeloo home.
_PROFILE_DIR: Final[str] = "profiles"
_LOG_DIR: Final[str] = "logs"
_BACKUP_DIR: Final[str] = "backup"
_PLUGINS_DIR: Final[str] = "plugins"
_SKILLS_DIR: Final[str] = "skills"
_SECRETS_FILE: Final[str] = "secrets.enc"
_ENV_FILE: Final[str] = ".env"
_CONFIG_FILE: Final[str] = "config.yaml"
_ACTIVE_PROFILE_FILE: Final[str] = "active_profile"

# Programmatic override cache (per-process).
_home_override: str | None = None


def _resolve_home() -> Path:
    """Internal helper: resolve Zeloo home from env vars / override / default."""
    for var in _ZELOO_HOME_ENV_VARS:
        val = os.environ.get(var)
        if val:
            return Path(val).expanduser()
    if _home_override:
        return Path(_home_override).expanduser()
    return _DEFAULT_HOME


def get_zeloo_home() -> Path:
    """Return the active Zeloo home directory.

    Resolution order:
        1. ``ZELOO_HOME`` environment variable
        2. ``zeloo_HOME`` environment variable
        3. ``zelooHOME`` environment variable
        4. Programmatic override (set_zeloo_home_override)
        5. Default ``~/.Zeloo``
    """
    return _resolve_home()


def set_zeloo_home_override(path: str | os.PathLike[str]) -> None:
    """Programmatically override the Zeloo home directory.

    Used by tests and embedded callers that need to redirect all
    config / state lookups without mutating environment variables.
    """
    global _home_override
    _home_override = os.fspath(path)


def reset_zeloo_home_override() -> None:
    """Clear the programmatic Zeloo home override."""
    global _home_override
    _home_override = None


def get_config_path() -> Path:
    """Return the path to ``config.yaml`` under Zeloo home."""
    return get_zeloo_home() / _CONFIG_FILE


def get_env_path() -> Path:
    """Return the path to the active ``.env`` file under Zeloo home."""
    return get_zeloo_home() / _ENV_FILE


def get_secrets_path() -> Path:
    """Return the path to the encrypted ``secrets.enc`` file."""
    return get_zeloo_home() / _SECRETS_FILE


def get_profiles_dir() -> Path:
    """Return the directory holding named profiles."""
    return get_zeloo_home() / _PROFILE_DIR


def get_logs_dir() -> Path:
    """Return the directory holding runtime logs."""
    return get_zeloo_home() / _LOG_DIR


def get_backup_dir() -> Path:
    """Return the directory holding config backups."""
    return get_zeloo_home() / _BACKUP_DIR


def get_plugins_dir() -> Path:
    """Return the directory holding installed plugins."""
    return get_zeloo_home() / _PLUGINS_DIR


def get_skills_dir() -> Path:
    """Return the directory holding workspace-local skills."""
    return get_zeloo_home() / _SKILLS_DIR


def ensure_zeloo_home() -> Path:
    """Ensure the Zeloo home directory exists; create it if missing.

    Returns the resolved home path. Parent directories are created
    recursively with the default permissions.
    """
    home = get_zeloo_home()
    try:
        home.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("Failed to create Zeloo home at %s", home)
        raise
    return home


def get_active_profile() -> str:
    """Return the currently active profile name.

    Falls back to ``"default"`` when no profile has been activated
    yet (or when the marker file is unreadable).
    """
    marker = get_zeloo_home() / _ACTIVE_PROFILE_FILE
    if marker.is_file():
        try:
            name = marker.read_text(encoding="utf-8").strip()
            if name:
                return name
        except OSError:
            logger.exception("Failed to read active profile marker at %s", marker)
    return "default"


def set_active_profile(name: str) -> Path:
    """Set the active profile name and persist it to disk.

    The marker file is created under Zeloo home if missing.
    Returns the path that was written.
    """
    home = ensure_zeloo_home()
    marker = home / _ACTIVE_PROFILE_FILE
    marker.write_text(name.strip(), encoding="utf-8")
    return marker


def list_known_subpaths() -> dict[str, Path]:
    """Return a mapping of every well-known Zeloo home sub-path.

    Useful for diagnostics, doctor commands, and snapshot tooling.
    """
    return {
        "home": get_zeloo_home(),
        "config": get_config_path(),
        "env": get_env_path(),
        "secrets": get_secrets_path(),
        "profiles": get_profiles_dir(),
        "logs": get_logs_dir(),
        "backup": get_backup_dir(),
        "plugins": get_plugins_dir(),
        "skills": get_skills_dir(),
        "active_profile_file": get_zeloo_home() / _ACTIVE_PROFILE_FILE,
    }


__all__ = [
    "ensure_zeloo_home",
    "get_active_profile",
    "get_backup_dir",
    "get_config_path",
    "get_env_path",
    "get_logs_dir",
    "get_plugins_dir",
    "get_profiles_dir",
    "get_secrets_path",
    "get_skills_dir",
    "get_zeloo_home",
    "list_known_subpaths",
    "reset_zeloo_home_override",
    "set_active_profile",
    "set_zeloo_home_override",
]
