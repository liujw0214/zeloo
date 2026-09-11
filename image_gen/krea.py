"""Krea AI image generation provider — FLUX/IP-Adapter/style-presets."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from image_gen.base import ImageProvider, ImageResponse, ImageResult

logger = logging.getLogger(__name__)

_KREA_BASE_URL = "https://api.krea.ai/v1"


class KreaProvider(ImageProvider):
    """Krea AI image generation provider.

    Supports FLUX.1, IP-Adapter, and style presets.
    See https://docs.krea.ai
    """

    name = "krea"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        import os as _os
        super().__init__(api_key or _os.environ.get("KREA_API_KEY", ""), **kwargs)

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{_KREA_BASE_URL}/models",
                    headers={"Authorization": f"Token {self.api_key}"},
                )
                return resp.status_code < 500
        except httpx.RequestError:
            return False

    def generate(
        self,
        prompt: str,
        model: str = "flux",
        width: int = 1024,
        height: int = 1024,
        **kwargs: Any,
    ) -> ImageResponse:
        if not self.api_key:
            raise RuntimeError(
                "Krea API key not set. Set KREA_API_KEY or pass api_key."
            )
        payload: dict[str, Any] = {
            "prompt": prompt,
            "model": model,
            "width": width,
            "height": height,
        }
        for key in ("style", "quality", "n"):
            if key in kwargs:
                payload[key] = kwargs[key]

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{_KREA_BASE_URL}/images/generate",
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[ImageResult] = []
        images = data.get("data", []) if isinstance(data, dict) else []
        for img in images:
            url = img.get("url", "") if isinstance(img, dict) else str(img)
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
