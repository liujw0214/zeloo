"""Image generation tools — create images from text prompts.

Uses the OpenAI Images API (DALL-E) by default, but works with any
OpenAI-compatible provider that exposes ``/v1/images/generations``.

Supports multi-provider failover: if the primary provider fails, the
next configured provider is tried automatically.

Configuration (config.yaml)::

    image_generation:
      enabled: true
      provider: openai          # primary provider
      model: dall-e-3
      size: 1024x1024
      quality: standard
      fallback_providers:       # optional failover list
        - name: together
          model: flux-1-schnell
          api_key: ${TOGETHER_API_KEY}
          base_url: https://api.together.xyz/v1
"""

from __future__ import annotations

import logging
import os
from typing import Any

from tools.base import tool

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "dall-e-3"
_DEFAULT_SIZE = "1024x1024"
_VALID_SIZES = {"1024x1024", "1024x1792", "1792x1024"}
_VALID_QUALITIES = {"standard", "hd"}


def _get_config() -> dict[str, Any]:
    """Load the image_generation config section (empty dict on failure)."""
    try:
        from zeloo_cli.config import load_config

        cfg = load_config()
        section = cfg.get("image_generation", {}) if isinstance(cfg, dict) else {}
        return section if isinstance(section, dict) else {}
    except Exception:
        return {}


def _is_enabled() -> bool:
    return bool(_get_config().get("enabled", False))


def _expand_env(value: str) -> str:
    """Expand ``${VAR}`` references in a config string from the environment."""
    if not isinstance(value, str):
        return value
    import re

    def _repl(m: re.Match[str]) -> str:
        return os.environ.get(m.group(1), "")

    return re.sub(r"\$\{([A-Z0-9_]+)\}", _repl, value)


