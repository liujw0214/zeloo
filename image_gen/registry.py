"""Image generation provider registry."""

from __future__ import annotations

import logging
from typing import Any

from image_gen.base import ImageProvider

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type[ImageProvider]] = {}


def register_provider(name: str, cls: type[ImageProvider]) -> None:
    _REGISTRY[name.lower()] = cls
    logger.debug("Registered image provider: %s", name)


def get_provider(name: str, **kwargs: Any) -> ImageProvider | None:
    cls = _REGISTRY.get(name.lower())
    if cls is None:
        return None
    return cls(**kwargs)


def list_providers() -> list[str]:
    return sorted(_REGISTRY.keys())


def _register_builtins() -> None:
    from image_gen.dalle import DalleProvider
    from image_gen.deepinfra import DeepInfraProvider
    from image_gen.fal import FalProvider
    from image_gen.grok_image import GrokImageProvider
    from image_gen.krea import KreaProvider
    from image_gen.meta_ai import MetaAIProvider
    from image_gen.stability import StabilityProvider

    register_provider("fal", FalProvider)
    register_provider("stability", StabilityProvider)
    register_provider("dalle", DalleProvider)
    register_provider("deepinfra", DeepInfraProvider)
    register_provider("krea", KreaProvider)
    register_provider("grok_image", GrokImageProvider)
    register_provider("meta_ai", MetaAIProvider)


_register_builtins()
