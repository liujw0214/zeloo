"""Search provider abstract base class and shared types."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result returned by a provider."""

    title: str
    url: str
    snippet: str
    score: float = 0.0
    source: str = ""
    published_date: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "score": self.score,
            "source": self.source,
            "published_date": self.published_date,
        }


@dataclass
class SearchResponse:
    """Structured response returned by :meth:`SearchProvider.search`."""

    query: str
    results: list[SearchResult] = field(default_factory=list)
    total_results: int = 0
    provider: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "total_results": self.total_results,
            "provider": self.provider,
            "results": [r.to_dict() for r in self.results],
        }


class ValidationError(Exception):
    """Raised when API credentials or configuration are invalid."""


class SearchProvider(ABC):
    """Abstract base for all search providers.

    Subclasses must set :attr:`name` and implement :meth:`search`,
    :meth:`validate_credentials`, and optionally :meth:`news_search`.
    """

    name: str = "base"
    base_url: str = ""

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        self.api_key = api_key
        self.config = kwargs

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        """Perform a web search and return structured results.

        Args:
            query: The search query string.
            num_results: Maximum number of results to return (provider may return fewer).

        Returns:
            A :class:`SearchResponse` containing ranked results.
        """

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Return True if the configured API key is valid."""

    def news_search(
        self,
        query: str,
        *,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        """Perform a news-focused search.

        Default implementation falls back to :meth:`search`.
        Subclasses should override if the provider has a dedicated news endpoint.
        """
        return self.search(query, num_results=num_results, **kwargs)