def _build_provider_list(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the ordered list of image providers (primary + fallbacks)."""
    providers: list[dict[str, Any]] = []

    # Primary provider
    primary: dict[str, Any] = {
        "name": cfg.get("provider", "openai"),
        "model": cfg.get("model", _DEFAULT_MODEL),
        "api_key": cfg.get("api_key") or os.environ.get("OPENAI_API_KEY", ""),
        "base_url": cfg.get("base_url"),
    }
    providers.append(primary)

    # Fallback providers
    fallbacks = cfg.get("fallback_providers", [])
    if isinstance(fallbacks, list):
        for fb in fallbacks:
            if not isinstance(fb, dict):
                continue
            name = fb.get("name", "")
            env_key = f"{name.upper()}_API_KEY" if name else ""
            providers.append({
                "name": name,
                "model": fb.get("model", primary["model"]),
                "api_key": _expand_env(fb.get("api_key", "")) or os.environ.get(env_key, ""),
                "base_url": fb.get("base_url"),
            })

    return providers


def _make_client(provider: dict[str, Any]) -> Any:
    """Create an OpenAI client for a single provider config."""
    from openai import OpenAI

    kwargs: dict[str, Any] = {"api_key": provider.get("api_key", "")}
    if provider.get("base_url"):
        kwargs["base_url"] = provider["base_url"]
    return OpenAI(**kwargs)


def _generate_with_fal(
    prompt: str,
    size: str,
    n: int,
    api_key: str,
    model: str = "fal-ai/flux/dev",
) -> list[str]:
    """Generate an image via the FAL REST API.

    FAL uses an async queue pattern: submit a request, poll for results.
    Returns a list of image URLs.
    """
    import httpx

    width, height = _size_to_wh(size)
    submit_url = f"https://queue.fal.run/{model}"
    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": prompt,
        "num_inference_steps": 28,
        "guidance_scale": 3.5,
        "width": width,
        "height": height,
        "num_images": n,
    }

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(submit_url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        request_id = data.get("request_id")
        if not request_id:
            return [img.get("url", "") for img in data.get("images", []) if img.get("url")]

        status_url = data.get("status_url") or f"https://queue.fal.run/{model}/requests/{request_id}"
        for _ in range(60):  # poll up to ~60s
            poll = client.get(status_url, headers=headers)
            poll.raise_for_status()
            poll_data = poll.json()
            if poll_data.get("status") == "COMPLETED":
                return [img.get("url", "") for img in poll_data.get("images", []) if img.get("url")]
            if poll_data.get("status") == "FAILED":
                raise RuntimeError(poll_data.get("error", "FAL generation failed"))
            import time
            time.sleep(1.0)

        raise RuntimeError("FAL generation timed out")


def _generate_with_deepinfra(
    prompt: str,
    size: str,
    n: int,
    api_key: str,
    model: str = "stability-ai/sdxl",
) -> list[str]:
    """Generate an image via the DeepInfra inference API.

    Returns a list of image URLs (DeepInfra returns base64 data URLs).
    """
    import httpx

    width, height = _size_to_wh(size)
    url = f"https://api.deepinfra.com/v1/inference/{model}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "input": {
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_outputs": n,
            "num_inference_steps": 30,
            "guidance_scale": 7.5,
        }
    }

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    outputs = data.get("output", [])
    urls: list[str] = []
    for item in outputs:
        if isinstance(item, str) and item.startswith(("http", "data:")):
            urls.append(item)
        elif isinstance(item, dict) and item.get("url"):
            urls.append(item["url"])
    return urls


def _size_to_wh(size: str) -> tuple[int, int]:
    """Convert a size string like '1024x1024' to (width, height) ints."""
    try:
        w, h = size.split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 1024, 1024


@tool(
    name="image_generate",
    description="Generate an image from a text prompt and return its URL",
    dangerous=False,
    toolset="image",
)
def image_generate(
    prompt: str,
    size: str | None = None,
    quality: str | None = None,
    n: int = 1,
) -> str:
    """Generate an image from a text prompt.

    Args:
        prompt: A detailed description of the desired image.
        size: Output size (``1024x1024``, ``1024x1792``, or ``1792x1024``).
            Defaults to the configured size or ``1024x1024``.
        quality: ``standard`` or ``hd``. Defaults to configured quality.
        n: Number of images to generate (default 1).

    Returns:
        The URL(s) of the generated image(s), one per line.
    """
    if not _is_enabled():
        return (
            "Image generation is disabled. Enable it by setting "
            "`image_generation.enabled: true` in config.yaml."
        )

    cfg = _get_config()
    size = size or cfg.get("size", _DEFAULT_SIZE)
    quality = quality or cfg.get("quality", "standard")

    if size not in _VALID_SIZES:
        return f"Error: invalid size '{size}'. Use one of: {', '.join(sorted(_VALID_SIZES))}"
    if quality not in _VALID_QUALITIES:
        return (
            f"Error: invalid quality '{quality}'. "
            f"Use one of: {', '.join(sorted(_VALID_QUALITIES))}"
        )

    providers = _build_provider_list(cfg)
    last_error: str | None = None

    for provider in providers:
        name = provider.get("name", "?")
        model = provider.get("model", _DEFAULT_MODEL)
        api_key = provider.get("api_key", "")
        if not api_key:
            logger.debug("Skipping image provider '%s': no API key", name)
            last_error = f"Provider '{name}' has no API key configured."
            continue
        try:
            if name == "fal":
                urls = _generate_with_fal(prompt, size, n, api_key, model)
            elif name == "deepinfra":
                urls = _generate_with_deepinfra(prompt, size, n, api_key, model)
            else:
                client = _make_client(provider)
                response = client.images.generate(
                    model=model,
                    prompt=prompt,
                    size=size,
                    quality=quality,
                    n=n,
                )
                urls = [img.url for img in response.data if img.url]

            if not urls:
                last_error = f"Provider '{name}' returned no image URL."
                continue
            logger.info("Image generated via provider '%s'", name)
            return "\n".join(urls)
        except Exception as exc:
            logger.warning("Image provider '%s' failed: %s", name, exc)
            last_error = f"{name}: {exc}"
            continue

    return f"Error generating image (all providers failed). Last error: {last_error}"
