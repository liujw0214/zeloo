"""Tests for provider_router resolve-cache + transport-adapter cache."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

from agent.provider_router import (
    _RESOLVE_CACHE_TTL_S,
    ProviderConfig,
    ProviderRouter,
)


def _router() -> ProviderRouter:
    return ProviderRouter(
        providers=[
            ProviderConfig(
                name="openai", model="gpt-4o", api_key="sk-test", priority=0
            ),
            ProviderConfig(
                name="anthropic", model="claude", api_key="sk-ant", priority=1
            ),
        ]
    )


class TestResolveCache:
    def test_first_call_resolves_and_caches(self) -> None:
        router = _router()
        with patch.object(
            ProviderConfig, "resolve", wraps=ProviderConfig.resolve, autospec=True
        ) as mock:
            r1 = router.resolve_cached("openai")
            assert r1 is not None
            assert r1.api_key == "sk-test"
            assert mock.call_count == 1

            # Second call within TTL should NOT re-resolve.
            r2 = router.resolve_cached("openai")
            assert r2 is not None
            assert mock.call_count == 1

    def test_cache_expires_after_ttl(self) -> None:
        router = _router()
        # First call seeds the cache.
        router.resolve_cached("openai")
        # Force expiry.
        router._resolved_cache["openai"] = (
            router._resolved_cache["openai"][0],
            time.time() - 1,
        )
        with patch.object(ProviderConfig, "resolve", autospec=True) as mock:
            router.resolve_cached("openai")
            assert mock.call_count == 1

    def test_unknown_provider_returns_none(self) -> None:
        router = _router()
        assert router.resolve_cached("missing") is None

    def test_invalidate_resolve_cache_all(self) -> None:
        router = _router()
        router.resolve_cached("openai")
        router.resolve_cached("anthropic")
        assert len(router._resolved_cache) == 2
        router.invalidate_resolve_cache()
        assert router._resolved_cache == {}

    def test_invalidate_resolve_cache_one(self) -> None:
        router = _router()
        router.resolve_cached("openai")
        router.resolve_cached("anthropic")
        router.invalidate_resolve_cache("openai")
        assert "openai" not in router._resolved_cache
        assert "anthropic" in router._resolved_cache

    def test_add_provider_invalidates_cache(self) -> None:
        router = _router()
        router.resolve_cached("openai")
        assert "openai" in router._resolved_cache
        router.add_provider(
            ProviderConfig(name="openai", model="gpt-4o", api_key="sk-test")
        )
        assert "openai" not in router._resolved_cache


class TestClientCache:
    def test_client_returned_from_cache(self) -> None:
        router = _router()
        # Stub OpenAI client creation so we don't hit the network.
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value = "client-1"
            c1 = router.get_client("openai")
            c2 = router.get_client("openai")
        assert c1 == "client-1"
        assert c2 == "client-1"
        assert mock_openai.call_count == 1

    def test_get_client_unknown_raises(self) -> None:
        router = _router()
        try:
            router.get_client("missing")
        except ValueError as exc:
            assert "missing" in str(exc)
        else:
            raise AssertionError("expected ValueError")


class TestTransportCache:
    def test_transport_returned_from_cache(self) -> None:
        router = _router()
        # openai has no transport adapter by default.
        # Patch a fake adapter class into the registry.
        from agent.provider_router import _TRANSPORT_ADAPTERS

        class FakeAdapter:
            def __init__(self, api_key: str = "", base_url: str | None = None) -> None:
                self.api_key = api_key
                self.base_url = base_url

            def chat_completion(self, *args: Any, **kwargs: Any) -> Any:  # noqa: D401
                return None

        _TRANSPORT_ADAPTERS["openai"] = FakeAdapter
        try:
            t1 = router.get_transport("openai")
            t2 = router.get_transport("openai")
            assert t1 is t2
            assert isinstance(t1, FakeAdapter)
            assert t1.api_key == "sk-test"
        finally:
            del _TRANSPORT_ADAPTERS["openai"]

    def test_transport_unknown_provider_returns_none(self) -> None:
        # Mock the registry empty AND drop any cached adapter from prior tests
        # so the lookup goes through the slow path.
        from agent.provider_router import _TRANSPORT_ADAPTERS

        router = _router()
        router._transports.clear()
        # Replace _register_transports with a no-op so a prior test's
        # call to ``get_transport("openai")`` doesn't leak the adapter
        # list into this test.
        with patch(
            "agent.provider_router._register_transports", lambda: None
        ):
            assert router.get_transport("openai") is None
            assert router.get_transport("anthropic") is None
        # Sanity: the registry was not mutated.
        assert "anthropic" not in _TRANSPORT_ADAPTERS


class TestResolveCacheConstants:
    def test_ttl_is_positive(self) -> None:
        assert _RESOLVE_CACHE_TTL_S > 0
        assert _RESOLVE_CACHE_TTL_S < 600  # not too long, otherwise stale rotation