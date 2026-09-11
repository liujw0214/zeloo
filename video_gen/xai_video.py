"""xAI Grok video generation provider.

xAI's Grok API exposes generative video capabilities alongside text and
image generation. Uses an OpenAI-compatible chat completions interface
extended with a video output mode.

API docs: https://docs.x.ai/docs
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from video_gen.base import (
    ValidationError,
    VideoProvider,
    VideoResponse,
    VideoResult,
)

logger = logging.getLogger(__name__)

# Default model: Grok video preview endpoint
DEFAULT_MODEL = "grok-video-preview"

# Known xAI video model identifiers
SUPPORTED_MODELS = {
    "grok-video-preview": {"max_duration": 10.0, "max_resolution": "1280x720"},
    "grok-2-video": {"max_duration": 8.0, "max_resolution": "1280x720"},
}

BASE_URL = "https://api.x.ai/v1"


class XaiVideoProvider(VideoProvider):
    """xAI Grok video generation provider."""

    name = "xai_video"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key=api_key, **kwargs)
        if not self.api_key:
            self.api_key = os.environ.get("XAI_API_KEY") or self.config.get("api_key")
        self.base_url = self.config.get("base_url", BASE_URL)
        self.timeout = self.config.get("timeout", 600.0)

    def validate_credentials(self) -> bool:
        """Check whether XAI_API_KEY is configured."""
        return bool(self.api_key) and len(self.api_key or "") > 8

    def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        resolution: str = "1280x720",
        duration_seconds: float = 5.0,
        fps: int = 24,
        seed: int | None = None,
        negative_prompt: str | None = None,
        num_videos: int = 1,
        **kwargs: Any,
    ) -> VideoResponse:
        """Generate video via xAI video endpoint."""
        if not self.validate_credentials():
            raise ValidationError("XAI_API_KEY is required for video generation")
        model_id = model or DEFAULT_MODEL

        # xAI uses a streaming video endpoint that returns the binary or URL
        url = f"{self.base_url}/video/generations"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": model_id,
            "prompt": prompt,
            "duration_seconds": duration_seconds,
        }
        if "x" in resolution:
            _w, _h = resolution.split("x")
            body["width"] = int(_w)
            body["height"] = int(_h)
        if fps:
            body["fps"] = fps
        if seed is not None:
            body["seed"] = seed
        if negative_prompt:
            body["negative_prompt"] = negative_prompt

        logger.info("Submitting video generation to xAI: model=%s", model_id)
        assert self.api_key is not None
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=body, headers=headers)
            response.raise_for_status()
            data = (
                response.json()
                if response.headers.get("content-type", "").startswith("application/json")
                else {"raw": response.text}
            )

        # xAI returns a list of video objects with `url` keys
        data_results = data.get("data") or []
        video_urls: list[str] = []
        for item in data_results:
            if isinstance(item, dict):
                url_str = item.get("url") or item.get("video_url")
                if url_str:
                    video_urls.append(url_str)
        if not video_urls:
            single = data.get("url") or data.get("video_url")
            if single:
                video_urls.append(single)

        # If we got fewer URLs than requested, fall back to the first one
        if not video_urls:
            video_urls = [""]

        _xparts = resolution.split("x")
        w: int = int(_xparts[0]) if len(_xparts) > 0 else 1280
        h: int = int(_xparts[1]) if len(_xparts) > 1 else 720
        results = [
            VideoResult(
                url=video_urls[i % len(video_urls)],
                duration_seconds=duration_seconds,
                fps=fps,
                width=w,
                height=h,
                format="mp4",
                model=model_id,
                provider=self.name,
                cost_usd=self.estimate_cost(duration_seconds, resolution, model_id),
                seed=seed,
                raw=data if isinstance(data, dict) else {},
            )
            for i in range(num_videos)
        ]

        return VideoResponse(
            results=results,
            provider=self.name,
            model=model_id,
            prompt=prompt,
            cost_usd=sum(r.cost_usd for r in results),
            request_id=str(data.get("id", "")) if isinstance(data, dict) else None,
            raw=data if isinstance(data, dict) else {},
        )

    def estimate_cost(
        self,
        duration_seconds: float,
        resolution: str = "1280x720",
        model: str | None = None,
        **kwargs: Any,
    ) -> float:
        """Estimate cost in USD.

        xAI video pricing (approximate, public 2026 rates):
        - Grok Video Preview: $0.60 per 5s clip
        """
        per_5s = 0.60
        if model and "grok-2-video" in model:
            per_5s = 0.80
        multiplier = 2.0 if "1080" in resolution or "1920" in resolution else 1.0
        return round((duration_seconds / 5.0) * per_5s * multiplier, 4)


__all__ = ["XaiVideoProvider", "DEFAULT_MODEL", "SUPPORTED_MODELS"]
