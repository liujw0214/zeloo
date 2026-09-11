"""Stability AI image generation provider."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from image_gen.base import ImageProvider, ImageResponse, ImageResult

logger = logging.getLogger(__name__)

STABILITY_API = "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image"


class StabilityProvider(ImageProvider):
    """Stability AI image generation.

    Supports SDXL and SD3 models.
    Requires a ``STABILITY_API_KEY`` environment variable or ``api_key`` argument.
    See https://platform.stability.ai
    """

    name = "stability"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = "stable-diffusion-xl-1024-v1-0",
        **kwargs: Any,
    ) -> None:
        import os

        super().__init__(api_key or os.environ.get("STABILITY_API_KEY", ""), **kwargs)
        self.model = model

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    "https://api.stability.ai/v1/account",
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
        seed: int | None = None,
        num_images: int = 1,
        **kwargs: Any,
    ) -> ImageResponse:
        width, height = self._parse_size(size)
        text_prompts = [{"text": prompt, "weight": 1.0}]
        payload: dict[str, Any] = {
            "text_prompts": text_prompts,
            "cfg_scale": kwargs.get("guidance_scale", 7),
            "height": height,
            "width": width,
            "samples": num_images,
        }
        if style:
            payload["style_preset"] = style
        if seed is not None:
            payload["seed"] = seed

        endpoint = f"https://api.stability.ai/v1/generation/{model or self.model}/text-to-image"
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[ImageResult] = []
        for artifact in data.get("artifacts", []):
            b64 = artifact.get("base64", "")
            if b64:
                img_url = f"data:image/png;base64,{b64}"
            else:
                img_url = ""
            results.append(
                ImageResult(
                    url=img_url,
                    width=width,
                    height=height,
                    model=model or self.model,
                    provider=self.name,
                    seed=artifact.get("seed"),
                    raw=artifact,
                )
            )

        return ImageResponse(
            results=results,
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
            w = int(parts[0])
            h = int(parts[1])
            return w, h
        except ValueError:
            return 1024, 1024
