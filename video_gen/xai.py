"""xAI Grok video generation provider.

xAI exposes video generation via a Grok model. The exact API surface
is evolving — this provider is implemented defensively so it returns a
helpful error if the endpoint is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from video_gen.base import VideoProvider, VideoResponse, VideoResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.x.ai/v1"
_DEFAULT_MODEL = "grok-2-video"


class XaiVideoProvider(VideoProvider):
    """Provider implementation for xAI Grok video generation."""

    name = "xai"
    default_model = _DEFAULT_MODEL
    default_duration = 5

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        if self.api_key is None:
            self.api_key = os.environ.get("XAI_API_KEY")

    def generate(
        self,
        prompt: str,
        **kwargs: Any,
    ) -> VideoResponse:
        if not self.api_key:
            return VideoResponse(
                results=[
                    VideoResult(
                        url="",
                        model=self.default_model,
                        provider=self.name,
                        raw={"error": "XAI_API_KEY not set"},
                    )
                ],
                provider=self.name,
                model=self.default_model,
                prompt=prompt,
                cost_usd=0.0,
            )
        duration = kwargs.get("duration", 5)
        result = self.generate_video(prompt, duration=duration, **kwargs)
        return VideoResponse(
            results=[result],
            provider=self.name,
            model=self.default_model,
            prompt=prompt,
            cost_usd=0.0,
        )

    def generate_video(
        self,
        prompt: str,
        duration: int = 5,
        model: str | None = None,
        **kwargs: Any,
    ) -> VideoResult:
        """Submit a video generation request to the xAI Grok API."""
        if not self.api_key:
            return VideoResult(
                url="",
                model=model or self.default_model,
                provider=self.name,
                raw={"error": "XAI_API_KEY not set"},
            )

        target_model = model or self.default_model
        url = f"{_BASE_URL}/video/generations"
        body = json.dumps(
            {
                "model": target_model,
                "prompt": prompt,
                "duration": duration,
            }
        ).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=300.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return VideoResult(
                url="",
                model=target_model,
                provider=self.name,
                raw={"error": f"xAI HTTP {exc.code}: video endpoint may not be available"},
            )
        except urllib.error.URLError as exc:
            return VideoResult(
                url="",
                model=target_model,
                provider=self.name,
                raw={"error": f"xAI connection error: {exc.reason}"},
            )

        video_url = ""
        if isinstance(data, dict):
            video_url = (
                data.get("url", "")
                or (data.get("video") or {}).get("url", "")
                or (data.get("data") or [{}])[0].get("url", "")
            )

        return VideoResult(
            url=video_url,
            model=target_model,
            provider=self.name,
            duration_seconds=float(duration),
            raw=data,
        )

    def validate_credentials(self) -> bool:
        """Return True if a key is set; xAI doesn't expose a cheap ping."""
        return bool(self.api_key)

    def estimate_cost(self, duration: int, model: str | None = None) -> float:
        """Conservative estimate: $1 per 5s clip."""
        return round(duration / 5 * 1.00, 4)
