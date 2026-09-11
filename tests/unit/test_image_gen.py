"""Unit tests for image_gen module."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)


def test_image_result_to_dict():
    """ImageResult.to_dict() returns a serialisable dict."""
    from image_gen.base import ImageResult

    result = ImageResult(
        url="https://example.com/img.png",
        width=1024,
        height=768,
        revised_prompt="a refined prompt",
        model="flux-pro",
        provider="fal",
        cost_usd=0.01,
        seed=42,
    )
    d = result.to_dict()
    assert d["url"] == "https://example.com/img.png"
    assert d["width"] == 1024
    assert d["revised_prompt"] == "a refined prompt"
    assert d["seed"] == 42


def test_image_response_to_dict():
    """ImageResponse.to_dict() returns a serialisable dict."""
    from image_gen.base import ImageResponse, ImageResult

    response = ImageResponse(
        results=[
            ImageResult(url="https://a.com/1.png", width=1024, height=1024),
            ImageResult(url="https://a.com/2.png", width=1024, height=1024),
        ],
        provider="fal",
        model="flux-schnell",
        prompt="a cat",
    )
    d = response.to_dict()
    assert len(d["results"]) == 2
    assert d["provider"] == "fal"


def test_registry_discovers_providers():
    """Registry returns all three built-in image providers."""
    from image_gen.registry import list_providers

    names = list_providers()
    assert "fal" in names
    assert "stability" in names
    assert "dalle" in names


def test_registry_get_provider():
    """get_provider returns an instance of the named provider."""
    from image_gen.registry import get_provider

    p = get_provider("fal", api_key="fake-key")
    assert p is not None
    assert p.name == "fal"

    none_p = get_provider("nonexistent")
    assert none_p is None


def test_fal_validate_no_key():
    """FalProvider.validate_credentials() returns False without a key."""
    from image_gen.fal import FalProvider

    p = FalProvider(api_key="")
    assert p.validate_credentials() is False


def test_fal_generate_with_mock():
    """FalProvider.generate() parses response and returns ImageResult."""
    from image_gen.fal import FalProvider

    mock_data = {
        "images": [{"url": "https://fal.run/img.png"}],
        "revised_prompt": "a sunset over mountains",
    }

    with patch("image_gen.fal.httpx") as mock_httpx:
        mock_client = MagicMock()
        mock_httpx.Client.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = mock_data
        mock_client.post.return_value = mock_response

        p = FalProvider(api_key="fake-key")
        resp = p.generate("a sunset", size="1024x1024")

        assert resp.provider == "fal"
        assert len(resp.results) == 1
        assert resp.results[0].url == "https://fal.run/img.png"
        assert resp.results[0].revised_prompt == "a sunset over mountains"


def test_fal_parse_size():
    """FalProvider._parse_size() parses WxH strings correctly."""
    from image_gen.fal import FalProvider

    assert FalProvider._parse_size("1024x768") == (1024, 768)
    assert FalProvider._parse_size("512x512") == (512, 512)
    assert FalProvider._parse_size("invalid") == (1024, 1024)
    assert FalProvider._parse_size("512x") == (1024, 1024)


def test_stability_validate_no_key():
    """StabilityProvider.validate_credentials() returns False without a key."""
    from image_gen.stability import StabilityProvider

    p = StabilityProvider(api_key="")
    assert p.validate_credentials() is False


def test_stability_generate_with_mock():
    """StabilityProvider.generate() parses base64 artifacts into data URIs."""
    from image_gen.stability import StabilityProvider

    mock_data = {
        "artifacts": [
            {"base64": "iVBORw0KGgoAAAANSUhEUg==", "seed": 123},
            {"base64": "YWJjZGVmZ2hpamtsbW5vcA==", "seed": 456},
        ]
    }

    with patch("image_gen.stability.httpx") as mock_httpx:
        mock_client = MagicMock()
        mock_httpx.Client.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = mock_data
        mock_client.post.return_value = mock_response

        p = StabilityProvider(api_key="fake-key")
        resp = p.generate("a cat", num_images=2)

        assert resp.provider == "stability"
        assert len(resp.results) == 2
        assert resp.results[0].url.startswith("data:image/png;base64,")
        assert resp.results[0].seed == 123


def test_stability_parse_size():
    """StabilityProvider._parse_size() parses WxH strings correctly."""
    from image_gen.stability import StabilityProvider

    assert StabilityProvider._parse_size("1024x768") == (1024, 768)
    assert StabilityProvider._parse_size("bad") == (1024, 1024)


def test_dalle_validate_no_key():
    """DalleProvider.validate_credentials() returns False without a key."""
    from image_gen.dalle import DalleProvider

    p = DalleProvider(api_key="")
    assert p.validate_credentials() is False


def test_dalle_generate_with_mock():
    """DalleProvider.generate() parses DALL-E response."""
    from image_gen.dalle import DalleProvider

    mock_data = {
        "data": [
            {
                "url": "https://oaidalleapiprodscus.blob.core.windows.net/ fake.png",
                "revised_prompt": "a painted sunset",
            }
        ]
    }

    with patch("image_gen.dalle.httpx") as mock_httpx:
        mock_client = MagicMock()
        mock_httpx.Client.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = mock_data
        mock_client.post.return_value = mock_response

        p = DalleProvider(api_key="fake-key")
        resp = p.generate("a sunset")

        assert resp.provider == "dalle"
        assert len(resp.results) == 1
        assert resp.results[0].url == mock_data["data"][0]["url"]
        assert resp.results[0].revised_prompt == "a painted sunset"


def test_dalle_normalise_size():
    """DalleProvider._normalise_size() maps known sizes correctly."""
    from image_gen.dalle import DalleProvider

    assert DalleProvider._normalise_size("1024x1024") == "1024x1024"
    assert DalleProvider._normalise_size("256x256") == "256x256"
    assert DalleProvider._normalise_size("1792x1024") == "1792x1024"
    assert DalleProvider._normalise_size("unknown") == "1024x1024"


if __name__ == "__main__":
    test_image_result_to_dict()
    test_image_response_to_dict()
    test_registry_discovers_providers()
    test_registry_get_provider()
    test_fal_validate_no_key()
    test_fal_generate_with_mock()
    test_fal_parse_size()
    test_stability_validate_no_key()
    test_stability_generate_with_mock()
    test_stability_parse_size()
    test_dalle_validate_no_key()
    test_dalle_generate_with_mock()
    test_dalle_normalise_size()
    print("All image_gen tests passed!")
