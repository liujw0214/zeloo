"""Web search tool — multiple backends, DuckDuckGo by default."""

from __future__ import annotations

import logging
import os
import re
import urllib.parse
from typing import Any

import httpx

from tools.base import tool
from tools.output_scan import scan_tool_output

logger = logging.getLogger(__name__)

# Search backends: name -> (enabled check, search function)
_BACKENDS: dict[str, Any] = {}


def _strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _search_duckduckgo(query: str, max_results: int) -> list[dict[str, str]]:
    """Search via DuckDuckGo HTML endpoint (no API key required)."""
    results: list[dict[str, str]] = []
    url = "https://html.duckduckgo.com/html/"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ZelooAgent/0.1)"}
    data = {"q": query, "kl": "us-en"}

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.post(url, data=data, headers=headers)
            resp.raise_for_status()
            html = resp.text

        # Parse result blocks: <a class="result__a" href="...">title</a>
        # and <a class="result__snippet">snippet</a>
        link_pattern = re.compile(
            r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            re.DOTALL,
        )
        snippet_pattern = re.compile(
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            re.DOTALL,
        )

        links = link_pattern.findall(html)
        snippets = snippet_pattern.findall(html)

        for i, (raw_url, title) in enumerate(links[:max_results]):
            # DuckDuckGo wraps URLs in a redirect: //duckduckgo.com/l/?uddg=...
            decoded_url = raw_url
            if "uddg=" in raw_url:
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
                decoded_url = parsed.get("uddg", [raw_url])[0]

            title_text = _strip_html(title)
            snippet = _strip_html(snippets[i]) if i < len(snippets) else ""
            results.append(
                {
                    "title": title_text,
                    "url": decoded_url,
                    "snippet": snippet,
                }
            )
    except Exception as e:
        logger.warning("DuckDuckGo search failed: %s", e)

    return results


def _search_serpapi(query: str, max_results: int) -> list[dict[str, str]]:
    """Search via SerpAPI (requires SERPAPI_KEY env var)."""
    results: list[dict[str, str]] = []
    api_key = os.environ.get("SERPAPI_KEY", "")
    if not api_key:
        return results

    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google",
        "q": query,
        "api_key": api_key,
        "num": max_results,
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        for item in data.get("organic_results", [])[:max_results]:
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                }
            )
    except Exception as e:
        logger.warning("SerpAPI search failed: %s", e)

    return results


def _search_tavily(query: str, max_results: int) -> list[dict[str, str]]:
    """Search via Tavily AI-optimized search API (requires TAVILY_API_KEY)."""
    results: list[dict[str, str]] = []
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return results

    url = "https://api.tavily.com/search"
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "advanced",
        "include_answer": False,
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        for item in data.get("results", [])[:max_results]:
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", ""),
                    "score": str(item.get("score", "")),
                }
            )
    except Exception as e:
        logger.warning("Tavily search failed: %s", e)

    return results


def _search_perplexity(query: str, max_results: int) -> list[dict[str, str]]:
    """Search via Perplexity AI search API (requires PERPLEXITY_API_KEY)."""
    results: list[dict[str, str]] = []
    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        return results

    url = "https://api.perplexity.ai/chat/completions"
    payload = {
        "model": "sonar-pro",
        "messages": [{"role": "user", "content": query}],
        "max_tokens": 1024,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        choice = data.get("choices", [{}])[0]
        answer = choice.get("message", {}).get("content", "")
        citations = data.get("citations", [])

        # Perplexity returns a synthesized answer + citation URLs.
        results.append({
            "title": f"Perplexity answer: {query[:60]}",
            "url": "",
            "snippet": answer,
        })
        for cite_url in citations[:max_results]:
            results.append({
                "title": "Citation",
                "url": cite_url,
                "snippet": "",
            })
    except Exception as e:
        logger.warning("Perplexity search failed: %s", e)

    return results


def _search_brave(query: str, max_results: int) -> list[dict[str, str]]:
    """Search via Brave Search API (requires BRAVE_API_KEY)."""
    results: list[dict[str, str]] = []
    api_key = os.environ.get("BRAVE_API_KEY", "")
    if not api_key:
        return results

    url = "https://api.search.brave.com/res/v1/web/search"
    params = {"q": query, "count": max_results}
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        for item in data.get("web", {}).get("results", [])[:max_results]:
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", ""),
                }
            )
    except Exception as e:
        logger.warning("Brave search failed: %s", e)

    return results


