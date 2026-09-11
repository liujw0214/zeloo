"""Web search providers — unified interface for 39+ search engines.

Categories:
- General: Tavily, DuckDuckGo, Brave, SearXNG, Mojeek, Kagi, Bing, Yahoo
- AI-powered: Perplexity, Exa, You.com, Grok, Parallel, Keenable
- Google-based: Google CSE, Serper.dev, SerpAPI
- Chinese: Baidu, 360, Sogou
- Korean: Naver
- Russian: Yandex Search
- Academic: Google Scholar, Semantic Scholar, Arxiv, PubMed
- Hosted search: Algolia
- Scraping: Firecrawl
- Social/Video: Twitter/X, YouTube, Reddit
- Shopping: Amazon
- Developer: StackOverflow, GitHub, HackerNews
- Jobs: Indeed
- Maps: OpenStreetMap
- Travel: Skyscanner
"""

from __future__ import annotations

from web_providers.algolia import AlgoliaProvider
from web_providers.amazon_search import AmazonSearchProvider
from web_providers.arxiv import ArxivProvider
from web_providers.baidu import BaiduProvider
from web_providers.base import (
    SearchProvider,
    SearchResponse,
    SearchResult,
    ValidationError,
)
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
from web_providers.registry import (
    get_provider,
    list_providers,
    register_provider,
)
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

__all__ = [
    "SearchProvider",
    "SearchResult",
    "SearchResponse",
    "ValidationError",
    "TavilyProvider",
    "DuckDuckGoProvider",
    "PerplexityProvider",
    "BraveProvider",
    "ExaProvider",
    "SearXNGProvider",
    "FirecrawlProvider",
    "GoogleCSEProvider",
    "SerperProvider",
    "KagiProvider",
    "YouProvider",
    "ParallelProvider",
    "KeenableProvider",
    "SerpAPIProvider",
    "GrokSearchProvider",
    "YandexSearchProvider",
    "MojeekProvider",
    "Search360Provider",
    "GoogleScholarProvider",
    "SemanticScholarProvider",
    "ArxivProvider",
    "PubMedProvider",
    "AlgoliaProvider",
    "BaiduProvider",
    "NaverProvider",
    "SogouProvider",
    "BingWebProvider",
    "YahooSearchProvider",
    "TwitterSearchProvider",
    "AmazonSearchProvider",
    "YouTubeSearchProvider",
    "RedditSearchProvider",
    "StackOverflowProvider",
    "GitHubSearchProvider",
    "HackerNewsProvider",
    "IndeedProvider",
    "OpenStreetMapProvider",
    "SkyscannerProvider",
    "get_provider",
    "list_providers",
    "register_provider",
]