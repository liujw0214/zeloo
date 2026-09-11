"""OpenAI DALL-E image generation provider."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from image_gen.base import ImageProvider, ImageResponse, ImageResult

logger = logging.getLogger(__name__)


class DalleProvider(ImageProvider):
    """OpenAI DALL-E image generation.

    Supports DALL-E 2 and DALL-E 3 models.
    Uses ``OPENAI_API_KEY`` environment variable or ``api_key`` argument.
    See https://platform.openai.com/docs/guides/images
    """

    name = "dalle"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = "dall-e-3",
        **kwargs: Any,
    ) -> None:
        import os

        super().__init__(api_key or os.environ.get("OPENAI_API_KEY", ""), **kwargs)
        self.model = model

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return resp.status_code in (200, 401, 403)
        except httpx.RequestError:
            return False

    def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        size: str = "1024x1024",
        style: str | None = None,
        num_images: int = 1,
        **kwargs: Any,
    ) -> ImageResponse:
        model_name = model or self.model
        payload: dict[str, Any] = {
            "model": model_name,
            "prompt": prompt,
            "n": num_images,
            "size": self._normalise_size(size),
        }
        if model_name.startswith("dall-e-3") and style:
            if style in ("natural", "vivid"):
                payload["style"] = style

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[ImageResult] = []
        for item in data.get("data", []):
            results.append(
                ImageResult(
                    url=item.get("url", ""),
                    revised_prompt=item.get("revised_prompt"),
                    model=model_name,
                    provider=self.name,
                    raw=item,
                )
            )

        return ImageResponse(
            results=results,
            provider=self.name,
            model=model_name,
            prompt=prompt,
            raw=data,
        )

    @staticmethod
    def _normalise_size(size: str) -> str:
        size_map = {
            "256x256": "256x256",
            "512x512": "512x512",
            "1024x1024": "1024x1024",
            "1024x1792": "1024x1792",
            "1792x1024": "1792x1024",
        }
        return size_map.get(size, "1024x1024")
