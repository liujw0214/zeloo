"""Browser automation providers — BrowserBase, Firecrawl.

Provides a uniform interface for headless browsing, page crawling,
and content extraction so the agent can interact with the live web.
"""

from __future__ import annotations

from browser.base import BrowserProvider, CrawlResult, PageSnapshot
from browser.registry import get_provider, list_providers, register_provider

__all__ = [
    "BrowserProvider",
    "CrawlResult",
    "PageSnapshot",
    "get_provider",
    "list_providers",
    "register_provider",
]
