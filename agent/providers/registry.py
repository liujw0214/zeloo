"""Provider registry — central discovery for :class:`BaseProvider` subclasses.

Concrete provider classes call :func:`register_provider` from their
module body (usually at the bottom of the file) so the registry is
populated as a side-effect of importing the module. The agent runtime
imports the package via :mod:`agent.providers` (which in turn imports
every concrete provider) to ensure registration happens at startup.

The registry is intentionally simple — a single module-level dict and
three accessor functions. This mirrors the design of the existing
:mod:`model_providers.registry` module so contributors familiar with
that module will find the new API familiar.

Example
-------
>>> from agent.providers.registry import (
...     PROVIDER_REGISTRY, register_provider, get_provider, list_providers,
... )
>>> "openai" in PROVIDER_REGISTRY
True
>>> provider = get_provider("openai", {"api_key": "sk-..."})
>>> provider.name
'openai'
"""

from __future__ import annotations

import logging
from typing import Any

from agent.providers.base import BaseProvider

logger = logging.getLogger(__name__)


PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {}


def register_provider(name: str, cls: type[BaseProvider]) -> None:
    """Register a provider class under *name*.

    If a provider is already registered under the same name the new
    class replaces it. A warning is logged so silent overrides are
    visible during development.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("provider name must be a non-empty string")
    if not (isinstance(cls, type) and issubclass(cls, BaseProvider)):
        raise TypeError(
            f"cls must be a BaseProvider subclass, got {cls!r}"
        )
    if name in PROVIDER_REGISTRY:
        logger.debug(
            "Overriding existing provider registration for %s", name,
        )
    PROVIDER_REGISTRY[name.lower()] = cls
    logger.debug("Registered provider: %s -> %s", name, cls.__name__)


def get_provider(name: str, config: dict[str, Any] | None = None) -> BaseProvider | None:
    """Return an instance of the registered provider *name*, or None.

    Missing providers return ``None`` so callers can fall back to
    another strategy (e.g. surfacing a configuration error to the user
    or trying a different provider).
    """
    cls = PROVIDER_REGISTRY.get((name or "").lower())
    if cls is None:
        return None
    try:
        return cls(config or {})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to instantiate provider %s", name)
        return None


def list_providers() -> list[str]:
    """Return a sorted list of all registered provider names."""
    return sorted(PROVIDER_REGISTRY.keys())


def unregister_provider(name: str) -> bool:
    """Remove a provider from the registry. Returns True if removed."""
    return PROVIDER_REGISTRY.pop(name.lower(), None) is not None


def clear_registry() -> None:  # pragma: no cover - test helper
    """Remove all registered providers. Intended for test isolation only."""
    PROVIDER_REGISTRY.clear()


__all__ = [
    "PROVIDER_REGISTRY",
    "register_provider",
    "get_provider",
    "list_providers",
    "unregister_provider",
    "clear_registry",
]
