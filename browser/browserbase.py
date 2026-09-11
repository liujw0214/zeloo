"""BrowserBase provider — cloud browser infrastructure."""

from __future__ import annotations

import logging
import re as _re
import time as _time

import httpx

from browser.base import BrowserProvider, CrawlResult, PageSnapshot

logger = logging.getLogger(__name__)

BROWSERBASE_API = "https://www.browserbase.com/api"


class BrowserBaseProvider(BrowserProvider):
    name = "browserbase"

    def __init__(
        self,
        api_key=None,
        *,
        project_id=None,
        **kwargs,
    ):
        import os
        super().__init__(api_key or os.environ.get("BROWSERBASE_API_KEY", ""), **kwargs)
        self.project_id = project_id or os.environ.get("BROWSERBASE_PROJECT_ID", "")

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{BROWSERBASE_API}/projects/{self.project_id}",
                    headers={"X-API-Key": self.api_key},
                )
                return resp.status_code in (200, 401, 403, 404)
        except httpx.RequestError:
            return False

    def navigate(
        self,
        url: str,
        *,
        wait_for=None,
        timeout: int = 30,
        **kwargs,
    ) -> PageSnapshot:
        payload = {"url": url, "timeout": timeout}
        if wait_for:
            payload["waitForSelector"] = wait_for
        payload.update(kwargs)
        headers = {"X-API-Key": self.api_key, "Content-Type": "application/json"}

        with httpx.Client(timeout=float(timeout) + 5.0) as client:
            resp = client.post(
                f"{BROWSERBASE_API}/sessions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            session_data = resp.json()
            session_id = session_data.get("id", "")
            live_url = (
                session_data.get("debuggerUrl") or session_data.get("websocketUrl", "")
            )

            get_resp = client.get(
                f"{BROWSERBASE_API}/sessions/{session_id}",
                headers=headers,
                timeout=float(timeout),
            )
            get_resp.raise_for_status()
            data_out = get_resp.json()

        events = data_out.get("events", [])
        page = events[0] if events else {}
        return PageSnapshot(
            url=url,
            title=data_out.get("title", ""),
            content=data_out.get("textContent") or page.get("textContent", ""),
            html=data_out.get("html") or page.get("html", ""),
            status_code=data_out.get("statusCode", 200),
            metadata={"sessionId": session_id, "liveUrl": live_url},
        )

    def crawl(
        self,
        url: str,
        *,
        depth: int = 1,
        max_pages: int = 10,
        **kwargs,
    ) -> CrawlResult:
        start = _time.monotonic()
        pages: list[PageSnapshot] = []
        seen: set = set()
        queue: list = [(url, 0)]

        while queue:
            current_url, current_depth = queue.pop(0)
            if current_depth > depth or len(pages) >= max_pages:
                continue
            if current_url in seen:
                continue
            seen.add(current_url)
            try:
                snapshot = self.navigate(current_url, **kwargs)
                pages.append(snapshot)
                for link in self._extract_links(snapshot):
                    if link not in seen and len(pages) < max_pages:
                        queue.append((link, current_depth + 1))
            except Exception as exc:
                pages.append(PageSnapshot(url=current_url, error=str(exc)))

        duration_ms = int((_time.monotonic() - start) * 1000)
        return CrawlResult(
            pages=pages,
            provider=self.name,
            crawl_url=url,
            depth=depth,
            total_pages=len(pages),
            duration_ms=duration_ms,
        )

    def screenshot(
        self,
        url: str,
        *,
        full_page: bool = False,
        format: str = "png",
        **kwargs,
    ) -> bytes:
        snapshot = self.navigate(url, **kwargs)
        screenshot_data = snapshot.metadata.get("screenshot")
        if screenshot_data:
            return screenshot_data
        raise NotImplementedError(
            "BrowserBase screenshot requires the screenshot add-on. "
            "Use navigate() to get page content instead."
        )

    @staticmethod
    def _extract_links(snapshot: PageSnapshot) -> list[str]:
        hrefs = _re.findall(r'href=["\'](https?://[^"\']+)["\']', snapshot.html)
        return list(dict.fromkeys(hrefs))
