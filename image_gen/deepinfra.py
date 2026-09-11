"""DeepInfra image generation provider — flux/sdxl via REST API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from image_gen.base import ImageProvider, ImageResponse, ImageResult

logger = logging.getLogger(__name__)

_DEEPINFRA_URL = "https://api.deepinfra.com/v1/interference/inference"


class DeepInfraProvider(ImageProvider):
    """DeepInfra image generation provider.

    Supports FLUX.1-dev, FLUX.1-schnell, SDXL via DeepInfra API.
    See https://deepinfra.com/models/image-generation
    """

    name = "deepinfra"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        import os as _os
        super().__init__(api_key or _os.environ.get("DEEPINFRA_API_KEY", ""), **kwargs)

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    "https://api.deepinfra.com/v1/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return resp.status_code < 500
        except httpx.RequestError:
            return False

    def _estimate_cost(self, model: str) -> float:
        rates = {
            "black-forest-labs/FLUX.1-dev": 0.015,
            "black-forest-labs/FLUX.1-schnell": 0.003,
            "stabilityai/stable-diffusion-xl-base-1.0": 0.005,
        }
        return rates.get(model, 0.005)

    def generate(
        self,
        prompt: str,
        model: str = "black-forest-labs/FLUX.1-dev",
        width: int = 1024,
        height: int = 1024,
        **kwargs: Any,
    ) -> ImageResponse:
        if not self.api_key:
            raise RuntimeError(
                "DeepInfra API key not set. Set DEEPINFRA_API_KEY or pass api_key."
            )

        payload = {
            "prompt": prompt,
            "model": model,
            "width": width,
            "height": height,
            "num_images": kwargs.get("n", 1),
        }
        if kwargs.get("negative_prompt"):
            payload["negative_prompt"] = kwargs["negative_prompt"]
        if kwargs.get("seed"):
            payload["seed"] = kwargs["seed"]
        if kwargs.get("guidance_scale"):
            payload["guidance_scale"] = kwargs["guidance_scale"]
        if kwargs.get("num_inference_steps"):
            payload["num_inference_steps"] = kwargs["num_inference_steps"]

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                _DEEPINFRA_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[ImageResult] = []
        images = data.get("images", [])
        for img_data in images:
            if isinstance(img_data, dict):
                url = img_data.get("url", "")
            else:
                url = ""

            results.append(
                ImageResult(
                    url=url,
                    width=width,
                    height=height,
                    model=model,
                    provider=self.name,
                    cost_usd=self._estimate_cost(model),
                    seed=kwargs.get("seed"),
                )
            )

        return ImageResponse(
            results=results,
            provider=self.name,
            model=model,
            prompt=prompt,
            cost_usd=len(results) * self._estimate_cost(model),
            raw=data,
        )
