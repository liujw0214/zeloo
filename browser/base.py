"""Browser provider abstract base class and shared types."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PageSnapshot:
    """A single page's extracted content."""

    url: str
    title: str = ""
    content: str = ""
    html: str = ""
    status_code: int = 200
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "html": self.html,
            "status_code": self.status_code,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class CrawlResult:
    """Result of a multi-URL crawl operation."""

    pages: list[PageSnapshot] = field(default_factory=list)
    provider: str = ""
    crawl_url: str = ""
    depth: int = 0
    total_pages: int = 0
    duration_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pages": [p.to_dict() for p in self.pages],
            "provider": self.provider,
            "crawl_url": self.crawl_url,
            "depth": self.depth,
            "total_pages": self.total_pages,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


class BrowserProvider(ABC):
    """Abstract base for browser automation providers.

    Subclasses must set :attr:`name` and implement :meth:`navigate`,
    :meth:`crawl`, :meth:`screenshot`, and :meth:`validate_credentials`.
    """

    name: str = "base"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        self.api_key = api_key
        self.config = kwargs

    @abstractmethod
    def navigate(
        self,
        url: str,
        *,
        wait_for: str | None = None,
        timeout: int = 30,
        **kwargs: Any,
    ) -> PageSnapshot:
        """Navigate to a URL and return the page content.

        Args:
            url: The target URL.
            wait_for: CSS selector or JS expression to wait for before returning.
            timeout: Navigation timeout in seconds.

        Returns:
            A :class:`PageSnapshot`.
        """

    @abstractmethod
    def crawl(
        self,
        url: str,
        *,
        depth: int = 1,
        max_pages: int = 10,
        **kwargs: Any,
    ) -> CrawlResult:
        """Crawl a URL recursively up to *depth* levels.

        Args:
            url: The seed URL.
            depth: Maximum crawl depth.
            max_pages: Maximum number of pages to crawl.

        Returns:
            A :class:`CrawlResult`.
        """

    @abstractmethod
    def screenshot(
        self,
        url: str,
        *,
        full_page: bool = False,
        format: str = "png",
        **kwargs: Any,
    ) -> bytes:
        """Take a screenshot of a URL and return PNG/JPEG bytes.

        Args:
            url: The target URL.
            full_page: Capture the entire scrollable page.
            format: Image format (png or jpeg).

        Returns:
            Raw image bytes.
        """

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Return True if the configured API key is valid."""
