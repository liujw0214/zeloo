"""Multi-provider routing with automatic failover.

When the primary LLM provider fails (network error, rate limit, 5xx),
the router transparently retries with the next configured provider. This
keeps the agent resilient to provider outages.

Configuration sources (in priority order):
1. Explicit ``providers`` list passed to :class:`ProviderRouter`.
2. ``zeloo_FALLBACK_PROVIDERS`` env var — comma-separated provider names.
3. ``zeloo_PROVIDER`` / ``zeloo_MODEL`` env vars for the primary.

Each provider resolves its credentials from standard env vars:
* openai:    ``OPENAI_API_KEY``
* deepseek:  ``DEEPSEEK_API_KEY``, base_url ``https://api.deepseek.com/v1``
* gemini:    ``GEMINI_API_KEY``, base_url ``https://generativelanguage.googleapis.com/v1beta/openai/``
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from agent.credential_pool import CredentialPool
from agent.error_classifier import classify_error
from agent.transports.base import (
    Response,
    TransportAdapter,
)

logger = logging.getLogger(__name__)

_TRANSPORT_ADAPTERS: dict[str, type[TransportAdapter]] = {}


def _register_transports() -> None:
    """Lazily register all available transport adapters."""
    if _TRANSPORT_ADAPTERS:
        return
    try:
        from agent.transports.anthropic_adapter import AnthropicAdapter
        _TRANSPORT_ADAPTERS["anthropic"] = AnthropicAdapter
    except Exception:
        pass
    try:
        from agent.transports.gemini_native_adapter import GeminiNativeAdapter
        _TRANSPORT_ADAPTERS["gemini"] = GeminiNativeAdapter
    except Exception:
        pass
    try:
        from agent.transports.bedrock_adapter import BedrockAdapter
        _TRANSPORT_ADAPTERS["bedrock"] = BedrockAdapter
    except Exception:
        pass
    try:
        from agent.transports.azure_identity_adapter import AzureIdentityAdapter
        _TRANSPORT_ADAPTERS["azure"] = AzureIdentityAdapter
    except Exception:
        pass
    try:
        from agent.transports.codex_runtime import CodexRuntime
        _TRANSPORT_ADAPTERS["codex"] = CodexRuntime
    except Exception:
        pass

# Lazy-initialized credential pool for multi-key rotation
_credential_pool: CredentialPool | None = None


def _get_credential_pool() -> CredentialPool:
    """Return the singleton credential pool (created on first use)."""
    global _credential_pool
    if _credential_pool is None:
        storage = os.environ.get("zeloo_CREDENTIAL_STORAGE")
        _credential_pool = CredentialPool(storage_path=storage)
    return _credential_pool

# Known providers with their default base URLs
# NOTE: Anthropic does not offer a native OpenAI-compatible endpoint.
# Set zeloo_BASE_URL to an OpenAI-compatible proxy (e.g. LiteLLM, OpenRouter)
# when using the "anthropic" provider, or use "openrouter" with an Anthropic model.
_KNOWN_PROVIDERS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "together": "https://api.together.xyz/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "anthropic": "",  # requires zeloo_BASE_URL (OpenAI-compatible proxy)
}

# Env var mapping: provider -> API key env var
_PROVIDER_KEY_ENVS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "together": "TOGETHER_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""

    name: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    priority: int = 0  # lower = higher priority

    def resolve(self) -> ProviderConfig:
        """Return a copy with base_url and api_key resolved from defaults/env.

        If no static API key is configured (env var), the resolver falls
        back to an OAuth access token obtained via the device-code flow
        (see :mod:`agent.oauth`). This allows providers like Codex that
        do not issue API keys to work transparently.
        """
        base_url = self.base_url or _KNOWN_PROVIDERS.get(self.name)
        api_key = self.api_key
        if not api_key:
            # 1. Try credential pool first (multi-key rotation)
            try:
                pool = _get_credential_pool()
                pool_key = pool.get_key(self.name)
                if pool_key:
                    api_key = pool_key
            except Exception:
                logger.debug("Credential pool lookup failed for %s", self.name, exc_info=True)
        if not api_key:
            env_name = _PROVIDER_KEY_ENVS.get(self.name)
            if env_name:
                api_key = os.environ.get(env_name, "")
        if not api_key:
            try:
                from agent.oauth import get_access_token

                api_key = get_access_token(self.name) or ""
            except Exception:
                api_key = ""
        return ProviderConfig(
            name=self.name,
            model=self.model,
            base_url=base_url,
            api_key=api_key,
            priority=self.priority,
        )

    def is_configured(self) -> bool:
        """Return True if this provider has an API key available."""
        resolved = self.resolve()
        return bool(resolved.api_key)


# How long a resolved provider config stays cached. Resolving consults
# the credential pool, env vars and OAuth — each a possible network or
# disk call. Caching for a short window collapses the per-turn overhead
# from O(resolution_cost) to O(1) per call without making rotation stale.
_RESOLVE_CACHE_TTL_S = 30.0


class ProviderRouter:
    """Routes LLM calls across multiple providers with failover."""

    def __init__(self, providers: list[ProviderConfig] | None = None) -> None:
        self._providers: list[ProviderConfig] = []
        self._clients: dict[str, Any] = {}
        # Resolved-config cache: ``name -> (resolved, expires_at)``.
        # Re-resolution on every call re-walks the credential pool, env
        # vars and OAuth module — caching for ``_RESOLVE_CACHE_TTL_S``
        # collapses that to a single dict lookup in the hot path.
        self._resolved_cache: dict[str, tuple[ProviderConfig, float]] = {}
        # Transport adapter cache — adapter construction can be expensive
        # (auth handshakes, HTTP client pools). Reuse across calls.
        self._transports: dict[str, TransportAdapter] = {}
        # Per-provider circuit-breaker state. ``open_until > now`` means
        # the provider is currently considered broken and should be
        # skipped in ``call_with_fallback`` rather than retried.
        self._circuit_open_until: dict[str, float] = {}

        if providers:
            for p in providers:
                self.add_provider(p)
        else:
            self._auto_configure()

    def _is_provider_circuit_open(self, provider_name: str) -> bool:
        """Return True if the circuit-breaker is currently open for *provider_name*."""
        until = self._circuit_open_until.get(provider_name, 0.0)
        return until > time.time()

    def trip_provider_circuit(
        self,
        provider_name: str,
        cooldown_seconds: float = 60.0,
    ) -> None:
        """Manually trip the circuit breaker for *provider_name*.

        Future ``call_with_fallback`` calls will skip the provider until
        the cooldown elapses. Used after auth failures or repeated
        server-side errors.
        """
        self._circuit_open_until[provider_name] = time.time() + cooldown_seconds
        # Also drop the resolved-config cache so a fresh key from the
        # pool can be picked up on the next call after the cooldown.
        self._resolved_cache.pop(provider_name, None)
        logger.warning(
            "Circuit breaker tripped for '%s' — cooldown %.1fs",
            provider_name,
            cooldown_seconds,
        )

    def reset_provider_circuit(self, provider_name: str) -> None:
        """Clear the circuit breaker for *provider_name*."""
        self._circuit_open_until.pop(provider_name, None)

    def add_provider(self, config: ProviderConfig) -> None:
        """Add a provider to the router (sorted by priority)."""
        resolved = config.resolve()
        if not resolved.is_configured():
            logger.debug("Skipping unconfigured provider: %s", config.name)
            return
        self._providers.append(resolved)
        self._providers.sort(key=lambda p: p.priority)
        # Invalidate caches that depend on the provider list.
        self._resolved_cache.pop(resolved.name, None)
        self._clients.pop(resolved.name, None)
        self._transports.pop(resolved.name, None)
        logger.info(
            "Provider added: %s (model=%s, priority=%d)",
            resolved.name, resolved.model, resolved.priority,
        )

    def _auto_configure(self) -> None:
        """Build the provider list from environment variables."""
        primary_name = os.environ.get("zeloo_PROVIDER", "openai")
        primary_model = os.environ.get("zeloo_MODEL", "gpt-4o")

        self.add_provider(ProviderConfig(name=primary_name, model=primary_model, priority=0))

        fallback_str = os.environ.get("zeloo_FALLBACK_PROVIDERS", "")
        if fallback_str:
            for i, name in enumerate(fallback_str.split(","), start=1):
                name = name.strip()
                if not name:
                    continue
                model = os.environ.get(f"zeloo_{name.upper()}_MODEL", "gpt-4o-mini")
                self.add_provider(ProviderConfig(name=name, model=model, priority=i))

    @property
    def providers(self) -> list[ProviderConfig]:
        """Return the list of configured providers."""
        return list(self._providers)

    @property
    def primary(self) -> ProviderConfig | None:
        """Return the primary (highest-priority) provider."""
        return self._providers[0] if self._providers else None

    def get_client(self, provider_name: str) -> Any:
        """Get or create an OpenAI client for the given provider."""
        if provider_name in self._clients:
            return self._clients[provider_name]

        config = self.resolve_cached(provider_name)
        if config is None:
            raise ValueError(f"Unknown provider: {provider_name}")

        from openai import OpenAI

        kwargs: dict[str, Any] = {"api_key": config.api_key or ""}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        client = OpenAI(**kwargs)
        self._clients[provider_name] = client
        return client

    def resolve_cached(self, provider_name: str) -> ProviderConfig | None:
        """Return a cached resolved config, refreshing if stale.

        Resolves the *first* provider whose name matches. Caches the
        result for ``_RESOLVE_CACHE_TTL_S``. Callers that have just
        rotated credentials (e.g. ``pool.report_failure``) should call
        :meth:`invalidate_resolve_cache` so the next lookup picks up the
        fresh key.
        """
        now = time.time()
        cached = self._resolved_cache.get(provider_name)
        if cached is not None and cached[1] > now:
            return cached[0]

        base = next(
            (p for p in self._providers if p.name == provider_name), None
        )
        if base is None:
            return None
        resolved = base.resolve()
        self._resolved_cache[provider_name] = (resolved, now + _RESOLVE_CACHE_TTL_S)
        return resolved

    def invalidate_resolve_cache(self, provider_name: str | None = None) -> None:
        """Drop one (or all) cached resolved config(s)."""
        if provider_name is None:
            self._resolved_cache.clear()
        else:
            self._resolved_cache.pop(provider_name, None)

    def call_with_fallback(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        stream: bool = False,
    ) -> Any:
        """Call the LLM, failing over to the next provider on error.

        Returns the OpenAI response object (or a stream iterator if
        ``stream=True``).

        Circuit breaker: providers whose auth/circuit is open or whose
        credentials have just been rotated are *skipped* rather than
        tried-and-failed. This saves the latency of a doomed request.
        """
        if not self._providers:
            raise RuntimeError("No configured providers available")

        last_error: Exception | None = None
        for provider in self._providers:
            # Skip providers whose circuit is currently broken — retrying
            # them would just waste a request slot.
            if self._is_provider_circuit_open(provider.name):
                logger.debug(
                    "Skipping '%s' — circuit breaker is open",
                    provider.name,
                )
                continue
            config = self.resolve_cached(provider.name) or provider.resolve()
            try:
                client = self.get_client(provider.name)
                kwargs: dict[str, Any] = {
                    "model": provider.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": stream,
                }
                if tools:
                    kwargs["tools"] = tools

                response = client.chat.completions.create(**kwargs)
                if provider is not self._providers[0]:
                    logger.info("Failover succeeded using provider: %s", provider.name)
                return response
            except Exception as e:
                last_error = e
                classification = classify_error(e, provider=provider.name)
                # Report failure to credential pool for key rotation. The
                # pool internally rotates the active key on each failure,
                # so we must invalidate the resolver cache here — otherwise
                # the next call would re-use the dead key.
                try:
                    pool = _get_credential_pool()
                    pool.report_failure(
                        provider.name,
                        config.api_key or "",
                        status_code=classification.status_code,
                    )
                    self.invalidate_resolve_cache(provider.name)
                except Exception:
                    pass
                # On AUTH failures, also trip the circuit breaker so the
                # next call skips this provider rather than re-trying with
                # a freshly-rotated key. The cooldown (60 s) is short
                # enough that the pool can re-issue a credential.
                if classification.category.value == "auth":
                    self.trip_provider_circuit(
                        provider.name,
                        cooldown_seconds=60.0,
                    )
                logger.warning(
                    "Provider %s failed [%s]: %s. retryable=%s, fallback=%s",
                    provider.name,
                    classification.category.value,
                    classification.message[:120],
                    classification.retryable,
                    classification.should_fallback_provider,
                )
                # If the error is not retryable and doesn't suggest fallback,
                # stop trying other providers immediately.
                if not classification.retryable and not classification.should_fallback_provider:
                    logger.info("Error not retryable, skipping remaining providers")
                    break
                # Honor retry delay for rate limits / timeouts
                if classification.retryable and classification.retry_delay_seconds > 0:
                    time.sleep(min(classification.retry_delay_seconds, 5.0))
                continue

        raise RuntimeError(f"All providers failed. Last error: {last_error}")

    def get_transport(self, provider_name: str) -> TransportAdapter | None:
        """Get or create a TransportAdapter for the given provider.

        Returns None if the provider does not have a registered adapter.
        Adapters are cached in ``self._transports`` so a long session does
        not reconstruct the underlying HTTP client on every call.
        """
        cached = self._transports.get(provider_name)
        if cached is not None:
            return cached

        _register_transports()
        adapter_cls = _TRANSPORT_ADAPTERS.get(provider_name)
        if not adapter_cls:
            return None

        config = self.resolve_cached(provider_name)
        if not config:
            return None

        try:
            adapter = adapter_cls(
                api_key=config.api_key or "",
                base_url=config.base_url,
            )
        except Exception:
            return None
        self._transports[provider_name] = adapter
        return adapter

    def call_with_transport(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> Response:
        """Call the LLM using a TransportAdapter (provider-native protocol).

        Falls back to OpenAI-compatible call_with_fallback if no
        TransportAdapter is registered for the provider.

        Circuit breaker: providers whose circuit is open are skipped
        (matching :meth:`call_with_fallback`).
        """
        if not self._providers:
            raise RuntimeError("No configured providers available")

        last_error: Exception | None = None
        primary_name = self.primary.name if self.primary else None

        for provider in self._providers:
            # Skip providers whose circuit is currently broken.
            if self._is_provider_circuit_open(provider.name):
                continue
            # Try the provider's TransportAdapter; if absent, fall
            # back to the OpenAI SDK via ``call_with_fallback`` semantics.
            transport = self.get_transport(provider.name)
            resolved = self.resolve_cached(provider.name) or provider.resolve()
            effective_model = model or resolved.model

            try:
                if transport is None:
                    logger.debug(
                        "No transport adapter for '%s', falling back to OpenAI SDK",
                        provider.name,
                    )
                    response = self.call_with_fallback(
                        messages=messages,
                        tools=tools,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=stream,
                    )
                    return self._openai_response_to_standard(response, model)

                resp = transport.chat_completion(
                    messages=messages,
                    model=effective_model,
                    tools=tools,
                    stream=stream,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                if primary_name and provider.name != primary_name:
                    logger.info(
                        "Transport failover succeeded: %s", provider.name
                    )
                return resp
            except Exception as ex:
                last_error = ex
                classification = classify_error(ex, provider=provider.name)
                # AUTH → trip the circuit breaker so the next call
                # skips this provider.
                if classification.category.value == "auth":
                    self.trip_provider_circuit(
                        provider.name,
                        cooldown_seconds=60.0,
                    )
                logger.warning(
                    "Transport '%s' failed [%s]: %s",
                    provider.name,
                    classification.category.value,
                    ex,
                )
                # Non-retryable, no fallback worth trying → stop.
                if (
                    not classification.retryable
                    and not classification.should_fallback_provider
                ):
                    logger.info(
                        "Error not retryable, stopping transport failover"
                    )
                    break
                continue

        msg = f"All transport providers failed. Last error: {last_error}"
        raise RuntimeError(msg) from None

    def _openai_response_to_standard(
        self, raw_response: Any, model: str
    ) -> Response:
        """Convert an OpenAI SDK response to a standardized Response."""
        try:
            choice = raw_response.choices[0]
            content = choice.message.content or ""
            finish_reason = str(choice.finish_reason or "")
            tool_calls = []
            if hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    })
            usage = raw_response.usage
            return Response(
                content=content,
                model=model,
                finish_reason=finish_reason,
                usage_in=usage.prompt_tokens if usage else 0,
                usage_out=usage.completion_tokens if usage else 0,
                tool_calls=tool_calls,
            )
        except Exception:
            return Response(content=str(raw_response), model=model)


# ── Smart Model Routing ─────────────────────────────────────────────

# Keywords that indicate a complex request requiring the primary model.
# Matched case-insensitively against the user's input.
_COMPLEX_KEYWORDS = frozenset({
    "debug", "error", "bug", "fix", "implement", "refactor", "rewrite",
    "deploy", "optimize", "optimise", "architect", "architecture", "design",
    "security", "vulnerability", "audit", "migrate", "migration",
    "complex", "tricky", "difficult", "hard", "challenge",
    "explain", "analyze", "analyse", "review", "evaluate", "investigate",
    "code", "function", "algorithm", "database", "sql", "api", "backend",
    "frontend", "infrastructure", "ci", "cd", "pipeline", "kubernetes",
    "docker", "compose", "nginx", "ssl", "certificate", "oauth",
})


@dataclass
class SmartRoutingConfig:
    """Configuration for smart model routing."""

    enabled: bool = False
    max_simple_chars: int = 160
    max_simple_words: int = 28
    cheap_provider: str = "openai"
    cheap_model: str = "gpt-4o-mini"


class SmartModelRouter:
    """Route simple requests to a cheaper model automatically.

    A request is considered "simple" when:
      * Its character count is below ``max_simple_chars``, AND
      * Its word count is below ``max_simple_words``, AND
      * It does not contain any complex-skill keywords.

    Otherwise the primary model is used.
    """

    def __init__(self, config: SmartRoutingConfig | None = None) -> None:
        self.config = config or SmartRoutingConfig()

    def is_simple(self, user_input: str) -> bool:
        """Return True if *user_input* should use the cheap model."""
        if not self.config.enabled or not user_input:
            return False
        if len(user_input) > self.config.max_simple_chars:
            return False
        if len(user_input.split()) > self.config.max_simple_words:
            return False
        lower = user_input.lower()
        return not any(kw in lower for kw in _COMPLEX_KEYWORDS)

    def select(
        self,
        user_input: str,
        primary_provider: str,
        primary_model: str,
    ) -> tuple[str, str]:
        """Return ``(provider, model)`` for the given input.

        If the input is simple and the cheap provider differs from the
        primary, returns the cheap provider/model. Otherwise returns the
        primary provider/model.
        """
        if self.is_simple(user_input) and (
            self.config.cheap_provider != primary_provider
            or self.config.cheap_model != primary_model
        ):
            return self.config.cheap_provider, self.config.cheap_model
        return primary_provider, primary_model

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> SmartModelRouter:
        """Build a :class:`SmartModelRouter` from a config dict.

        Reads ``smart_model_routing`` section with keys:
        ``enabled``, ``max_simple_chars``, ``max_simple_words``,
        ``cheap_provider``, ``cheap_model``.
        """
        smr = (config or {}).get("smart_model_routing", {}) if isinstance(config, dict) else {}
        if not isinstance(smr, dict):
            smr = {}
        cfg = SmartRoutingConfig(
            enabled=bool(smr.get("enabled", False)),
            max_simple_chars=int(smr.get("max_simple_chars", 160)),
            max_simple_words=int(smr.get("max_simple_words", 28)),
            cheap_provider=str(smr.get("cheap_provider", "openai")),
            cheap_model=str(smr.get("cheap_model", "gpt-4o-mini")),
        )
        return cls(cfg)
