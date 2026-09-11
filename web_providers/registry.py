"""Search provider registry — discovery and lookup."""

from __future__ import annotations

import logging
from typing import Any

from web_providers.base import SearchProvider

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type[SearchProvider]] = {}


def register_provider(name: str, cls: type[SearchProvider]) -> None:
    _REGISTRY[name.lower()] = cls
    logger.debug("Registered search provider: %s", name)


def get_provider(name: str, **kwargs: Any) -> SearchProvider | None:
    cls = _REGISTRY.get(name.lower())
    if cls is None:
        return None
    return cls(**kwargs)


def list_providers() -> list[str]:
    return sorted(_REGISTRY.keys())


def _register_builtins() -> None:
    from web_providers.algolia import AlgoliaProvider
    from web_providers.amazon_search import AmazonSearchProvider
    from web_providers.arxiv import ArxivProvider
    from web_providers.baidu import BaiduProvider
    from web_providers.bing_web import BingWebProvider
    from web_providers.brave import BraveProvider
    from web_providers.duckduckgo import DuckDuckGoProvider
    from web_providers.exa import ExaProvider
    from web_providers.firecrawl import FirecrawlProvider
    from web_providers.github_search import GitHubSearchProvider
    from web_providers.google_cse import GoogleCSEProvider
    from web_providers.google_scholar import GoogleScholarProvider
    from web_providers.grok_search import GrokSearchProvider
    from web_providers.hackernews import HackerNewsProvider
    from web_providers.indeed import IndeedProvider
    from web_providers.kagi import KagiProvider
    from web_providers.keenable import KeenableProvider
    from web_providers.mojeek import MojeekProvider
    from web_providers.naver import NaverProvider
    from web_providers.osm_search import OpenStreetMapProvider
    from web_providers.parallel import ParallelProvider
    from web_providers.perplexity import PerplexityProvider
    from web_providers.pubmed import PubMedProvider
    from web_providers.reddit_search import RedditSearchProvider
    from web_providers.search_360 import Search360Provider
    from web_providers.searxng import SearXNGProvider
    from web_providers.semantic_scholar import SemanticScholarProvider
    from web_providers.serpapi import SerpAPIProvider
    from web_providers.serper import SerperProvider
    from web_providers.skyscanner import SkyscannerProvider
    from web_providers.sogou import SogouProvider
    from web_providers.stackoverflow import StackOverflowProvider
    from web_providers.tavily import TavilyProvider
    from web_providers.twitter_search import TwitterSearchProvider
    from web_providers.yahoo_search import YahooSearchProvider
    from web_providers.yandex import YouProvider
    from web_providers.yandex_search import YandexSearchProvider
    from web_providers.youtube_search import YouTubeSearchProvider

    register_provider("tavily", TavilyProvider)
    register_provider("duckduckgo", DuckDuckGoProvider)
    register_provider("perplexity", PerplexityProvider)
    register_provider("brave", BraveProvider)
    register_provider("exa", ExaProvider)
    register_provider("searxng", SearXNGProvider)
    register_provider("firecrawl", FirecrawlProvider)
    register_provider("google_cse", GoogleCSEProvider)
    register_provider("serper", SerperProvider)
    register_provider("kagi", KagiProvider)
    register_provider("you", YouProvider)
    register_provider("parallel", ParallelProvider)
    register_provider("keenable", KeenableProvider)
    register_provider("serpapi", SerpAPIProvider)
    register_provider("grok_search", GrokSearchProvider)
    register_provider("yandex_search", YandexSearchProvider)
    register_provider("mojeek", MojeekProvider)
    register_provider("search_360", Search360Provider)
    register_provider("google_scholar", GoogleScholarProvider)
    register_provider("semantic_scholar", SemanticScholarProvider)
    register_provider("arxiv", ArxivProvider)
    register_provider("pubmed", PubMedProvider)
    register_provider("algolia", AlgoliaProvider)
    register_provider("baidu", BaiduProvider)
    register_provider("naver", NaverProvider)
    register_provider("sogou", SogouProvider)
    register_provider("bing_web", BingWebProvider)
    register_provider("yahoo_search", YahooSearchProvider)
    register_provider("twitter_search", TwitterSearchProvider)
    register_provider("amazon_search", AmazonSearchProvider)
    register_provider("youtube_search", YouTubeSearchProvider)
    register_provider("reddit_search", RedditSearchProvider)
    register_provider("stackoverflow", StackOverflowProvider)
    register_provider("github_search", GitHubSearchProvider)
    register_provider("hackernews", HackerNewsProvider)
    register_provider("indeed", IndeedProvider)
    register_provider("openstreetmap", OpenStreetMapProvider)
    register_provider("skyscanner", SkyscannerProvider)


_register_builtins()
