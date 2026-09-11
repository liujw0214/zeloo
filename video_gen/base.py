"""Video provider abstract base class and shared types."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class VideoModel(StrEnum):
    """Standardised video model identifiers mapped per provider."""

    # DeepInfra open-source models
    HUNYUAN_VIDEO = "hunyuan-video"
    WAN_2_1 = "wan-2.1"
    MOCHI = "mochi"
    LTX_VIDEO = "ltx-video"

    # FAL hosted models
    FAL_KLING = "fal-kling"
    FAL_LUMA = "fal-luma"
    FAL_MINIMAX = "fal-minimax"

    # xAI
    XAI_GROK_VIDEO = "xai-grok-video"


class VideoResolution(StrEnum):
    """Standardised video resolution presets."""

    SD_480 = "480p"
    HD_720 = "720p"
    FHD_1080 = "1080p"
    PORTRAIT_720 = "720x1280"
    PORTRAIT_1080 = "1080x1920"
    LANDSCAPE_1280 = "1280x720"
    LANDSCAPE_1920 = "1920x1080"
    SQUARE = "1024x1024"


class VideoFormat(StrEnum):
    """Output container/codec presets."""

    MP4_H264 = "mp4_h264"
    MP4_H265 = "mp4_h265"
    WEBM_VP9 = "webm_vp9"
    GIF = "gif"


@dataclass
class VideoResult:
    """A single generated video from :meth:`VideoProvider.generate`."""

    url: str
    duration_seconds: float = 5.0
    fps: int = 24
    width: int = 1280
    height: int = 720
    format: str = "mp4"
    model: str = ""
    provider: str = ""
    cost_usd: float = 0.0
    seed: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "duration_seconds": self.duration_seconds,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "model": self.model,
            "provider": self.provider,
            "cost_usd": self.cost_usd,
            "seed": self.seed,
        }


@dataclass
class VideoResponse:
    """Structured response returned by :meth:`VideoProvider.generate`."""

    results: list[VideoResult] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    prompt: str = ""
    cost_usd: float = 0.0
    request_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [r.to_dict() for r in self.results],
            "provider": self.provider,
            "model": self.model,
            "prompt": self.prompt,
            "cost_usd": self.cost_usd,
            "request_id": self.request_id,
        }


class ValidationError(Exception):
    """Raised when API credentials or configuration are invalid."""


class VideoProvider(ABC):
    """Abstract base for all video generation providers.

    Subclasses must set :attr:`name` and implement :meth:`generate` and
    :meth:`validate_credentials`.
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
        resolution: str = "1280x720",
        duration_seconds: float = 5.0,
        fps: int = 24,
        seed: int | None = None,
        negative_prompt: str | None = None,
        num_videos: int = 1,
        **kwargs: Any,
    ) -> VideoResponse:
        """Generate one or more videos from a text prompt.

        Args:
            prompt: The text description of the desired video.
            model: Provider-specific model identifier.
            resolution: Output resolution preset.
            duration_seconds: Length of the video (seconds).
            fps: Frame rate.
            seed: Fixed random seed for reproducibility.
            negative_prompt: Optional text describing what to avoid.
            num_videos: Number of videos to generate.

        Returns:
            A :class:`VideoResponse` containing the generated video(s).
        """

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Return True if the configured API key is valid."""

    def estimate_cost(
        self,
        duration_seconds: float,
        resolution: str = "1280x720",
        model: str | None = None,
        **kwargs: Any,
    ) -> float:
        """Estimate cost in USD for the given parameters.

        Default implementation uses a simple per-second rate. Subclasses
        should override with their actual pricing.
        """
        # Default: $0.10 per second of 720p video
        base_rate = 0.10
        if "1080" in resolution:
            base_rate = 0.20
        elif "480" in resolution:
            base_rate = 0.05
        return round(duration_seconds * base_rate, 4)
