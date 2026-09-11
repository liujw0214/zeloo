"""DeepInfra video generation provider.

Supports Hunyuan Video, Wan 2.1, Mochi, and LTX-Video models through
the DeepInfra cloud API. DeepInfra exposes open-source video diffusion
models at competitive prices.

API docs: https://deepinfra.com/docs
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

# Default model: Hunyuan Video (high quality, 5s default)
DEFAULT_MODEL = "tencent/HunyuanVideo"

# Known DeepInfra video model identifiers
SUPPORTED_MODELS = {
    "tencent/HunyuanVideo": {"max_duration": 5.0, "max_resolution": "1280x720"},
    "Wan-AI/Wan2.1-T2V-14B": {"max_duration": 6.0, "max_resolution": "1280x720"},
    "genmo/mochi-1-preview": {"max_duration": 5.4, "max_resolution": "1280x720"},
    "Lightricks/LTX-Video": {"max_duration": 5.0, "max_resolution": "1280x720"},
}

BASE_URL = "https://api.deepinfra.com/v1"


class DeepInfraVideoProvider(VideoProvider):
    """DeepInfra video generation provider."""

    name = "deepinfra"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key=api_key, **kwargs)
        # Read API key from parameter, env, or config (in that order)
        if not self.api_key:
            self.api_key = os.environ.get("DEEPINFRA_API_KEY") or self.config.get("api_key")
        self.base_url = self.config.get("base_url", BASE_URL)
        self.timeout = self.config.get("timeout", 600.0)
        self.poll_interval = self.config.get("poll_interval", 5.0)

    def validate_credentials(self) -> bool:
        """Check whether an API key is configured.

        DeepInfra requires an API key; this method only verifies presence.
        """
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
        """Generate video via DeepInfra async inference endpoint."""
        if not self.validate_credentials():
            raise ValidationError("DEEPINFRA_API_KEY is required for video generation")
        assert self.api_key is not None
        model_id = model or DEFAULT_MODEL
        if model_id not in SUPPORTED_MODELS:
            logger.warning(
                "Unknown model %s, will attempt anyway (supported: %s)",
                model_id,
                list(SUPPORTED_MODELS.keys()),
            )

        request_body = {
            "prompt": prompt,
            "num_frames": int(duration_seconds * fps),
            "height": int(resolution.split("x")[1]) if "x" in resolution else 720,
            "width": int(resolution.split("x")[0]) if "x" in resolution else 1280,
        }
        if negative_prompt:
            request_body["negative_prompt"] = negative_prompt
        if seed is not None:
            request_body["seed"] = seed

        url = f"{self.base_url}/inference/{model_id}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        logger.info("Submitting video generation to DeepInfra: model=%s", model_id)
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=request_body, headers=headers)
            response.raise_for_status()
            data = response.json()

        # DeepInfra returns request_id; poll until complete
        request_id = data.get("request_id") or data.get("id")
        if request_id:
            video_url = self._poll_result(client, model_id, request_id, headers)
        else:
            video_url = data.get("output_url") or data.get("video_url") or ""

        results = [
            VideoResult(
                url=video_url,
                duration_seconds=duration_seconds,
                fps=fps,
                width=int(str(request_body["width"])),
                height=int(str(request_body["height"])),
                format="mp4",
                model=model_id,
                provider=self.name,
                cost_usd=self.estimate_cost(duration_seconds, resolution, model_id),
                seed=seed,
                raw=data if isinstance(data, dict) else {"response": str(data)},
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
            raw=data if isinstance(data, dict) else {},
        )

    def _poll_result(
        self,
        client: httpx.Client,
        model_id: str,
        request_id: str,
        headers: dict[str, str],
    ) -> str:
        """Poll the request status until completion."""
        import time

        url = f"{self.base_url}/inference/{model_id}/get_result"
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            resp = client.post(url, json={"request_id": request_id}, headers=headers)
            if resp.status_code != 200:
                time.sleep(self.poll_interval)
                continue
            data = resp.json()
            status = (data.get("status") or "").lower()
            if status in ("succeeded", "success", "complete", "completed"):
                return (
                    data.get("output_url")
                    or data.get("video_url")
                    or data.get("result", {}).get("url", "")
                )
            if status in ("failed", "error"):
                raise RuntimeError(f"DeepInfra generation failed: {data}")
            time.sleep(self.poll_interval)
        raise TimeoutError(f"DeepInfra generation timed out after {self.timeout}s")

    def estimate_cost(
        self,
        duration_seconds: float,
        resolution: str = "1280x720",
        model: str | None = None,
        **kwargs: Any,
    ) -> float:
        """Estimate cost based on model and duration.

        Pricing (approximate, public 2026 rates):
        - Hunyuan Video: $0.30 / second
        - Wan 2.1: $0.40 / second
        - Mochi: $0.20 / second
        - LTX-Video: $0.15 / second
        """
        per_second = 0.30
        if model and "Wan" in model:
            per_second = 0.40
        elif model and "mochi" in model.lower():
            per_second = 0.20
        elif model and "LTX" in model:
            per_second = 0.15
        multiplier = 2.0 if "1080" in resolution else 1.0
        return round(duration_seconds * per_second * multiplier, 4)


__all__ = ["DeepInfraVideoProvider", "DEFAULT_MODEL", "SUPPORTED_MODELS"]
