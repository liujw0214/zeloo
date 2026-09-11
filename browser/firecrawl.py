"""Firecrawl provider — web crawling and content extraction."""

from __future__ import annotations

import logging
import time as _time

import httpx

from browser.base import BrowserProvider, CrawlResult, PageSnapshot

logger = logging.getLogger(__name__)

API_URL = "https://api.firecrawl.dev/v0"


class FirecrawlProvider(BrowserProvider):
    """Firecrawl AI crawler.

    Requires FIRECRAWL_API_KEY env var or api_key arg.
    """

    name = "firecrawl"

    def __init__(self, api_key=None, **kwargs):
        import os
        super().__init__(api_key or os.environ.get("FIRECRAWL_API_KEY", ""), **kwargs)

    def validate_credentials(self):
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    API_URL + "/account",
                    headers={"Authorization": "Bearer " + self.api_key},
                )
                return resp.status_code in (200, 401, 402, 403)
        except httpx.RequestError:
            return False

    def navigate(self, url, *, wait_for=None, timeout=30, **kwargs):
        payload = {
            "url": url,
            "pageOptions": {"onlyMainContent": True},
        }
        if wait_for:
            payload["pageOptions"]["waitForSelector"] = wait_for
        payload.update(kwargs)
        with httpx.Client(timeout=float(timeout) + 5.0) as client:
            resp = client.post(
                API_URL + "/scrape",
                headers={"Authorization": "Bearer " + self.api_key},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        meta = data.get("metadata", {})
        return PageSnapshot(
            url=url,
            title=meta.get("title", ""),
            content=data.get("content", ""),
            html="",
            status_code=meta.get("statusCode", 200),
            error=data.get("error"),
            metadata=data,
        )

    def crawl(self, url, *, depth=1, max_pages=10, **kwargs):
        start = _time.monotonic()
        payload = {
            "urls": [url],
            "crawlOptions": {"maxDepth": depth, "limit": max_pages},
        }
        payload.update(kwargs)
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                API_URL + "/crawl",
                headers={"Authorization": "Bearer " + self.api_key},
                json=payload,
            )
            resp.raise_for_status()
            job = resp.json()
        job_id = job.get("jobId", "")
        pages = []
        for _ in range(30):
            _time.sleep(3)
            with httpx.Client(timeout=15.0) as client:
                status_resp = client.get(
                    API_URL + "/crawl/status/" + job_id,
                    headers={"Authorization": "Bearer " + self.api_key},
                )
                status_resp.raise_for_status()
                status_data = status_resp.json()
            if status_data.get("status") == "completed":
                for page in status_data.get("data", []):
                    pm = page.get("metadata", {})
                    pages.append(
                        PageSnapshot(
                            url=page.get("url", ""),
                            title=pm.get("title", ""),
                            content=page.get("content", ""),
                            html="",
                            status_code=pm.get("statusCode", 200),
                            metadata=pm,
                        )
                    )
                break
            elif status_data.get("status") == "failed":
                break
        duration_ms = int((_time.monotonic() - start) * 1000)
        return CrawlResult(
            pages=pages,
            provider=self.name,
            crawl_url=url,
            depth=depth,
            total_pages=len(pages),
            duration_ms=duration_ms,
        )

    def screenshot(self, url, *, full_page=False, fmt="png", **kwargs):
        raise NotImplementedError(
            "Firecrawl screenshot not available via API. Use navigate() to get content."
        )
