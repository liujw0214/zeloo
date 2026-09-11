"""xAI Grok image generation provider — flux-sana / grok-2-image."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from image_gen.base import ImageProvider, ImageResponse, ImageResult

logger = logging.getLogger(__name__)

_XAI_BASE_URL = "https://api.x.ai/v1"


class GrokImageProvider(ImageProvider):
    """xAI Grok image generation provider.

    Supports grok-2-image model via xAI API.
    See https://docs.x.ai/docs
    """

    name = "grok_image"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        import os as _os
        super().__init__(api_key or _os.environ.get("XAI_API_KEY", ""), **kwargs)

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{_XAI_BASE_URL}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return resp.status_code < 500
        except httpx.RequestError:
            return False

    def generate(
        self,
        prompt: str,
        model: str = "grok-2-image",
        width: int = 1024,
        height: int = 1024,
        **kwargs: Any,
    ) -> ImageResponse:
        if not self.api_key:
            raise RuntimeError(
                "xAI API key not set. Set XAI_API_KEY or pass api_key."
            )
        payload: dict[str, Any] = {
            "prompt": prompt,
            "model": model,
            "n": kwargs.get("n", 1),
        }
        for key in ("quality", "response_format"):
            if key in kwargs:
                payload[key] = kwargs[key]

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{_XAI_BASE_URL}/images/generations",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[ImageResult] = []
        for img in data.get("data", []):
            url = img.get("url", "")
            revised = img.get("revised_prompt")
            results.append(
                ImageResult(
                    url=url,
                    width=width,
                    height=height,
                    revised_prompt=revised,
                    model=model,
                    provider=self.name,
                    cost_usd=0.03,
                )
            )

        return ImageResponse(
            results=results,
            provider=self.name,
            model=model,
            prompt=prompt,
            cost_usd=len(results) * 0.03,
            raw=data,
        )
