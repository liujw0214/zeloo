"""Model list auto-updater.

Maintains an up-to-date catalogue of models for each provider supported
by Zeloo. The catalogue is composed of three sources:

1. ``ModelSource.STATIC``     — hard-coded fallback list (always available).
2. ``ModelSource.API``        — provider-specific fetchers that hit the
   vendor's ``/v1/models`` endpoint or equivalent.
3. ``ModelSource.OPENAI_COMPAT`` — generic OpenAI-compatible
   ``GET /v1/models`` endpoint, used by OpenRouter and any
   self-hosted proxy that mirrors the OpenAI shape.

Results are persisted to a JSON cache file so the runtime can avoid
hitting remote endpoints on every startup. The cache TTL defaults to
24 hours and is configurable per-instance.

Typical usage::

    updater = ModelUpdater(cache_path=Path("~/.Zeloo/models.json").expanduser())
    openai_models = updater.get_models("openai")
    everything = updater.update_all()
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = Path.home() / ".Zeloo" / "models_cache.json"
DEFAULT_TTL_HOURS = 24
PROBE_TIMEOUT_S = 10.0


class ModelSource(Enum):
    """Origin of a :class:`ModelInfo` record."""

    STATIC = "static"            # Hard-coded fallback list.
    API = "api"                  # Provider-specific fetcher.
    OPENAI_COMPAT = "openai_compat"  # Generic OpenAI-compatible /v1/models.


@dataclass
class ModelInfo:
    """Description of a single chat-completion model."""

    id: str
    provider: str
    display_name: str
    context_length: int
    input_cost_per_1k: float    # USD per 1k input tokens.
    output_cost_per_1k: float   # USD per 1k output tokens.
    supports_vision: bool = False
    supports_tools: bool = False
    supports_streaming: bool = True
    release_date: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dictionary."""
        data = asdict(self)
        if self.release_date is not None:
            data["release_date"] = self.release_date.isoformat()
        return data

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ModelInfo:
        """Inverse of :meth:`to_dict`."""
        release = payload.get("release_date")
        if isinstance(release, str):
            try:
                payload["release_date"] = datetime.fromisoformat(release)
            except ValueError:
                payload["release_date"] = None
        return cls(**payload)


# ---------------------------------------------------------------------------
# Static catalogues. Kept short and conservative; live fetches supplement
# them with the latest vendor list.
# ---------------------------------------------------------------------------

