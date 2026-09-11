"""Meta AI image generation provider — seamless-m4t / imagica integration."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from image_gen.base import ImageProvider, ImageResponse, ImageResult

logger = logging.getLogger(__name__)

_META_BASE_URL = "https://api.meta.ai/v1"


class MetaAIProvider(ImageProvider):
    """Meta AI image generation provider.

    Supports Meta's image generation models via Meta AI API.
    See https://developers.meta.com
    """

    name = "meta_ai"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        import os as _os
        super().__init__(api_key or _os.environ.get("META_API_KEY", ""), **kwargs)

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{_META_BASE_URL}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return resp.status_code < 500
        except httpx.RequestError:
            return False

    def generate(
        self,
        prompt: str,
        model: str = "meta-imagen-3",
        width: int = 1024,
        height: int = 1024,
        **kwargs: Any,
    ) -> ImageResponse:
        if not self.api_key:
            raise RuntimeError(
                "Meta API key not set. Set META_API_KEY or pass api_key."
            )
        payload: dict[str, Any] = {
            "prompt": prompt,
            "model": model,
            "width": width,
            "height": height,
        }
        for key in ("n", "style"):
            if key in kwargs:
                payload[key] = kwargs[key]

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{_META_BASE_URL}/images/generations",
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
            results.append(
                ImageResult(
                    url=url,
                    width=width,
                    height=height,
                    model=model,
                    provider=self.name,
                    cost_usd=0.01,
                )
            )

        return ImageResponse(
            results=results,
            provider=self.name,
            model=model,
            prompt=prompt,
            cost_usd=len(results) * 0.01,
            raw=data,
        )
