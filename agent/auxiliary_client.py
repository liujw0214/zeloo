"""Auxiliary LLM client — side tasks on a cheaper model.

The auxiliary client handles low-stakes, high-volume sub-tasks such as
web content extraction, image description, and text summarization using
a cheaper/faster model. It never counts against the primary model's
iteration budget and does not share the primary conversation context.

Configuration (config.yaml)::

    auxiliary:
      enabled: true
      provider: openai
      model: gpt-4o-mini
      base_url: null
      max_tokens: 1024
      temperature: 0.0
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_AUX_MODEL = "gpt-4o-mini"
_DEFAULT_AUX_PROVIDER = "openai"


class AuxiliaryClient:
    """A lightweight LLM client for side tasks.

    Uses a separate (typically cheaper) model and does not consume the
    primary agent's iteration budget. Falls back to a no-op when
    disabled or misconfigured.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        provider: str = _DEFAULT_AUX_PROVIDER,
        model: str = _DEFAULT_AUX_MODEL,
        base_url: str | None = None,
        api_key: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> None:
        self.enabled = enabled
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client: Any = None

    # ── Factory ──────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> AuxiliaryClient:
        """Build an :class:`AuxiliaryClient` from config.yaml.

        Reads the ``auxiliary`` section. When ``enabled`` is false or the
        section is missing, returns a disabled client whose methods are
        safe no-ops.
        """
        aux = (config or {}).get("auxiliary", {}) if isinstance(config, dict) else {}
        if not isinstance(aux, dict):
            aux = {}

        return cls(
            enabled=bool(aux.get("enabled", False)),
            provider=str(aux.get("provider", _DEFAULT_AUX_PROVIDER)),
            model=str(aux.get("model", _DEFAULT_AUX_MODEL)),
            base_url=aux.get("base_url"),
            api_key=aux.get("api_key"),
            max_tokens=int(aux.get("max_tokens", 1024)),
            temperature=float(aux.get("temperature", 0.0)),
        )

    # ── Public API ───────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True if the auxiliary client is enabled and can make calls."""
        return self.enabled

    def complete(
        self,
        prompt: str,
        *,
        system: str = "You are a helpful assistant.",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Run a single-turn completion and return the text response.

        Returns an empty string if the client is disabled or the call fails.
        """
        if not self.enabled:
            return ""

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens or self.max_tokens,
                temperature=self.temperature if temperature is None else temperature,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            logger.warning("Auxiliary client call failed: %s", exc)
            return ""

    def summarize(self, text: str, max_chars: int = 500) -> str:
        """Summarize *text* to at most *max_chars* characters."""
        if not self.enabled or not text:
            return text[:max_chars] if text else ""
        prompt = (
            f"Summarize the following text concisely in at most "
            f"{max_chars} characters. Preserve key facts and names.\n\n{text}"
        )
        summary = self.complete(prompt, system="You summarize text concisely.")
        return (summary or text)[:max_chars]

    def extract_text(self, html_or_text: str) -> str:
        """Extract clean readable text from HTML or noisy text.

        Falls back to stripping HTML tags with a regex when the client
        is disabled.
        """
        if not self.enabled:
            import re

            return re.sub(r"<[^>]+>", "", html_or_text).strip()

        prompt = (
            "Extract the main readable text content from the following, "
            "removing navigation, ads, and boilerplate. Return only the "
            f"clean text.\n\n{html_or_text[:8000]}"
        )
        result = self.complete(prompt, system="You extract clean text from web pages.")
        return result or html_or_text

    def describe_image(self, image_url: str) -> str:
        """Return a text description of an image at *image_url*.

        Requires the auxiliary model to support vision (e.g. gpt-4o-mini).
        Returns an empty string on failure.
        """
        if not self.enabled:
            return ""
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe this image briefly."},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    }
                ],
                max_tokens=self.max_tokens,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            logger.warning("Auxiliary image description failed: %s", exc)
            return ""

    # ── Internal ─────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        """Lazy-initialize the OpenAI-compatible client."""
        if self._client is not None:
            return self._client

        import os

        from openai import OpenAI

        api_key = self.api_key or os.environ.get("OPENAI_API_KEY", "")
        kwargs: dict[str, Any] = {"api_key": api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self._client = OpenAI(**kwargs)
        return self._client
