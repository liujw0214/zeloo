"""Tests for the AuxiliaryClient."""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from agent.auxiliary_client import AuxiliaryClient

# ── Disabled client (no API calls) ──────────────────────────────────


def test_disabled_client_is_not_available():
    c = AuxiliaryClient(enabled=False)
    assert c.is_available() is False


def test_disabled_complete_returns_empty():
    c = AuxiliaryClient(enabled=False)
    assert c.complete("hello") == ""


def test_disabled_summarize_truncates():
    c = AuxiliaryClient(enabled=False)
    assert c.summarize("hello world", max_chars=5) == "hello"


def test_disabled_extract_text_strips_html():
    c = AuxiliaryClient(enabled=False)
    # Fallback regex strips tags but leaves inner text content.
    assert c.extract_text("<p>hello</p>").strip() == "hello"


def test_disabled_describe_image_returns_empty():
    c = AuxiliaryClient(enabled=False)
    assert c.describe_image("http://example.com/img.png") == ""


# ── from_config ──────────────────────────────────────────────────────


def test_from_config_disabled_by_default():
    c = AuxiliaryClient.from_config({})
    assert c.is_available() is False


def test_from_config_reads_aux_section():
    c = AuxiliaryClient.from_config({
        "auxiliary": {
            "enabled": True,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "max_tokens": 512,
            "temperature": 0.1,
        }
    })
    assert c.is_available() is True
    assert c.model == "gpt-4o-mini"
    assert c.max_tokens == 512
    assert c.temperature == 0.1


def test_from_config_handles_none():
    c = AuxiliaryClient.from_config(None)
    assert c.is_available() is False


# ── Enabled client (with mocked OpenAI client) ───────────────────────


def _mocked_client() -> MagicMock:
    """Return an AuxiliaryClient whose _get_client is mocked."""
    c = AuxiliaryClient(enabled=True, model="gpt-4o-mini")
    mock = MagicMock()
    mock.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="mocked response"))]
    )
    c._client = mock
    return c


def test_enabled_complete_returns_content():
    c = _mocked_client()
    result = c.complete("say hi")
    assert result == "mocked response"


def test_enabled_complete_passes_model_and_messages():
    c = _mocked_client()
    c.complete("prompt text", system="sys")
    call_kwargs = c._client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"
    assert call_kwargs["messages"][0]["role"] == "system"
    assert call_kwargs["messages"][1]["content"] == "prompt text"


def test_enabled_summarize_uses_auxiliary():
    c = _mocked_client()
    result = c.summarize("long text " * 100, max_chars=10)
    assert result == "mocked response"[:10]


def test_enabled_extract_text_uses_auxiliary():
    c = _mocked_client()
    result = c.extract_text("<html>noise</html>")
    assert result == "mocked response"


def test_enabled_describe_image_uses_vision():
    c = _mocked_client()
    result = c.describe_image("http://example.com/img.png")
    assert result == "mocked response"
    call_kwargs = c._client.chat.completions.create.call_args.kwargs
    content = call_kwargs["messages"][0]["content"]
    assert any(item.get("type") == "image_url" for item in content)


def test_complete_returns_empty_on_api_failure():
    c = AuxiliaryClient(enabled=True)
    with patch.object(AuxiliaryClient, "_get_client", side_effect=RuntimeError("boom")):
        assert c.complete("hi") == ""


if __name__ == "__main__":
    test_disabled_client_is_not_available()
    test_disabled_complete_returns_empty()
    test_disabled_summarize_truncates()
    test_disabled_extract_text_strips_html()
    test_disabled_describe_image_returns_empty()
    test_from_config_disabled_by_default()
    test_from_config_reads_aux_section()
    test_from_config_handles_none()
    test_enabled_complete_returns_content()
    test_enabled_complete_passes_model_and_messages()
    test_enabled_summarize_uses_auxiliary()
    test_enabled_extract_text_uses_auxiliary()
    test_enabled_describe_image_uses_vision()
    test_complete_returns_empty_on_api_failure()
    print("All auxiliary_client tests passed!")
