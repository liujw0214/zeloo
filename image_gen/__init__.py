"""Image generation providers.

Nine providers are supported across three tiers:
- Tier 1 (Cloud API): DALL-E, Stability AI, Grok Image
- Tier 2 (Queue API): FAL (Flux/SDXL/Realistic), DeepInfra, Krea, Meta AI
- Tier 3 (Specialized): Codex (code visualization)

Use :func:`get_provider` to retrieve a provider by name:

    from image_gen import get_provider
    img = get_provider("fal")
    result = img.generate(prompt="a sunset over mountains", size="1024x1024")
    print(result.url)

For downloading generated images, use the download utilities:

    from image_gen import download_image, download_image_result
    result = download_image_result(provider_result, output_dir="images/")
    print(f"Downloaded {result['downloaded']} images")
"""

from __future__ import annotations

from image_gen.base import ImageProvider, ImageResponse, ImageResult, ValidationError
from image_gen.download import (
    download_image,
    download_image_result,
    get_output_path,
    sanitize_filename,
    verify_checksum,
)
from image_gen.registry import get_provider, list_providers, register_provider

__all__ = [
    "ImageProvider",
    "ImageResult",
    "ImageResponse",
    "ValidationError",
    "get_provider",
    "list_providers",
    "register_provider",
    "download_image",
    "download_image_result",
    "get_output_path",
    "sanitize_filename",
    "verify_checksum",
]
