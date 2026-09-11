"""Tests for ProviderRouter circuit breaker."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import pytest

from agent.error_classifier import ErrorCategory, ErrorClassification
from agent.provider_router import ProviderConfig, ProviderRouter


def _router() -> ProviderRouter:
    return ProviderRouter(
        providers=[
            ProviderConfig(name="openai", model="gpt-4o", api_key="sk", priority=0),
            ProviderConfig(name="anthropic", model="claude", api_key="sk-ant", priority=1),
        ]
    )


class TestCircuitState:
    def test_initial_circuit_closed(self) -> None:
        router = _router()
        assert router._is_provider_circuit_open("openai") is False

    def test_trip_opens_circuit(self) -> None:
        router = _router()
        router.trip_provider_circuit("openai", cooldown_seconds=60)
        assert router._is_provider_circuit_open("openai") is True

    def test_circuit_expires(self) -> None:
        router = _router()
        router.trip_provider_circuit("openai", cooldown_seconds=0.05)
        assert router._is_provider_circuit_open("openai") is True
        time.sleep(0.1)
        assert router._is_provider_circuit_open("openai") is False

    def test_reset_provider_circuit(self) -> None:
        router = _router()
        router.trip_provider_circuit("openai", cooldown_seconds=60)
        router.reset_provider_circuit("openai")
        assert router._is_provider_circuit_open("openai") is False

    def test_reset_unknown_provider_safe(self) -> None:
        router = _router()
        # Should not raise even if no circuit was open.
        router.reset_provider_circuit("never-tripped")


class TestCircuitSkipsProvider:
    def test_skipped_provider_in_fallback(self) -> None:
        """When openai's circuit is open, call_with_fallback should
        skip it. We verify this by counting the ``get_client`` calls."""
        router = _router()
        router.trip_provider_circuit("openai", cooldown_seconds=60)

        calls: list[str] = []

        class _OKClient:
            def __init__(self, name: str) -> None:
                self.name = name

            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs: Any) -> Any:
                        response = type("R", (), {})()
                        response.choices = [
                            type("C", (), {
                                "message": type("M", (), {
                                    "content": "ok",
                                    "tool_calls": None,
                                })(),
                                "finish_reason": "stop",
                            })()
                        ]
                        response.usage = type(
                            "U", (), {"prompt_tokens": 1, "completion_tokens": 1}
                        )()
                        return response

        def fake_get_client(name: str) -> _OKClient:
            calls.append(name)
            return _OKClient(name)

        with patch.object(router, "get_client", side_effect=fake_get_client):
            router.call_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
            )
        # openai was skipped — only anthropic was used.
        assert calls == ["anthropic"]

    def test_all_circuits_open_raises(self) -> None:
        router = _router()
        router.trip_provider_circuit("openai", cooldown_seconds=60)
        router.trip_provider_circuit("anthropic", cooldown_seconds=60)
        with pytest.raises(RuntimeError, match="All providers failed"):
            router.call_with_fallback(messages=[{"role": "user", "content": "hi"}])


class TestCircuitInvalidatesResolveCache:
    def test_trip_drops_resolve_cache(self) -> None:
        """When a provider's circuit is tripped, its resolved-config
        cache must also be cleared so the next call after the cooldown
        picks up a freshly-rotated credential."""
        router = _router()
        router.resolve_cached("openai")
        assert "openai" in router._resolved_cache
        router.trip_provider_circuit("openai", cooldown_seconds=60)
        assert "openai" not in router._resolved_cache


class TestCircuitAutoTripOnAuth:
    def test_auth_failure_trips_circuit(self) -> None:
        """Auth failures from call_with_fallback must auto-trip the
        circuit so subsequent calls skip the broken provider."""
        router = _router()

        class _FailClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**_kw: Any) -> None:
                        raise Exception("401 Unauthorized: invalid api key")

        auth_error = ErrorClassification(
            category=ErrorCategory.AUTH,
            message="401 Unauthorized",
            retryable=False,
            retry_delay_seconds=0.0,
            should_fallback_provider=True,
            should_escalate=True,
            status_code=401,
        )

        with (
            patch.object(router, "get_client", return_value=_FailClient()),
            patch("agent.provider_router._get_credential_pool") as mock_pool_fn,
            patch(
                "agent.provider_router.classify_error",
                return_value=auth_error,
            ),
        ):
            mock_pool_fn.return_value = type(
                "P", (), {"report_failure": lambda *a, **kw: None}
            )()
            with pytest.raises(RuntimeError):
                router.call_with_fallback(
                    messages=[{"role": "user", "content": "hi"}],
                )

        # After the auth failure, openai's circuit must be open.
        assert router._is_provider_circuit_open("openai") is True


class TestCallWithTransportCircuitBreaker:
    """``call_with_transport`` shares the circuit-breaker state with
    ``call_with_fallback`` — tripped providers must be skipped on the
    failover path too."""

    def test_skipped_provider_in_transport_failover(self) -> None:
        """If openai's circuit is open, ``call_with_transport`` must
        not even attempt openai — anthropic gets the first try."""
        from agent.provider_router import _TRANSPORT_ADAPTERS

        router = _router()
        router.trip_provider_circuit("openai", cooldown_seconds=60)

        calls: list[str] = []

        class _OKTransport:
            def __init__(self, name: str) -> None:
                self.name = name

            def chat_completion(self, **kwargs: Any) -> Any:
                calls.append(kwargs.get("model", ""))
                from agent.transports.base import Response

                return Response(
                    content="ok",
                    model=self.name,
                    finish_reason="stop",
                    usage_in=1,
                    usage_out=1,
                    tool_calls=[],
                )

        # Register a fake adapter so ``get_transport`` returns our stub.
        saved = dict(_TRANSPORT_ADAPTERS)

        class _AdapterFactory:
            def __init__(self, name: str) -> None:
                self.name = name

            def __call__(self, api_key: str = "", base_url: str | None = None) -> Any:
                return _OKTransport(self.name)

        _TRANSPORT_ADAPTERS["openai"] = _AdapterFactory("openai")
        _TRANSPORT_ADAPTERS["anthropic"] = _AdapterFactory("anthropic")
        try:

            router.call_with_transport(
                messages=[{"role": "user", "content": "hi"}],
                model="",
            )
            # Only anthropic's transport was used.
            assert calls == ["claude"]
        finally:
            # Restore the registry.
            _TRANSPORT_ADAPTERS.clear()
            _TRANSPORT_ADAPTERS.update(saved)

    def test_transport_non_retryable_stops_failover(self) -> None:
        """A non-retryable error must stop the failover loop immediately.

        Without this check the router would keep retrying the
        remaining providers needlessly — wasting requests on a
        classification that's known to be fatal (e.g. context
        overflow / validation).
        """
        from agent.provider_router import _TRANSPORT_ADAPTERS

        router = _router()

        calls: list[str] = []

        class _FailTransport:
            def __init__(self, name: str) -> None:
                self.name = name

            def chat_completion(self, **kwargs: Any) -> None:
                calls.append(self.name)
                raise ValueError("400 context overflow: too many tokens")

        class _AdapterFactory:
            def __init__(self, name: str) -> None:
                self.name = name

            def __call__(self, api_key: str = "", base_url: str | None = None) -> Any:
                return _FailTransport(self.name)

        # Validation / context-overflow errors are NOT retryable and
        # should not trigger further providers.
        non_retryable = ErrorClassification(
            category=ErrorCategory.CONTEXT_OVERFLOW,
            message="context overflow",
            retryable=False,
            retry_delay_seconds=0.0,
            should_fallback_provider=False,
            should_escalate=False,
            status_code=400,
        )

        saved = dict(_TRANSPORT_ADAPTERS)
        _TRANSPORT_ADAPTERS["openai"] = _AdapterFactory("openai")
        _TRANSPORT_ADAPTERS["anthropic"] = _AdapterFactory("anthropic")
        try:
            with patch(
                "agent.provider_router.classify_error",
                return_value=non_retryable,
            ):
                with pytest.raises(RuntimeError):
                    router.call_with_transport(
                        messages=[{"role": "user", "content": "hi"}],
                        model="",
                    )
            # Only the primary (openai) transport was tried —
            # anthropic was correctly skipped because the error was
            # non-retryable. ``calls`` records the *provider name*
            # each transport was constructed with.
            assert calls == ["openai"]
        finally:
            _TRANSPORT_ADAPTERS.clear()
            _TRANSPORT_ADAPTERS.update(saved)