"""Video generation provider registry."""

from __future__ import annotations

import logging
import threading
from typing import Any

from video_gen.base import VideoProvider

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type[VideoProvider]] = {}

_MAX_CACHE_SIZE = 100

_CACHE: dict[tuple[str, str], VideoProvider] = {}
_CACHE_LOCK = threading.Lock()


def register_provider(name: str, cls: type[VideoProvider]) -> None:
    """Register a video provider class under the given name."""
    _REGISTRY[name.lower()] = cls
    logger.debug("Registered video provider: %s", name)


def get_provider(name: str, **kwargs: Any) -> VideoProvider | None:
    """Instantiate a provider by registry name.

    When ``api_key`` is explicitly provided, the instance is cached and
    reused on subsequent calls with the same ``(name, api_key)`` pair.
    Without ``api_key`` a fresh instance is created each call (env vars
    are respected at instantiation time).
    """
    cls = _REGISTRY.get(name.lower())
    if cls is None:
        return None

    api_key = kwargs.get("api_key") if kwargs else None
    if api_key is not None:
        cache_key = (name.lower(), api_key)
        with _CACHE_LOCK:
            if cache_key in _CACHE:
                return _CACHE[cache_key]
            if len(_CACHE) >= _MAX_CACHE_SIZE:
                evicted = next(iter(_CACHE))
                del _CACHE[evicted]
                logger.debug("Cache evicted: %s", evicted)
            instance = cls(**kwargs)
            _CACHE[cache_key] = instance
            return instance

    return cls(**kwargs)


def list_providers() -> list[str]:
    """Return sorted list of registered provider names."""
    return sorted(_REGISTRY.keys())


def clear_cache() -> int:
    """Clear all cached provider instances.

    Returns:
        The number of entries that were removed.
    """
    with _CACHE_LOCK:
        count = len(_CACHE)
        _CACHE.clear()
    return count


def _register_builtins() -> None:
    """Register all built-in video providers."""
    from video_gen.deepinfra import DeepInfraVideoProvider
    from video_gen.fal import FalVideoProvider
    from video_gen.xai_video import XaiVideoProvider

    register_provider("deepinfra_video", DeepInfraVideoProvider)
    register_provider("fal_video", FalVideoProvider)
    register_provider("xai_video", XaiVideoProvider)


_register_builtins()


__all__ = ["register_provider", "get_provider", "list_providers", "clear_cache"]
