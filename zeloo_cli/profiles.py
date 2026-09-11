"""Profile management for Zeloo.

Profiles are isolated Zeloo home directories under
``~/.Zeloo/profiles/<name>/``. Each profile has its own config.yaml,
skills/, memories/, and state.db. Activating a profile points the
runtime at that directory via zeloo_HOME.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from agent.zeloo_constants import (
    get_profile_dir,
    get_profiles_root,
    get_zeloo_home,
    set_zeloo_home_override,
)

logger = logging.getLogger(__name__)

# Subdirectories created for every new profile
_PROFILE_SUBDIRS = ("skills", "memories", "trajectories")


def get_active_profile_name() -> str:
    """Return the name of the currently active profile."""
    home = get_zeloo_home()
    profiles_root = get_profiles_root()
    try:
        rel = home.resolve().relative_to(profiles_root.resolve())
        return rel.parts[0] if rel.parts else "default"
    except (ValueError, OSError):
        return "default"


def list_profiles() -> list[str]:
    """List all available profile names (always includes 'default')."""
    profiles_root = get_profiles_root()
    if not profiles_root.is_dir():
        return ["default"]
    profiles = {"default"}
    for child in profiles_root.iterdir():
        if child.is_dir():
            profiles.add(child.name)
    return sorted(profiles)


def create_profile(name: str, *, copy_from: str | None = None) -> Path:
    """Create a new profile directory with the standard subdirectory layout.

    Args:
        name: Profile name (kebab-case recommended).
        copy_from: If given, copy config.yaml from this existing profile.

    Returns:
        The path to the new profile directory.
    """
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"Invalid profile name: {name!r}")

    profile_dir = get_profile_dir(name)
    if profile_dir.exists():
        raise FileExistsError(f"Profile '{name}' already exists at {profile_dir}")

    profile_dir.mkdir(parents=True, exist_ok=True)
    for sub in _PROFILE_SUBDIRS:
        (profile_dir / sub).mkdir(exist_ok=True)

    # Copy config from an existing profile if requested
    if copy_from:
        source_cfg = get_profile_dir(copy_from) / "config.yaml"
        if source_cfg.is_file():
            shutil.copy2(source_cfg, profile_dir / "config.yaml")
            logger.info("Copied config.yaml from profile '%s' to '%s'", copy_from, name)
        else:
            logger.warning("Source profile '%s' has no config.yaml", copy_from)

    logger.info("Created profile '%s' at %s", name, profile_dir)
    return profile_dir


def activate_profile(name: str) -> Path:
    """Activate a profile by pointing zeloo_HOME at its directory.

    This sets the programmatic home override for the current process.
    For cross-process activation, set the ``zeloo_HOME`` environment
    variable to the profile directory before launching.
    """
    profile_dir = get_profile_dir(name)
    if not profile_dir.is_dir():
        raise FileNotFoundError(f"Profile '{name}' not found at {profile_dir}")

    set_zeloo_home_override(str(profile_dir))
    # Also set the env var so subprocesses (MCP servers, etc.) inherit it
    os.environ["zeloo_HOME"] = str(profile_dir)

    # Reset config cache so the profile's config.yaml is loaded next
    try:
        from zeloo_cli.config import reset_config_cache

        reset_config_cache()
    except Exception:
        pass

    logger.info("Activated profile '%s' -> %s", name, profile_dir)
    return profile_dir


def delete_profile(name: str) -> None:
    """Delete a profile directory. Cannot delete 'default'."""
    if name == "default":
        raise ValueError("Cannot delete the 'default' profile")
    profile_dir = get_profile_dir(name)
    if not profile_dir.is_dir():
        raise FileNotFoundError(f"Profile '{name}' not found")
    shutil.rmtree(profile_dir)
    logger.info("Deleted profile '%s'", name)
