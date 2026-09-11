"""FAL image generation provider — Flux / SDXL via FAL queue API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from image_gen.base import ImageProvider, ImageResponse, ImageResult

logger = logging.getLogger(__name__)

FAL_IMAGE_API = "https://queue.fal.run/fal-ai/flux-schnell"


class FalProvider(ImageProvider):
    """FAL queue API image generation.

    Supports Flux (pro/dev/schnell), SDXL, and Realistic models.
    Requires a ``FAL_API_KEY`` environment variable or ``api_key`` argument.
    See https://fal.run/docs/image-generation
    """

    name = "fal"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = "fal-ai/flux-schnell",
        **kwargs: Any,
    ) -> None:
        import os

        super().__init__(api_key or os.environ.get("FAL_API_KEY", ""), **kwargs)
        self.model = model

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    "https://queue.fal.run/fal-ai/flux-schnell",
                    headers={"Authorization": f"Key {self.api_key}"},
                )
                return resp.status_code in (200, 400, 401, 403)
        except httpx.RequestError:
            return False

    def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        size: str = "1024x1024",
        **kwargs: Any,
    ) -> ImageResponse:
        width_s, height_s = self._parse_size(size)
        payload: dict[str, Any] = {
            "prompt": prompt,
            "image_size": {"width": width_s, "height": height_s},
            "num_images": 1,
        }
        if model:
            payload["model_name"] = model
        if "seed" in kwargs:
            payload["seed"] = kwargs["seed"]
        if "guidance_scale" in kwargs:
            payload["guidance_scale"] = kwargs["guidance_scale"]

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                FAL_IMAGE_API,
                headers={
                    "Authorization": f"Key {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        images = data.get("images", [])
        image_url = images[0].get("url", "") if images else ""
        revised = data.get("revised_prompt")

        result = ImageResult(
            url=image_url,
            width=width_s,
            height=height_s,
            revised_prompt=revised,
            model=model or self.model,
            provider=self.name,
            raw=data,
        )

        return ImageResponse(
            results=[result],
            provider=self.name,
            model=model or self.model,
            prompt=prompt,
            raw=data,
        )

    @staticmethod
    def _parse_size(size: str) -> tuple[int, int]:
        parts = size.lower().split("x")
        if len(parts) != 2:
            return 1024, 1024
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return 1024, 1024