def _search_exa(query: str, max_results: int) -> list[dict[str, str]]:
    """Search via Exa semantic search API (requires EXA_API_KEY)."""
    results: list[dict[str, str]] = []
    api_key = os.environ.get("EXA_API_KEY", "")
    if not api_key:
        return results

    url = "https://api.exa.ai/search"
    payload = {
        "query": query,
        "numResults": max_results,
        "useAutoprompt": True,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        for item in data.get("results", [])[:max_results]:
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("text", ""),
                    "score": str(item.get("score", "")),
                }
            )
    except Exception as e:
        logger.warning("Exa search failed: %s", e)

    return results


def _get_active_backend() -> str:
    """Determine which search backend to use.

    Priority: explicit zeloo_SEARCH_BACKEND > Tavily > Perplexity >
    SerpAPI > Exa > Brave > DuckDuckGo (default, no key required).
    """
    explicit = os.environ.get("zeloo_SEARCH_BACKEND", "").lower()
    if explicit in {
        "tavily", "perplexity", "serpapi", "exa", "brave", "duckduckgo",
    }:
        return explicit

    if os.environ.get("TAVILY_API_KEY"):
        return "tavily"
    if os.environ.get("PERPLEXITY_API_KEY"):
        return "perplexity"
    if os.environ.get("SERPAPI_KEY"):
        return "serpapi"
    if os.environ.get("EXA_API_KEY"):
        return "exa"
    if os.environ.get("BRAVE_API_KEY"):
        return "brave"
    return "duckduckgo"


@tool(
    name="web_search",
    description="Search the web for information",
    toolset="web",
)
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web and return formatted results.

    Args:
        query: The search query.
        max_results: Maximum number of results to return (1-10).
    """
    max_results = max(1, min(10, max_results))
    backend = _get_active_backend()

    if backend == "tavily":
        results = _search_tavily(query, max_results)
    elif backend == "perplexity":
        results = _search_perplexity(query, max_results)
    elif backend == "serpapi":
        results = _search_serpapi(query, max_results)
    elif backend == "exa":
        results = _search_exa(query, max_results)
    elif backend == "brave":
        results = _search_brave(query, max_results)
    else:
        results = _search_duckduckgo(query, max_results)

    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query} (backend: {backend})\n"]
    for i, item in enumerate(results, 1):
        lines.append(f"{i}. {item['title']}")
        lines.append(f"   URL: {item['url']}")
        if item["snippet"]:
            lines.append(f"   {item['snippet']}")
        lines.append("")

    return "\n".join(lines).rstrip()


@tool(
    name="web_fetch",
    description="Fetch a URL and return its clean text content",
    toolset="web",
)
def web_fetch(url: str, max_chars: int = 4000) -> str:
    """Fetch a web page and return extracted readable text.

    Uses the auxiliary LLM client (when enabled) to clean up HTML noise;
    otherwise falls back to simple HTML tag stripping.

    Args:
        url: The URL to fetch.
        max_chars: Maximum characters to return.
    """
    try:
        response = httpx.get(url, timeout=15, follow_redirects=True)
        response.raise_for_status()
        content = response.text
    except Exception as exc:
        return f"Error fetching {url}: {exc}"

    # Use auxiliary client for clean text extraction when available
    try:
        from run_agent import _current_agent

        agent = _current_agent.get()
        if agent is not None and hasattr(agent, "auxiliary") and agent.auxiliary.is_available():
            text = agent.auxiliary.extract_text(content)
        else:
            text = _strip_html(content)
    except Exception:
        text = _strip_html(content)

    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    text = text or "(no readable content)"
    return scan_tool_output(text, tool_name="web_fetch", source=url[:200])