_STATIC_MODELS: dict[str, list[ModelInfo]] = {
    "openai": [
        ModelInfo(
            id="gpt-4o", provider="openai", display_name="GPT-4o",
            context_length=128_000, input_cost_per_1k=0.005, output_cost_per_1k=0.015,
            supports_vision=True, supports_tools=True,
            release_date=datetime(2024, 5, 13, tzinfo=timezone.utc),
        ),
        ModelInfo(
            id="gpt-4o-mini", provider="openai", display_name="GPT-4o mini",
            context_length=128_000, input_cost_per_1k=0.00015, output_cost_per_1k=0.0006,
            supports_vision=True, supports_tools=True,
            release_date=datetime(2024, 7, 18, tzinfo=timezone.utc),
        ),
        ModelInfo(
            id="gpt-4-turbo", provider="openai", display_name="GPT-4 Turbo",
            context_length=128_000, input_cost_per_1k=0.01, output_cost_per_1k=0.03,
            supports_vision=True, supports_tools=True,
            release_date=datetime(2024, 4, 9, tzinfo=timezone.utc),
        ),
        ModelInfo(
            id="gpt-3.5-turbo", provider="openai", display_name="GPT-3.5 Turbo",
            context_length=16_385, input_cost_per_1k=0.0005, output_cost_per_1k=0.0015,
            supports_tools=True,
        ),
        ModelInfo(
            id="o1-preview", provider="openai", display_name="o1-preview",
            context_length=128_000, input_cost_per_1k=0.015, output_cost_per_1k=0.06,
            supports_vision=False, supports_tools=False,
            release_date=datetime(2024, 9, 12, tzinfo=timezone.utc),
        ),
        ModelInfo(
            id="o1-mini", provider="openai", display_name="o1-mini",
            context_length=128_000, input_cost_per_1k=0.003, output_cost_per_1k=0.012,
            supports_vision=False, supports_tools=False,
            release_date=datetime(2024, 9, 12, tzinfo=timezone.utc),
        ),
    ],
    "anthropic": [
        ModelInfo(
            id="claude-3-5-sonnet", provider="anthropic",
            display_name="Claude 3.5 Sonnet", context_length=200_000,
            input_cost_per_1k=0.003, output_cost_per_1k=0.015,
            supports_vision=True, supports_tools=True,
            release_date=datetime(2024, 10, 22, tzinfo=timezone.utc),
        ),
        ModelInfo(
            id="claude-3-5-haiku", provider="anthropic",
            display_name="Claude 3.5 Haiku", context_length=200_000,
            input_cost_per_1k=0.0008, output_cost_per_1k=0.004,
            supports_vision=True, supports_tools=True,
            release_date=datetime(2024, 11, 4, tzinfo=timezone.utc),
        ),
        ModelInfo(
            id="claude-3-opus", provider="anthropic",
            display_name="Claude 3 Opus", context_length=200_000,
            input_cost_per_1k=0.015, output_cost_per_1k=0.075,
            supports_vision=True, supports_tools=True,
            release_date=datetime(2024, 2, 29, tzinfo=timezone.utc),
        ),
        ModelInfo(
            id="claude-3-haiku", provider="anthropic",
            display_name="Claude 3 Haiku", context_length=200_000,
            input_cost_per_1k=0.00025, output_cost_per_1k=0.00125,
            supports_vision=True, supports_tools=True,
            release_date=datetime(2024, 3, 13, tzinfo=timezone.utc),
        ),
    ],
    "google": [
        ModelInfo(
            id="gemini-1.5-pro", provider="google",
            display_name="Gemini 1.5 Pro", context_length=2_000_000,
            input_cost_per_1k=0.00125, output_cost_per_1k=0.005,
            supports_vision=True, supports_tools=True,
        ),
        ModelInfo(
            id="gemini-1.5-flash", provider="google",
            display_name="Gemini 1.5 Flash", context_length=1_000_000,
            input_cost_per_1k=0.000075, output_cost_per_1k=0.0003,
            supports_vision=True, supports_tools=True,
        ),
        ModelInfo(
            id="gemini-2.0-flash", provider="google",
            display_name="Gemini 2.0 Flash", context_length=1_000_000,
            input_cost_per_1k=0.0001, output_cost_per_1k=0.0004,
            supports_vision=True, supports_tools=True,
        ),
    ],
    "deepseek": [
        ModelInfo(
            id="deepseek-chat", provider="deepseek",
            display_name="DeepSeek Chat", context_length=128_000,
            input_cost_per_1k=0.00027, output_cost_per_1k=0.0011,
            supports_tools=True,
        ),
        ModelInfo(
            id="deepseek-reasoner", provider="deepseek",
            display_name="DeepSeek Reasoner", context_length=128_000,
            input_cost_per_1k=0.00055, output_cost_per_1k=0.00219,
            supports_tools=False,
        ),
    ],
    "groq": [
        ModelInfo(
            id="llama-3.1-70b", provider="groq",
            display_name="Llama 3.1 70B (Groq)", context_length=128_000,
            input_cost_per_1k=0.00059, output_cost_per_1k=0.00079,
            supports_tools=True,
        ),
        ModelInfo(
            id="mixtral-8x7b", provider="groq",
            display_name="Mixtral 8x7B (Groq)", context_length=32_768,
            input_cost_per_1k=0.00027, output_cost_per_1k=0.00027,
            supports_tools=True,
        ),
    ],
    "mistral": [
        ModelInfo(
            id="mistral-large", provider="mistral",
            display_name="Mistral Large", context_length=128_000,
            input_cost_per_1k=0.004, output_cost_per_1k=0.012,
            supports_tools=True,
        ),
        ModelInfo(
            id="mistral-small", provider="mistral",
            display_name="Mistral Small", context_length=128_000,
            input_cost_per_1k=0.001, output_cost_per_1k=0.003,
            supports_tools=True,
        ),
    ],
    "xai": [
        ModelInfo(
            id="grok-2", provider="xai",
            display_name="Grok 2", context_length=131_072,
            input_cost_per_1k=0.002, output_cost_per_1k=0.01,
            supports_vision=True, supports_tools=True,
        ),
        ModelInfo(
            id="grok-2-mini", provider="xai",
            display_name="Grok 2 mini", context_length=131_072,
            input_cost_per_1k=0.0002, output_cost_per_1k=0.001,
            supports_tools=True,
        ),
    ],
}


# ---------------------------------------------------------------------------
# Provider endpoints used by the API fetchers.
# ---------------------------------------------------------------------------

_API_ENDPOINTS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
}


