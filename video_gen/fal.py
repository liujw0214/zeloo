"""FAL.ai video generation provider.

FAL.ai runs a queue-based inference API supporting multiple hosted video
models: Kling, Luma Dream Machine, MiniMax Hailuo, etc.

API docs: https://fal.ai/docs
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

# Default model: Kling 1.6 (high quality, popular)
DEFAULT_MODEL = "fal-ai/kling-video/v1.6/standard/text-to-video"

# Known FAL video model identifiers
SUPPORTED_MODELS = {
    "fal-ai/kling-video/v1.6/standard/text-to-video": {
        "max_duration": 10.0,
        "max_resolution": "1920x1080",
    },
    "fal-ai/kling-video/v1.5/pro/text-to-video": {
        "max_duration": 10.0,
        "max_resolution": "1920x1080",
    },
    "fal-ai/luma-dream-machine": {"max_duration": 5.0, "max_resolution": "1280x720"},
    "fal-ai/minimax-video-01": {"max_duration": 6.0, "max_resolution": "1280x720"},
    "fal-ai/cogvideox-5b": {"max_duration": 6.0, "max_resolution": "1280x720"},
    "fal-ai/stable-video": {"max_duration": 4.0, "max_resolution": "1024x576"},
}

BASE_URL = "https://queue.fal.run"


class FalVideoProvider(VideoProvider):
    """FAL.ai video generation provider (queue-based)."""

    name = "fal"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key=api_key, **kwargs)
        if not self.api_key:
            self.api_key = os.environ.get("FAL_API_KEY") or self.config.get("api_key")
        self.base_url = self.config.get("base_url", BASE_URL)
        self.timeout = self.config.get("timeout", 600.0)
        self.poll_interval = self.config.get("poll_interval", 3.0)

    def validate_credentials(self) -> bool:
        """Check whether FAL_KEY is configured."""
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
        """Generate video via FAL queue API with polling."""
        if not self.validate_credentials():
            raise ValidationError("FAL_API_KEY is required for video generation")
        model_id = model or DEFAULT_MODEL

        # Submit request to FAL queue
        submit_url = f"{self.base_url}/{model_id}"
        headers = {
            "Authorization": f"Key {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "prompt": prompt,
            "duration": str(int(duration_seconds))
            if "kling" in model_id.lower()
            else duration_seconds,
        }
        if negative_prompt:
            body["negative_prompt"] = negative_prompt
        if "x" in resolution:
            _w, _h = resolution.split("x")
            body["width"] = int(_w)
            body["height"] = int(_h)
        if seed is not None:
            body["seed"] = seed

        logger.info("Submitting video generation to FAL: model=%s", model_id)
        if not self.validate_credentials():
            raise ValidationError("FAL_API_KEY is required for video generation")
        assert self.api_key is not None
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(submit_url, json=body, headers=headers)
            response.raise_for_status()
            submission = response.json()
            request_id = submission.get("request_id") or submission.get("id") or ""

            # Poll status endpoint until complete
            video_url = self._poll_result(client, model_id, request_id, headers)

        _parts = resolution.split("x")
        w: int = int(_parts[0]) if len(_parts) > 0 else 1280
        h: int = int(_parts[1]) if len(_parts) > 1 else 720
        results = [
            VideoResult(
                url=video_url,
                duration_seconds=duration_seconds,
                fps=fps,
                width=w,
                height=h,
                format="mp4",
                model=model_id,
                provider=self.name,
                cost_usd=self.estimate_cost(duration_seconds, resolution, model_id),
                seed=seed,
                raw=submission if isinstance(submission, dict) else {},
            )
            for _ in range(num_videos)
        ]

        return VideoResponse(
            results=results,
            provider=self.name,
            model=model_id,
            prompt=prompt,
            cost_usd=sum(r.cost_usd for r in results),
            request_id=str(request_id) if request_id else None,
            raw=submission if isinstance(submission, dict) else {},
        )

    def _poll_result(
        self,
        client: httpx.Client,
        model_id: str,
        request_id: str,
        headers: dict[str, str],
    ) -> str:
        """Poll FAL queue status endpoint until completion."""
        import time

        if not request_id:
            raise ValidationError("FAL queue did not return a request_id")
        status_url = f"{self.base_url}/{model_id}/requests/{request_id}/status"
        result_url = f"{self.base_url}/{model_id}/requests/{request_id}"
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            resp = client.get(status_url, headers=headers)
            if resp.status_code != 200:
                time.sleep(self.poll_interval)
                continue
            data = resp.json()
            status = (data.get("status") or "").lower()
            if status in ("completed", "succeeded", "success"):
                final = client.get(result_url, headers=headers)
                final.raise_for_status()
                payload = final.json()
                # FAL returns video URL inside "video" or "output_url" key
                if isinstance(payload, dict):
                    return (
                        payload.get("video", {}).get("url")
                        or payload.get("output_url")
                        or payload.get("url", "")
                    )
                return ""
            if status in ("failed", "error"):
                raise RuntimeError(f"FAL generation failed: {data}")
            time.sleep(self.poll_interval)
        raise TimeoutError(f"FAL generation timed out after {self.timeout}s")

    def estimate_cost(
        self,
        duration_seconds: float,
        resolution: str = "1280x720",
        model: str | None = None,
        **kwargs: Any,
    ) -> float:
        """Estimate cost in USD.

        Pricing (approximate public rates):
        - Kling 1.6: $0.50 per 5s
        - Luma Dream Machine: $0.32 per 5s
        - Hailuo: $0.28 per 5s
        """
        per_5s = 0.50
        if model and "luma" in model.lower():
            per_5s = 0.32
        elif model and "minimax" in model.lower():
            per_5s = 0.28
        elif model and "cogvideox" in model.lower():
            per_5s = 0.20
        elif model and "stable-video" in model.lower():
            per_5s = 0.15
        multiplier = 2.0 if "1080" in resolution or "1920" in resolution else 1.0
        return round((duration_seconds / 5.0) * per_5s * multiplier, 4)


__all__ = ["FalVideoProvider", "DEFAULT_MODEL", "SUPPORTED_MODELS"]
