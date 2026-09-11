"""Browser screenshot vision analysis.

Wraps vision-capable LLMs (OpenAI gpt-4o / Anthropic Claude / Google
Gemini / local Ollama) to interpret browser screenshots. Used for
visual element detection, captcha triage, and accessibility audits.

The module never makes a network call on its own — callers can either
inject a pre-built client via :meth:`set_transport` or use the default
``httpx``-based fallback when ``httpx`` is installed.

Example::

    vision = BrowserVision(model="gpt-4o", api_key="sk-...")
    result = await vision.describe(png_bytes, question="Is there a captcha?")
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Captcha fingerprint regex — case-insensitive, matches common vendor
# tokens in DOM text or image alt text.
_CAPTCHA_HINTS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "turnstile",
    "are you human",
    "i'm not a robot",
    "verify you are a human",
    "security check",
    "robot check",
)

# Hard cap on the image payload (bytes). The vision API will reject
# anything larger; we truncate gracefully instead of failing hard.
_MAX_IMAGE_BYTES = 8 * 1024 * 1024

_DEFAULT_PROMPTS = {
    "describe": (
        "You are looking at a screenshot of a web page. "
        "Describe the page in 2-3 sentences, mentioning the most "
        "important visible elements and the overall purpose."
    ),
    "find": (
        "You are looking at a screenshot. The user is searching for: "
        "{description}. Reply ONLY with JSON: "
        '{"found": bool, "x": int, "y": int, "confidence": float, '
        '"label": str}. x and y are pixel coordinates from the top-left '
        'corner. confidence is between 0 and 1.'
    ),
    "captcha": (
        "You are looking at a screenshot. Determine if there is a "
        "CAPTCHA challenge visible (any vendor). Reply ONLY with JSON: "
        '{"has_captcha": bool, "vendor": str|null, "severity": '
        '"low"|"medium"|"high", "notes": str}.'
    ),
}


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class VisionTransport(Protocol):
    """Pluggable transport for talking to the vision provider."""

    async def send(self, payload: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - protocol
        ...


@dataclass
class VisionResult:
    """The decoded result from a vision call."""

    ok: bool
    text: str = ""
    parsed: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    latency_ms: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly dict."""
        return {
            "ok": self.ok,
            "text": self.text,
            "parsed": dict(self.parsed),
            "model": self.model,
            "latency_ms": round(self.latency_ms, 2),
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class VisionError(RuntimeError):
    """Raised for unrecoverable vision failures."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> float:
    import time

    return time.time()


def _safe_b64(data: bytes) -> str:
    """Base64-encode ``data`` after applying the size cap."""
    if not isinstance(data, (bytes, bytearray)):
        raise VisionError("screenshot must be bytes")
    if len(data) > _MAX_IMAGE_BYTES:
        logger.warning(
            "vision_image_truncated size=%d cap=%d", len(data), _MAX_IMAGE_BYTES
        )
        data = data[:_MAX_IMAGE_BYTES]
    return base64.b64encode(bytes(data)).decode("ascii")


def _strip_code_fence(text: str) -> str:
    """Remove ```json ... ``` fences if present."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text


def _coerce_json(text: str) -> dict[str, Any]:
    """Try hard to parse ``text`` as JSON; fall back to a wrapper dict."""
    cleaned = _strip_code_fence(text)
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
        return {"value": value}
    except json.JSONDecodeError:
        return {"raw_text": text}


def _looks_like_captcha(screenshot_bytes: bytes) -> dict[str, Any] | None:
    """Cheap textual fingerprint check for captcha indicators.

    This is intentionally lightweight: it inspects PNG / JPEG headers
    for embedded text markers and never runs OCR. Returns ``None`` if
    nothing matched.
    """
    if not screenshot_bytes:
        return None
    try:
        head = screenshot_bytes[:4096].decode("latin-1", errors="ignore").lower()
    except Exception:  # pragma: no cover - defensive
        return None
    for token in _CAPTCHA_HINTS:
        if token in head:
            return {"vendor": token, "matched_in": "header", "severity": "medium"}
    return None


# ---------------------------------------------------------------------------
# Default transport (httpx-based)
# ---------------------------------------------------------------------------


class HttpxVisionTransport:
    """Thin httpx transport. Imported lazily so the module works without httpx."""

    def __init__(self, model: str, api_key: str, base_url: str = "https://api.openai.com/v1") -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def send(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            import httpx  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - env-specific
            raise VisionError(
                "httpx is required for the default vision transport"
            ) from exc

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise VisionError(
                f"vision provider returned HTTP {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json()


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class BrowserVision:
    """Analyze browser screenshots using a vision-capable LLM.

    The class is provider-agnostic. By default it formats an OpenAI-style
    Chat Completions payload; a custom :class:`VisionTransport` can be
    plugged in for Anthropic, Gemini, Ollama, etc.
    """

    SUPPORTED_MODELS_PREFIXES: tuple[str, ...] = (
        "gpt-4o",
        "gpt-4-vision",
        "claude-3",
        "gemini",
        "llava",
        "qwen-vl",
    )

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        transport: VisionTransport | None = None,
        max_output_tokens: int = 600,
    ) -> None:
        """Initialize the vision wrapper.

        Args:
            model: Model identifier (gpt-4o, claude-3-opus, gemini-1.5, ...).
            api_key: Provider API key. Falls back to ``OPENAI_API_KEY``
                / ``ANTHROPIC_API_KEY`` based on the model prefix.
            base_url: Override the API base URL.
            transport: Optional pre-built transport (skips httpx import).
            max_output_tokens: Maximum completion length per call.
        """
        self.model: str = model
        self.api_key: str = api_key or self._resolve_api_key(model)
        self.base_url: str = base_url
        self.max_output_tokens: int = max(64, int(max_output_tokens))
        self._transport: VisionTransport | None = transport

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_api_key(model: str) -> str:
        lower = model.lower()
        if lower.startswith("claude"):
            return os.environ.get("ANTHROPIC_API_KEY", "")
        if lower.startswith("gemini"):
            return os.environ.get("GOOGLE_API_KEY", "") or os.environ.get(
                "GEMINI_API_KEY", ""
            )
        return os.environ.get("OPENAI_API_KEY", "")

    def _get_transport(self) -> VisionTransport:
        if self._transport is not None:
            return self._transport
        if not self.api_key:
            raise VisionError(
                f"No API key resolved for model {self.model!r}. "
                "Pass api_key= or set OPENAI_API_KEY / ANTHROPIC_API_KEY."
            )
        self._transport = HttpxVisionTransport(
            model=self.model, api_key=self.api_key, base_url=self.base_url
        )
        return self._transport

    def set_transport(self, transport: VisionTransport) -> None:
        """Inject a custom transport (useful for tests)."""
        self._transport = transport

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        image_b64: str,
        prompt: str,
        *,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": self.max_output_tokens,
            "temperature": max(0.0, min(1.0, float(temperature))),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                }
            ],
        }

    @staticmethod
    def _extract_text(response: dict[str, Any]) -> str:
        """Pull the assistant text from an OpenAI-style response."""
        try:
            choices = response.get("choices") or []
            if not choices:
                return ""
            msg = choices[0].get("message") or {}
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                    elif isinstance(item, str):
                        parts.append(item)
                return "\n".join(parts)
        except Exception:  # pragma: no cover - defensive
            return ""
        return ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def describe(
        self,
        screenshot_bytes: bytes,
        question: str = "",
        *,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """Describe what's on the screen.

        Args:
            screenshot_bytes: PNG / JPEG image data.
            question: Optional follow-up question (e.g. "Is the login
                button visible?"). Empty = plain description.
            temperature: Sampling temperature.

        Returns:
            A :class:`VisionResult` dict.
        """
        prompt = _DEFAULT_PROMPTS["describe"]
        if question:
            prompt = f"{prompt}\n\nFollow-up question: {question.strip()}"

        result = await self._call(prompt, screenshot_bytes, temperature=temperature)
        return result.to_dict()

    async def find_element(
        self,
        screenshot_bytes: bytes,
        description: str,
        *,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Locate an element by description.

        Returns:
            Dict with ``found``, ``x``, ``y``, ``confidence``, ``label``.
            Coordinates are approximate and in pixel space relative to
            the top-left of the screenshot.
        """
        if not description.strip():
            raise VisionError("find_element() requires a non-empty description")
        prompt = _DEFAULT_PROMPTS["find"].format(description=description.strip())
        result = await self._call(prompt, screenshot_bytes, temperature=temperature)
        out = result.to_dict()
        parsed = result.parsed or {}
        # Coerce common types so downstream code can rely on them.
        out["found"] = bool(parsed.get("found"))
        try:
            out["x"] = int(parsed.get("x", -1))
            out["y"] = int(parsed.get("y", -1))
        except (TypeError, ValueError):
            out["x"] = -1
            out["y"] = -1
        try:
            out["confidence"] = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            out["confidence"] = 0.0
        out["label"] = str(parsed.get("label", ""))
        return out

    async def detect_captcha(
        self,
        screenshot_bytes: bytes,
        *,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Detect whether a CAPTCHA is visible.

        Combines a fast textual fingerprint scan with an LLM-based
        visual confirmation. Returns the most confident signal.
        """
        fingerprint = _looks_like_captcha(screenshot_bytes)
        prompt = _DEFAULT_PROMPTS["captcha"]
        result = await self._call(prompt, screenshot_bytes, temperature=temperature)
        out = result.to_dict()
        parsed = result.parsed or {}
        llm_signal = {
            "vendor": parsed.get("vendor"),
            "severity": parsed.get("severity", "low"),
            "notes": parsed.get("notes", ""),
        }
        has_captcha = bool(parsed.get("has_captcha")) or fingerprint is not None
        if fingerprint and not llm_signal.get("vendor"):
            llm_signal["vendor"] = fingerprint.get("vendor")
            llm_signal["severity"] = fingerprint.get("severity", "medium")
        out["has_captcha"] = has_captcha
        out["vendor"] = llm_signal.get("vendor")
        out["severity"] = llm_signal.get("severity", "low")
        out["notes"] = llm_signal.get("notes", "")
        out["fingerprint"] = fingerprint or {}
        return out

    # ------------------------------------------------------------------
    # Internal call helper
    # ------------------------------------------------------------------

    async def _call(
        self,
        prompt: str,
        screenshot_bytes: bytes,
        *,
        temperature: float = 0.2,
    ) -> VisionResult:
        """Execute a single vision call and decode the response."""
        start = _now()
        try:
            image_b64 = _safe_b64(screenshot_bytes)
            payload = self._build_payload(image_b64, prompt, temperature=temperature)
            transport = self._get_transport()
            response = await transport.send(payload)
        except VisionError:
            raise
        except Exception as exc:
            logger.exception("vision_call_failed")
            return VisionResult(
                ok=False,
                model=self.model,
                error=str(exc),
                latency_ms=(_now() - start) * 1000.0,
            )

        text = self._extract_text(response)
        parsed = _coerce_json(text) if text else {}
        return VisionResult(
            ok=True,
            text=text,
            parsed=parsed,
            model=self.model,
            raw=response,
            latency_ms=(_now() - start) * 1000.0,
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """Return a non-network diagnostic snapshot."""
        return {
            "model": self.model,
            "base_url": self.base_url,
            "has_api_key": bool(self.api_key),
            "max_output_tokens": self.max_output_tokens,
            "transport": type(self._transport).__name__ if self._transport else None,
        }
