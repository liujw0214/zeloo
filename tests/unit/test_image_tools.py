"""Tests for image_tools (image_generate)."""

import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, ".")

_CONFIG = {
    "enabled": True,
    "provider": "openai",
    "model": "dall-e-3",
    "api_key": "sk-test",
    "size": "1024x1024",
    "quality": "standard",
}


def test_image_generate_disabled():
    with patch("tools.image_tools._get_config", return_value={"enabled": False}):
        from tools.image_tools import image_generate

        result = image_generate("a cat")
        assert "disabled" in result.lower()


def test_image_generate_invalid_size():
    with patch("tools.image_tools._get_config", return_value=_CONFIG):
        from tools.image_tools import image_generate

        result = image_generate("a cat", size="1234x5678")
        assert "invalid size" in result.lower()


def test_image_generate_invalid_quality():
    with patch("tools.image_tools._get_config", return_value=_CONFIG):
        from tools.image_tools import image_generate

        result = image_generate("a cat", quality="ultra")
        assert "invalid quality" in result.lower()


def test_image_generate_success():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.data = [MagicMock(url="https://example.com/img.png")]
    mock_client.images.generate.return_value = mock_response

    with patch("tools.image_tools._get_config", return_value=_CONFIG), patch(
        "tools.image_tools._make_client", return_value=mock_client
    ):
        from tools.image_tools import image_generate

        result = image_generate("a cat")
        assert "img.png" in result


def test_image_generate_fallback():
    cfg = {
        "enabled": True,
        "provider": "primary",
        "model": "dall-e-3",
        "api_key": "",
        "size": "1024x1024",
        "quality": "standard",
        "fallback_providers": [
            {"name": "backup", "model": "flux", "api_key": "sk-backup", "base_url": "x"}
        ],
    }
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.data = [MagicMock(url="https://backup.com/img.png")]
    mock_client.images.generate.return_value = mock_response

    with patch("tools.image_tools._get_config", return_value=cfg), patch(
        "tools.image_tools._make_client", return_value=mock_client
    ):
        from tools.image_tools import image_generate

        result = image_generate("a cat")
        assert "img.png" in result


def test_image_generate_all_fail():
    with patch("tools.image_tools._get_config", return_value=_CONFIG), patch(
        "tools.image_tools._make_client", side_effect=RuntimeError("API down")
    ):
        from tools.image_tools import image_generate

        result = image_generate("a cat")
        assert "Error" in result or "failed" in result.lower()


if __name__ == "__main__":
    test_image_generate_disabled()
    test_image_generate_invalid_size()
    test_image_generate_invalid_quality()
    test_image_generate_success()
    test_image_generate_fallback()
    test_image_generate_all_fail()
    print("All image_tools tests passed!")
