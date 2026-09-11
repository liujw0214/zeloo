"""Zeloo Agent CLI."""

from __future__ import annotations

# Re-export the configuration core modules so callers can write
# ``from zeloo_cli import config_loader`` without caring about the
# internal split between loader / migrations / defaults.
from zeloo_cli import (
    config_defaults,
    config_home,
    config_inventory,
    config_loader,
    config_migrations,
)

__all__ = [
    "config_defaults",
    "config_home",
    "config_inventory",
    "config_loader",
    "config_migrations",
]
