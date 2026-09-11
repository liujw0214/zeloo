"""Image provider abstract base class and shared types."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class ImageModel(StrEnum):
    """Standardised image model identifiers mapped per provider."""

    FLUX_PRO = "flux-pro"
    FLUX_DEV = "flux-dev"
    FLUX_SCHNELL = "flux-schnell"
    SDXL = "sdxl"
    SD3 = "sd3"
    DALLE_3 = "dall-e-3"
    DALLE_2 = "dall-e-2"
    REALISTIC = "realistic"


class ImageStyle(StrEnum):
    """Standardised image style presets."""

    NATURAL = "natural"
    VIVID = "vivid"
    ARTISTIC = "artistic"
    PHOTOREALISTIC = "photorealistic"
    ANIME = "anime"
    ABSTRACT = "abstract"


@dataclass
class ImageResult:
    """A single generated image from :meth:`ImageProvider.generate`."""

    url: str
    width: int = 1024
    height: int = 1024
    revised_prompt: str | None = None
    model: str = ""
    provider: str = ""
    cost_usd: float = 0.0
    seed: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "width": self.width,
            "height": self.height,
            "revised_prompt": self.revised_prompt,
            "model": self.model,
            "provider": self.provider,
            "cost_usd": self.cost_usd,
            "seed": self.seed,
        }


@dataclass
class ImageResponse:
    """Structured response returned by :meth:`ImageProvider.generate`."""

    results: list[ImageResult] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    prompt: str = ""
    cost_usd: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [r.to_dict() for r in self.results],
            "provider": self.provider,
            "model": self.model,
            "prompt": self.prompt,
            "cost_usd": self.cost_usd,
        }


class ValidationError(Exception):
    """Raised when API credentials or configuration are invalid."""


class ImageProvider(ABC):
    """Abstract base for all image generation providers.

    Subclasses must set :attr:`name` and implement :meth:`generate`,
    :meth:`validate_credentials`, and optionally :meth:`variations`.
    """

    name: str = "base"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        self.api_key = api_key
        self.config = kwargs

    @abstractmethod
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
        """Generate one or more images from a text prompt.

        Args:
            prompt: The text description of the desired image.
            model: Provider-specific model identifier.
            size: Image dimensions in WxH format (e.g. "1024x1024").
            style: Style preset identifier.
            seed: Fixed random seed for reproducibility.
            num_images: Number of images to generate (1-4 typically).

        Returns:
            An :class:`ImageResponse` containing the generated image(s).
        """

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Return True if the configured API key is valid."""

    def variations(
        self,
        image_url: str,
        *,
        model: str | None = None,
        size: str = "1024x1024",
        count: int = 4,
        **kwargs: Any,
    ) -> ImageResponse:
        """Generate variations of an existing image.

        Default implementation re-prompts with the original URL as
        reference, varying the seed to produce *count* alternative
        generations. Subclasses that support native variation APIs
        (e.g. OpenAI) should override this.
        """
        import random
        prompt = f"Variation of image: {image_url}"
        response = self.generate(
            prompt,
            model=model,
            size=size,
            num_images=count,
            seed=kwargs.pop("seed", random.randint(1000, 999999)),
            **kwargs,
        )
        return response
