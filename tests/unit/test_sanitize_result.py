"""Tests for ConversationLoop._sanitize_result (M3 — multi-modal)."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from agent.conversation_loop import ConversationLoop  # noqa: E402


def _new_loop() -> ConversationLoop:
    """Build a ConversationLoop with a stub agent — we never call run()."""
    return ConversationLoop(agent=SimpleNamespace())


# ── string passthrough ───────────────────────────────────────────────


def test_sanitize_passthrough_for_plain_string() -> None:
    """Plain strings round-trip unchanged."""
    loop = _new_loop()
    assert loop._sanitize_result("hello world") == "hello world"


def test_sanitize_preserves_unicode_string() -> None:
    """Unicode survives without re-encoding as ``\\uXXXX``."""
    loop = _new_loop()
    out = loop._sanitize_result("中文 — 🚀")
    assert out == "中文 — 🚀"


# ── dict / list → JSON ───────────────────────────────────────────────


def test_sanitize_dict_to_json() -> None:
    """A dict serialises to a UTF-8 JSON object string."""
    loop = _new_loop()
    out = loop._sanitize_result({"status": "ok", "count": 3})
    parsed = json.loads(out)
    assert parsed == {"status": "ok", "count": 3}


def test_sanitize_list_to_json() -> None:
    """A list serialises to a JSON array string."""
    loop = _new_loop()
    out = loop._sanitize_result([1, 2, "three"])
    parsed = json.loads(out)
    assert parsed == [1, 2, "three"]


def test_sanitize_nested_dict_to_json() -> None:
    """Nested dicts encode without losing non-ASCII keys/values."""
    loop = _new_loop()
    out = loop._sanitize_result({"a": {"b": "中文"}})
    parsed = json.loads(out)
    assert parsed["a"]["b"] == "中文"


# ── bytes → image_base64 ─────────────────────────────────────────────


def test_sanitize_bytes_produces_image_marker() -> None:
    """Raw ``bytes`` are encoded as a ``image_base64`` JSON marker."""
    loop = _new_loop()
    payload = b"\x89PNG\r\n\x1a\n-fake-binary-"
    out = loop._sanitize_result(payload)
    parsed = json.loads(out)
    assert parsed["type"] == "image_base64"
    assert parsed["mime"] == "image/png"
    assert base64.b64decode(parsed["data"]) == payload


def test_sanitize_empty_bytes_still_encodes() -> None:
    """Empty bytes still produce a valid (zero-length) marker."""
    loop = _new_loop()
    out = loop._sanitize_result(b"")
    parsed = json.loads(out)
    assert parsed["type"] == "image_base64"
    assert parsed["data"] == ""


# ── PIL Image → image_base64 ─────────────────────────────────────────


def test_sanitize_pil_image_to_png_marker() -> None:
    """A PIL Image is encoded as PNG inside an ``image_base64`` marker."""
    pytest = __import__("pytest")
    pil = pytest.importorskip("PIL")
    # Some distributions expose Image under PIL.Image, others require direct import.
    try:
        from PIL import Image as _Image  # noqa: F401
    except Exception:
        pytest.skip("PIL.Image unavailable")
    loop = _new_loop()
    # Build a minimal 2x2 RGB image without depending on filesystem assets.
    img = pil.Image.new("RGB", (2, 2), color=(255, 0, 0))
    out = loop._sanitize_result(img)
    parsed = json.loads(out)
    assert parsed["type"] == "image_base64"
    assert parsed["mime"] == "image/png"
    decoded = base64.b64decode(parsed["data"])
    # PNG magic bytes are 89 50 4E 47 0D 0A 1A 0A.
    assert decoded.startswith(b"\x89PNG\r\n\x1a\n")


# ── fallbacks ────────────────────────────────────────────────────────


def test_sanitize_unknown_type_falls_back_to_str() -> None:
    """A custom object falls back to ``str(obj)``."""
    loop = _new_loop()

    class Weird:
        def __str__(self) -> str:
            return "weird-object"

    assert loop._sanitize_result(Weird()) == "weird-object"


def test_sanitize_int_falls_back_to_str() -> None:
    """A bare int falls back to its ``str()`` form."""
    loop = _new_loop()
    assert loop._sanitize_result(42) == "42"


# ── secret-scan + truncation integration ─────────────────────────────


def test_sanitize_truncates_long_strings() -> None:
    """Strings longer than ``MAX_TOOL_RESULT_LENGTH`` get truncated with marker."""
    from agent.zeloo_constants import MAX_TOOL_RESULT_LENGTH

    loop = _new_loop()
    big = "x" * (MAX_TOOL_RESULT_LENGTH + 500)
    out = loop._sanitize_result(big)
    assert len(out) <= MAX_TOOL_RESULT_LENGTH + len("\n...[truncated]")
    assert out.endswith("\n...[truncated]")


def test_sanitize_runs_secret_scanner() -> None:
    """The secret scanner is still applied to multi-modal results too.

    We patch ``tools.output_scan.scan_tool_output`` (the call inside
    ``_sanitize_result``) and assert it gets called with the
    intermediate text/JSON form.
    """
    loop = _new_loop()
    sentinel = "REDACTED-CALLED"
    with patch("tools.output_scan.scan_tool_output", return_value=sentinel) as m:
        out = loop._sanitize_result({"api_key": "AKIA1234567890ABCDEF"})
    assert out == sentinel
    m.assert_called_once()


def test_sanitize_secret_scanner_failure_is_non_fatal() -> None:
    """If the scanner raises, the loop falls back to plain text/JSON."""

    def _boom(*args: object, **kwargs: object) -> str:
        raise RuntimeError("scanner down")

    loop = _new_loop()
    with patch("tools.output_scan.scan_tool_output", side_effect=_boom):
        out = loop._sanitize_result("safe text")
    assert out == "safe text"


def test_sanitize_coerce_helper_handles_bytes() -> None:
    """``_coerce_to_text`` is the unit-level entry point for type routing."""
    out = ConversationLoop._coerce_to_text(b"abc")
    parsed = json.loads(out)
    assert parsed["type"] == "image_base64"
    assert base64.b64decode(parsed["data"]) == b"abc"