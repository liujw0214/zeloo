"""Unit tests for web_providers search integration."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)


def test_search_result_to_dict():
    """SearchResult.to_dict() returns a serialisable dict."""
    from web_providers.base import SearchResult

    result = SearchResult(
        title="Test Page",
        url="https://example.com",
        snippet="A test snippet.",
        score=0.95,
        source="test",
        published_date="2024-01-01",
    )
    d = result.to_dict()
    assert d["title"] == "Test Page"
    assert d["url"] == "https://example.com"
    assert d["score"] == 0.95


def test_search_response_to_dict():
    """SearchResponse.to_dict() returns a serialisable dict."""
    from web_providers.base import SearchResponse, SearchResult

    response = SearchResponse(
        query="test query",
        results=[
            SearchResult(
                title="Result 1", url="https://ex.com/1", snippet="s1", score=0.9
            ),
            SearchResult(
                title="Result 2", url="https://ex.com/2", snippet="s2", score=0.8
            ),
        ],
        total_results=2,
        provider="test",
    )
    d = response.to_dict()
    assert d["query"] == "test query"
    assert d["total_results"] == 2
    assert len(d["results"]) == 2


def test_registry_discovers_providers():
    """Registry returns all three built-in search providers."""
    from web_providers.registry import list_providers

    names = list_providers()
    assert "tavily" in names
    assert "duckduckgo" in names
    assert "perplexity" in names


def test_registry_get_provider():
    """get_provider returns an instance of the named provider."""
    from web_providers.registry import get_provider

    p = get_provider("tavily", api_key="fake-key")
    assert p is not None
    assert p.name == "tavily"

    none_p = get_provider("nonexistent")
    assert none_p is None


def test_duckduckgo_no_api_key():
    """DuckDuckGo works without an API key."""
    from web_providers.duckduckgo import DuckDuckGoProvider

    p = DuckDuckGoProvider()
    assert p.validate_credentials() is True


def test_duckduckgo_search_with_mock():
    """DuckDuckGo.search() parses JSON response and returns results."""
    from web_providers.duckduckgo import DuckDuckGoProvider

    mock_data = {
        "Heading": "Python Programming",
        "AbstractText": "Python is a programming language.",
        "AbstractURL": "https://en.wikipedia.org/wiki/Python",
        "AbstractSource": "Wikipedia",
        "RelatedTopics": [
            {"Text": "Python syntax", "FirstURL": "https://ex.com/1"},
            {"Text": "Python libraries", "FirstURL": "https://ex.com/2"},
        ],
    }

    with patch("web_providers.duckduckgo.httpx") as mock_httpx:
        mock_client = MagicMock()
        mock_httpx.Client.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = mock_data
        mock_client.get.return_value = mock_response

        p = DuckDuckGoProvider()
        resp = p.search("python")

        assert resp.query == "python"
        assert resp.provider == "duckduckgo"
        assert len(resp.results) >= 2
        assert any(r.url == "https://en.wikipedia.org/wiki/Python" for r in resp.results)


def test_tavily_search_with_mock():
    """Tavily.search() parses response and returns structured results."""
    from web_providers.tavily import TavilyProvider

    mock_data = {
        "results": [
            {
                "title": "Tavily API",
                "url": "https://tavily.com",
                "content": "AI search.",
                "score": 0.9,
            },
            {
                "title": "Docs",
                "url": "https://docs.tavily.com",
                "content": "Documentation.",
                "score": 0.8,
            },
        ],
        "total_results": 2,
    }

    with patch("web_providers.tavily.httpx") as mock_httpx:
        mock_client = MagicMock()
        mock_httpx.Client.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = mock_data
        mock_client.post.return_value = mock_response

        p = TavilyProvider(api_key="fake-key")
        resp = p.search("tavily api")

        assert resp.provider == "tavily"
        assert len(resp.results) == 2
        assert resp.results[0].title == "Tavily API"
        assert resp.results[0].score == 0.9


def test_tavily_validate_credentials_no_key():
    """Tavily.validate_credentials() returns False when no key is set."""
    from web_providers.tavily import TavilyProvider

    p = TavilyProvider(api_key="")
    assert p.validate_credentials() is False


def test_tavily_news_search_with_mock():
    """Tavily.news_search() calls the news endpoint and parses results."""
    from web_providers.tavily import TavilyProvider

    mock_data = {
        "results": [
            {
                "title": "AI News",
                "url": "https://news.com",
                "content": "Latest AI news.",
                "score": 0.95,
            },
        ],
        "total_results": 1,
    }

    with patch("web_providers.tavily.httpx") as mock_httpx:
        mock_client = MagicMock()
        mock_httpx.Client.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = mock_data
        mock_client.post.return_value = mock_response

        p = TavilyProvider(api_key="fake-key")
        resp = p.news_search("AI", num_results=5)

        assert resp.provider == "tavily"
        assert len(resp.results) == 1
        assert resp.results[0].title == "AI News"


def test_perplexity_search_with_mock():
    """Perplexity.search() parses response with fallback to answer."""
    from web_providers.perplexity import PerplexityProvider

    mock_data = {
        "results": [
            {
                "title": "P Doc",
                "url": "https://perplexity.ai",
                "snippet": "Search docs.",
                "score": 0.9,
            },
        ],
        "total_results": 1,
    }

    with patch("web_providers.perplexity.httpx") as mock_httpx:
        mock_client = MagicMock()
        mock_httpx.Client.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = mock_data
        mock_client.post.return_value = mock_response

        p = PerplexityProvider(api_key="fake-key")
        resp = p.search("perplexity")

        assert resp.provider == "perplexity"
        assert len(resp.results) == 1


def test_perplexity_fallback_to_answer():
    """When Perplexity returns no results, falls back to the answer text."""
    from web_providers.perplexity import PerplexityProvider

    mock_data = {
        "results": [],
        "total_results": 0,
        "choices": [{"message": {"content": "This is the direct answer."}}],
    }

    with patch("web_providers.perplexity.httpx") as mock_httpx:
        mock_client = MagicMock()
        mock_httpx.Client.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = mock_data
        mock_client.post.return_value = mock_response

        p = PerplexityProvider(api_key="fake-key")
        resp = p.search("what is ai")

        assert len(resp.results) == 1
        assert "direct answer" in resp.results[0].snippet


def test_perplexity_validate_credentials_no_key():
    """Perplexity.validate_credentials() returns False when no key."""
    from web_providers.perplexity import PerplexityProvider

    p = PerplexityProvider(api_key="")
    assert p.validate_credentials() is False


if __name__ == "__main__":
    test_search_result_to_dict()
    test_search_response_to_dict()
    test_registry_discovers_providers()
    test_registry_get_provider()
    test_duckduckgo_no_api_key()
    test_duckduckgo_search_with_mock()
    test_tavily_search_with_mock()
    test_tavily_validate_credentials_no_key()
    test_tavily_news_search_with_mock()
    test_perplexity_search_with_mock()
    test_perplexity_fallback_to_answer()
    test_perplexity_validate_credentials_no_key()
    print("All web_providers tests passed!")