class ModelUpdater:
    """Resolve and refresh model catalogues for known providers.

    The updater is intentionally synchronous: callers wrap it in
    ``asyncio.to_thread`` if they need non-blocking behaviour. The class
    itself never raises — it logs warnings and falls back to static
    catalogues when remote fetches fail.
    """

    def __init__(
        self,
        cache_path: Path | None = None,
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> None:
        self._cache_path = cache_path or DEFAULT_CACHE_PATH
        self._ttl = timedelta(hours=ttl_hours)
        self._cache: dict[str, list[ModelInfo]] = {}
        self._timestamps: dict[str, datetime] = {}
        self._load_cache()

    # ----- public API ---------------------------------------------------

    def get_models(self, provider: str) -> list[ModelInfo]:
        """Return the current catalogue for *provider*.

        If the cache is fresh the cached list is returned untouched.
        Otherwise ``update_provider`` is called transparently. Falls
        back to the static catalogue when everything else fails.
        """
        if self._is_fresh(provider):
            cached = self._cache.get(provider)
            if cached:
                return list(cached)
        try:
            refreshed = self.update_provider(provider)
            if refreshed:
                return refreshed
        except Exception as exc:  # noqa: BLE001
            logger.warning("Refresh failed for %s: %s", provider, exc)
        return list(_STATIC_MODELS.get(provider, []))

    def update_provider(self, provider: str, force: bool = False) -> list[ModelInfo]:
        """Refresh the catalogue for a single provider.

        When *force* is true the cache is ignored and a remote call is
        always attempted (still falls back to static on failure).
        """
        if not force and self._is_fresh(provider):
            cached = self._cache.get(provider)
            if cached:
                return list(cached)

        try:
            fetched = self.fetch_from_api(provider)
            source = fetched
        except Exception as exc:  # noqa: BLE001
            logger.debug("API fetch failed for %s: %s", provider, exc)
            source = list(_STATIC_MODELS.get(provider, []))

        self._cache[provider] = source
        self._timestamps[provider] = datetime.now(timezone.utc)
        self._save_cache()
        return list(source)

    def update_all(self, force: bool = False) -> dict[str, list[ModelInfo]]:
        """Refresh every provider with a known static catalogue."""
        results: dict[str, list[ModelInfo]] = {}
        for provider in list(_STATIC_MODELS.keys()) + ["openrouter"]:
            try:
                results[provider] = self.update_provider(provider, force=force)
            except Exception as exc:  # noqa: BLE001
                logger.warning("update_all: skipping %s due to %s", provider, exc)
                results[provider] = list(_STATIC_MODELS.get(provider, []))
        return results

    def get_provider_static_models(self, provider: str) -> list[ModelInfo]:
        """Return the hard-coded catalogue for *provider*."""
        return list(_STATIC_MODELS.get(provider, []))

    def fetch_from_api(self, provider: str) -> list[ModelInfo]:
        """Dispatch to the appropriate provider fetcher."""
        if provider == "openai":
            return self._fetch_openai_models()
        if provider == "anthropic":
            return self._fetch_anthropic_models()
        if provider == "openrouter":
            return self._fetch_openrouter_models()
        # Generic OpenAI-compatible endpoint — try anyway, then fall back.
        api_key = os.environ.get(f"{provider.upper()}_API_KEY")
        base = os.environ.get(f"{provider.upper()}_BASE_URL", _API_ENDPOINTS.get(provider, ""))
        if base:
            return self.fetch_openai_compatible(base, api_key)
        return list(_STATIC_MODELS.get(provider, []))

    def fetch_openai_compatible(
        self,
        base_url: str,
        api_key: str | None = None,
    ) -> list[ModelInfo]:
        """Hit a generic OpenAI-compatible ``GET /v1/models`` endpoint.

        Returns an empty list on any error — callers fall back to the
        static catalogue.
        """
        url = base_url.rstrip("/")
        if not url.endswith("/v1/models"):
            url = f"{url}/v1/models" if url.endswith("/v1") else f"{url}/v1/models"
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            with httpx.Client(timeout=PROBE_TIMEOUT_S) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI-compat fetch failed (%s): %s", url, exc)
            return []

        provider_label = self._infer_provider_from_url(base_url)
        out: list[ModelInfo] = []
        for entry in payload.get("data", []):
            if not isinstance(entry, dict):
                continue
            model_id = entry.get("id")
            if not model_id:
                continue
            out.append(ModelInfo(
                id=str(model_id),
                provider=provider_label,
                display_name=str(entry.get("name") or model_id),
                context_length=int(entry.get("context_length") or 0),
                input_cost_per_1k=0.0,
                output_cost_per_1k=0.0,
                supports_vision=bool(entry.get("supports_vision", False)),
                supports_tools=bool(entry.get("supports_tools", False)),
                supports_streaming=bool(entry.get("supports_streaming", True)),
                metadata={"raw": entry},
            ))
        return out

    def clear_cache(self, provider: str | None = None) -> None:
        """Clear the cache for one provider, or all of them."""
        if provider is None:
            self._cache.clear()
            self._timestamps.clear()
        else:
            self._cache.pop(provider, None)
            self._timestamps.pop(provider, None)
        self._save_cache()

    def get_cache_age(self, provider: str) -> timedelta | None:
        """Return how stale the cached catalogue for *provider* is."""
        ts = self._timestamps.get(provider)
        if ts is None:
            return None
        return datetime.now(timezone.utc) - ts

    # ----- provider-specific fetchers -----------------------------------

    def _fetch_openai_models(self) -> list[ModelInfo]:
        """Fetch from OpenAI's ``/v1/models`` endpoint."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.debug("OPENAI_API_KEY not set; skipping remote fetch")
            return list(_STATIC_MODELS.get("openai", []))
        url = _API_ENDPOINTS["openai"]
        try:
            with httpx.Client(timeout=PROBE_TIMEOUT_S) as client:
                resp = client.get(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI /v1/models failed: %s", exc)
            return list(_STATIC_MODELS.get("openai", []))

        static_by_id = {m.id: m for m in _STATIC_MODELS.get("openai", [])}
        out: list[ModelInfo] = []
        for entry in payload.get("data", []):
            model_id = entry.get("id")
            if not isinstance(model_id, str):
                continue
            base = static_by_id.get(model_id)
            if base is not None:
                out.append(base)
                continue
            out.append(ModelInfo(
                id=model_id,
                provider="openai",
                display_name=model_id,
                context_length=0,
                input_cost_per_1k=0.0,
                output_cost_per_1k=0.0,
                metadata={"raw": entry},
            ))
        return out or list(_STATIC_MODELS.get("openai", []))

    def _fetch_anthropic_models(self) -> list[ModelInfo]:
        """Fetch from Anthropic's ``/v1/models`` endpoint."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.debug("ANTHROPIC_API_KEY not set; skipping remote fetch")
            return list(_STATIC_MODELS.get("anthropic", []))
        url = _API_ENDPOINTS["anthropic"]
        try:
            with httpx.Client(timeout=PROBE_TIMEOUT_S) as client:
                resp = client.get(
                    url,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Anthropic /v1/models failed: %s", exc)
            return list(_STATIC_MODELS.get("anthropic", []))

        static_by_id = {m.id: m for m in _STATIC_MODELS.get("anthropic", [])}
        out: list[ModelInfo] = []
        for entry in payload.get("data", []):
            model_id = entry.get("id")
            if not isinstance(model_id, str):
                continue
            base = static_by_id.get(model_id)
            if base is not None:
                out.append(base)
                continue
            out.append(ModelInfo(
                id=model_id,
                provider="anthropic",
                display_name=entry.get("display_name", model_id),
                context_length=0,
                input_cost_per_1k=0.0,
                output_cost_per_1k=0.0,
                metadata={"raw": entry},
            ))
        return out or list(_STATIC_MODELS.get("anthropic", []))

    def _fetch_openrouter_models(self) -> list[ModelInfo]:
        """Fetch from OpenRouter's ``/api/v1/models`` endpoint."""
        return self.fetch_openai_compatible(
            base_url="https://openrouter.ai/api",
            api_key=os.environ.get("OPENROUTER_API_KEY"),
        )

    # ----- cache plumbing ----------------------------------------------

    def _is_fresh(self, provider: str) -> bool:
        ts = self._timestamps.get(provider)
        if ts is None or provider not in self._cache:
            return False
        return (datetime.now(timezone.utc) - ts) < self._ttl

    def _load_cache(self) -> None:
        """Load the on-disk cache if it exists."""
        if not self._cache_path.exists():
            return
        try:
            with open(self._cache_path, encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Cache load failed: %s", exc)
            return
        models = payload.get("models", {}) or {}
        timestamps = payload.get("timestamps", {}) or {}
        for provider, entries in models.items():
            try:
                self._cache[provider] = [ModelInfo.from_dict(e) for e in entries]
            except Exception as exc:  # noqa: BLE001
                logger.debug("Skipping malformed cache entry %s: %s", provider, exc)
        for provider, ts_str in timestamps.items():
            try:
                self._timestamps[provider] = datetime.fromisoformat(ts_str)
            except ValueError:
                continue

    def _save_cache(self) -> None:
        """Persist the in-memory cache to disk (best-effort)."""
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "models": {
                    p: [m.to_dict() for m in models]
                    for p, models in self._cache.items()
                },
                "timestamps": {
                    p: ts.isoformat() for p, ts in self._timestamps.items()
                },
            }
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Cache save failed: %s", exc)

    @staticmethod
    def _infer_provider_from_url(url: str) -> str:
        """Best-effort provider label extraction from a base URL."""
        lowered = url.lower()
        for token in ("openai", "anthropic", "openrouter", "deepseek",
                      "groq", "mistral", "google", "xai", "together",
                      "fireworks", "ollama"):
            if token in lowered:
                return token
        return "custom"


__all__ = [
    "ModelInfo",
    "ModelSource",
    "ModelUpdater",
    "DEFAULT_CACHE_PATH",
    "DEFAULT_TTL_HOURS",
]
