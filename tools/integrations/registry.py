"""Platform integration registry.

Maps a short string identifier (``"discord"``, ``"slack"``, ...) to a
concrete :class:`BaseIntegration` subclass. Integrations register
themselves at import time via the :func:`register_integration` decorator.
"""

from __future__ import annotations

import logging
from typing import Any

from tools.integrations.base import BaseIntegration

logger = logging.getLogger(__name__)

INTEGRATION_REGISTRY: dict[str, type[BaseIntegration]] = {}


def register_integration(
    name: str,
    cls: type[BaseIntegration] | None = None,
) -> Any:
    """Register an integration class.

    Can be used as a bare decorator or a function call::

        @register_integration("discord")
        class DiscordIntegration(BaseIntegration): ...

        register_integration("custom", MyIntegration)
    """

    def _wrap(klass: type[BaseIntegration]) -> type[BaseIntegration]:
        if not isinstance(klass, type) or not issubclass(klass, BaseIntegration):
            raise TypeError(
                f"{klass!r} is not a subclass of BaseIntegration"
            )
        if name in INTEGRATION_REGISTRY:
            logger.warning(
                "Integration %r already registered; overwriting with %s",
                name,
                klass.__name__,
            )
        INTEGRATION_REGISTRY[name] = klass
        # Stash on the class for debugging/inspection.
        klass.platform_name = klass.platform_name or name  # type: ignore[misc]
        return klass

    if cls is None:
        return _wrap
    return _wrap(cls)


def get_integration(
    name: str,
    config: dict[str, Any] | None = None,
) -> BaseIntegration | None:
    """Instantiate the integration registered under ``name``.

    Returns ``None`` if the name is unknown. ``config`` defaults to an
    empty dictionary so call-sites can always pass an optional config.
    """
    klass = INTEGRATION_REGISTRY.get(name)
    if klass is None:
        logger.warning("No integration registered for name=%r", name)
        return None
    return klass(config or {})


def list_integrations() -> list[str]:
    """Return the sorted list of registered integration identifiers."""
    return sorted(INTEGRATION_REGISTRY.keys())


def unregister_integration(name: str) -> bool:
    """Remove a previously registered integration.

    Returns ``True`` if an entry was removed, ``False`` otherwise.
    Primarily useful for tests that want to reset state.
    """
    return INTEGRATION_REGISTRY.pop(name, None) is not None


# ---------------------------------------------------------------------------
# Auto-registration: importing this module triggers registration of all
# built-in integrations. Each integration file applies the
# ``@register_integration`` decorator at class definition time, so the
# imports below populate :data:`INTEGRATION_REGISTRY` as a side effect.
# A failed import is logged at WARNING and the integration is simply
# absent from the registry (it remains importable as a module).
# ---------------------------------------------------------------------------
def _try_import(name: str, module_path: str) -> None:
    try:
        import importlib

        importlib.import_module(module_path)
        logger.debug("Loaded integration: %s", name)
    except ModuleNotFoundError as exc:
        logger.warning("Skipping integration %s: %s", name, exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load integration %s: %s", name, exc)


_try_import("discord", "tools.integrations.discord_integration")
_try_import("slack", "tools.integrations.slack_integration")
_try_import("feishu", "tools.integrations.feishu_integration")
_try_import("telegram", "tools.integrations.telegram_integration")


__all__ = [
    "INTEGRATION_REGISTRY",
    "register_integration",
    "get_integration",
    "list_integrations",
    "unregister_integration",
]