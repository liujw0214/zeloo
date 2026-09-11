"""Configuration schema migrations for Zeloo.

Configurations written by older Zeloo versions are upgraded in-place
to the current schema using a chain of registered migrators. Each
migrator is a function ``(config: dict) -> dict`` decorated with
:func:`register_migration` and is invoked in order when the on-disk
version is older than the target.

This module is intentionally side-effect free other than the
registration table and a couple of convenience constants — actual
loading of the user config happens in :mod:`zeloo_cli.config`.
"""

from __future__ import annotations

import copy
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from zeloo_cli.config_defaults import CONFIG_SCHEMA_VERSION

logger = logging.getLogger(__name__)

#: Bump this when shipping a new schema. Migration target version.
CONFIG_SCHEMA_VERSION = CONFIG_SCHEMA_VERSION  # re-exported for legacy callers
TARGET_VERSION: int = CONFIG_SCHEMA_VERSION

#: Migration table: ``(from_version, to_version) -> migrator_func``.
_MIGRATIONS: dict[tuple[int, int], Callable[[dict[str, Any]], dict[str, Any]]] = {}

#: When ``True``, ``migrate_config`` runs the migrators registered
#: above without writing back to disk. Useful for dry-runs.
_DRY_RUN: bool = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_migration(
    from_version: int,
    to_version: int,
) -> Callable[[Callable[[dict[str, Any]], dict[str, Any]]], Callable[[dict[str, Any]], dict[str, Any]]]:
    """Decorator: register a migrator from ``from_version`` to ``to_version``.

    The decorated function receives the config dict and must return
    the same dict (mutated or replaced) with its ``version`` field
    set to ``to_version``.
    """
    key = (from_version, to_version)

    def decorator(func: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[[dict[str, Any]], dict[str, Any]]:
        if key in _MIGRATIONS:
            logger.warning("Overwriting existing migrator for %s -> %s", from_version, to_version)
        _MIGRATIONS[key] = func
        return func

    return decorator


# ---------------------------------------------------------------------------
# Built-in migrators
# ---------------------------------------------------------------------------


def _migrate_v0_to_v1(config: dict[str, Any]) -> dict[str, Any]:
    """Add schema-level defaults that were implicit in pre-v1 configs.

    Pre-v1 configs had no ``version`` field at all. This migrator
    stamps the config as v1 and back-fills the keys that became
    required in v1 (default approvals mode, log level).
    """
    config.setdefault("approvals", {})
    approvals = config["approvals"]
    approvals.setdefault("mode", "interactive")
    approvals.setdefault("denial_breaker_threshold", 3)

    config.setdefault("logging", {})
    logging_cfg = config["logging"]
    logging_cfg.setdefault("level", "INFO")
    logging_cfg.setdefault("format", "text")

    config.setdefault("display", {})
    display = config["display"]
    display.setdefault("interface", "cli")
    display.setdefault("skin", "default")

    config["version"] = 1
    return config


def _migrate_v1_to_v2(config: dict[str, Any]) -> dict[str, Any]:
    """Rename ``model.name`` to ``model.default`` and add the rest.

    The model selector was renamed in v2 to free up ``name`` for an
    optional human-friendly alias. Provider stays the same.
    """
    model = config.setdefault("model", {})
    if "name" in model and "default" not in model:
        model["default"] = model.pop("name")
    model.setdefault("provider", "openai")
    model.setdefault("temperature", 0.7)
    model.setdefault("max_tokens", 4096)

    config["version"] = 2
    return config


# Register the built-in migrators.
register_migration(0, 1)(_migrate_v0_to_v1)
register_migration(1, 2)(_migrate_v1_to_v2)


def needs_migration(config: dict[str, Any], target_version: int | None = None) -> bool:
    """Return ``True`` when ``config`` is below ``target_version``.

    Missing or non-integer ``version`` fields are treated as version 0
    so very old configs always trigger migration.
    """
    target = target_version if target_version is not None else TARGET_VERSION
    current = _current_version(config)
    return current < target


def _current_version(config: dict[str, Any]) -> int:
    """Extract the numeric version from ``config`` (defaults to 0)."""
    raw = config.get("version", 0) if isinstance(config, dict) else 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _migration_path(
    current: int,
    target: int,
) -> list[tuple[int, int]]:
    """Build a linear migration path from ``current`` to ``target``.

    Raises :class:`ValueError` when no continuous chain of registered
    migrators exists between the two versions.
    """
    if current == target:
        return []
    if current > target:
        raise ValueError(f"Cannot downgrade config from v{current} to v{target}")

    path: list[tuple[int, int]] = []
    cursor = current
    visited: set[int] = {cursor}
    while cursor < target:
        next_step = next(
            ((frm, to) for (frm, to) in _MIGRATIONS.keys() if frm == cursor and to not in visited),
            None,
        )
        if next_step is None:
            raise ValueError(
                f"No migration path from v{cursor} to v{target}; "
                f"registered hops: {sorted(_MIGRATIONS.keys())}"
            )
        _frm, to = next_step
        path.append(next_step)
        if to in visited:
            raise ValueError(f"Cycle detected in migration table at v{to}")
        visited.add(to)
        cursor = to
    return path


def migrate_config(
    config: dict[str, Any],
    target_version: int | None = None,
) -> dict[str, Any]:
    """Migrate ``config`` forward to ``target_version``.

    The input dict may be mutated in place; the returned reference
    points at the same (now up-to-date) object for ergonomic chaining.
    """
    target = target_version if target_version is not None else TARGET_VERSION
    current = _current_version(config)
    if current >= target:
        config["version"] = target
        return config

    work = config if not _DRY_RUN else copy.deepcopy(config)
    for frm, to in _migration_path(current, target):
        migrator = _MIGRATIONS[(frm, to)]
        logger.info("Migrating config v%d -> v%d", frm, to)
        work = migrator(work) or work

    work["version"] = target
    return work


def backup_config_before_migration(config_path: Path) -> Path:
    """Copy ``config_path`` into Zeloo home's ``backup/`` directory.

    The destination file is named with a UTC timestamp so successive
    backups never collide. Returns the path that was written.

    If ``config_path`` does not exist, the function returns ``config_path``
    unchanged (there is nothing to back up).
    """
    if not config_path.is_file():
        logger.debug("No config file to back up at %s", config_path)
        return config_path

    from zeloo_cli.config_home import ensure_zeloo_home, get_backup_dir

    ensure_zeloo_home()
    backup_dir = get_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    suffix = config_path.suffix or ".yaml"
    dest = backup_dir / f"{config_path.stem}.{timestamp}{suffix}"
    shutil.copy2(config_path, dest)
    logger.info("Backed up %s -> %s", config_path, dest)
    return dest


def list_migrations() -> list[tuple[int, int]]:
    """Return the registered migration hops sorted by ``from_version``."""
    return sorted(_MIGRATIONS.keys())


def reset_migration_table() -> None:
    """Clear the in-process migration table.

    Intended for tests that want to register custom migrators in
    isolation. Production code should never call this.
    """
    _MIGRATIONS.clear()


def set_dry_run(enabled: bool) -> None:
    """Toggle the module-level dry-run flag used by :func:`migrate_config`."""
    global _DRY_RUN
    _DRY_RUN = enabled


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "TARGET_VERSION",
    "backup_config_before_migration",
    "list_migrations",
    "migrate_config",
    "needs_migration",
    "register_migration",
    "reset_migration_table",
    "set_dry_run",
]
