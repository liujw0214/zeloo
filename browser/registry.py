"""Browser provider registry."""

from __future__ import annotations

import logging
from typing import Any

from browser.base import BrowserProvider

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type[BrowserProvider]] = {}


def register_provider(name: str, cls: type[BrowserProvider]) -> None:
    _REGISTRY[name.lower()] = cls
    logger.debug("Registered browser provider: %s", name)


def get_provider(name: str, **kwargs: Any) -> BrowserProvider | None:
    cls = _REGISTRY.get(name.lower())
    if cls is None:
        return None
    return cls(**kwargs)


def list_providers() -> list[str]:
    return sorted(_REGISTRY.keys())


def _register_builtins() -> None:
    from browser.browserbase import BrowserBaseProvider
    from browser.firecrawl import FirecrawlProvider
    from browser.playwright import PlaywrightBrowserProvider

    register_provider("browserbase", BrowserBaseProvider)
    register_provider("firecrawl", FirecrawlProvider)
    register_provider("playwright", PlaywrightBrowserProvider)


_register_builtins()
