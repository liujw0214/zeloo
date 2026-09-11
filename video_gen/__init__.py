"""Zeloo video generation package.

Provides 3 video generation providers with a uniform interface:
- DeepInfra (cloud-hosted open models, OpenAI-compatible)
- FAL.ai (queue-based inference with webhook callbacks)
- xAI Grok (real-time generative video via xAI API)

Usage:
    from video_gen import get_provider, list_providers
    provider = get_provider("deepinfra", api_key="...")
    response = provider.generate("A cat playing piano")
"""

from __future__ import annotations

import logging

from video_gen.base import (
    VideoModel,
    VideoProvider,
    VideoResolution,
    VideoResponse,
    VideoResult,
)
from video_gen.download import (
    download_video,
    download_video_result,
    get_output_path,
    verify_checksum,
)
from video_gen.registry import clear_cache, get_provider, list_providers, register_provider

logger = logging.getLogger(__name__)

__all__ = [
    "VideoModel",
    "VideoProvider",
    "VideoResolution",
    "VideoResponse",
    "VideoResult",
    "get_provider",
    "list_providers",
    "register_provider",
    "download_video",
    "download_video_result",
    "get_output_path",
    "verify_checksum",
    "clear_cache",
]
