"""Tests for agent/providers/_http.py timeout helper (M1)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

import httpx  # noqa: E402

from agent.providers._http import (  # noqa: E402
    DEFAULT_TIMEOUT,
    DEFAULT_TIMEOUT_S,
    async_get_json,
    async_post_json,
    get_timeout,
)


# ── get_timeout() unit tests ──────────────────────────────────────────


def test_get_timeout_default_when_env_unset(monkeypatch: object) -> None:
    """No env var → DEFAULT_TIMEOUT (connect=10, read/write/pool=300)."""
    monkeypatch.delenv("ZELOO_LLM_TIMEOUT_SECONDS", raising=False)  # type: ignore[attr-defined]
    timeout = get_timeout()
    assert isinstance(timeout, httpx.Timeout)
    assert timeout == DEFAULT_TIMEOUT
    assert timeout.connect == 10.0
    assert timeout.read == 300.0
    assert timeout.write == 300.0
    assert timeout.pool == 300.0


def test_get_timeout_with_env_override(monkeypatch: object) -> None:
    """``ZELOO_LLM_TIMEOUT_SECONDS=60`` → connect capped, others 300s."""
    monkeypatch.setenv("ZELOO_LLM_TIMEOUT_SECONDS", "60")  # type: ignore[attr-defined]
    timeout = get_timeout()
    assert timeout.connect == 30.0  # min(60, 30)
    assert timeout.read == 300.0  # 60 * 5
    assert timeout.write == 300.0
    assert timeout.pool == 300.0


def test_get_timeout_with_low_env_value(monkeypatch: object) -> None:
    """A short timeout propagates without caps when below 30."""
    monkeypatch.setenv("ZELOO_LLM_TIMEOUT_SECONDS", "5")  # type: ignore[attr-defined]
    timeout = get_timeout()
    assert timeout.connect == 5.0  # min(5, 30) = 5
    assert timeout.read == 25.0  # 5 * 5
    assert timeout.write == 25.0
    assert timeout.pool == 25.0


def test_get_timeout_with_high_env_value(monkeypatch: object) -> None:
    """A high env value caps connect at 30s, scales others ×5."""
    monkeypatch.setenv("ZELOO_LLM_TIMEOUT_SECONDS", "120")  # type: ignore[attr-defined]
    timeout = get_timeout()
    assert timeout.connect == 30.0  # min(120, 30)
    assert timeout.read == 600.0  # 120 * 5
    assert timeout.write == 600.0
    assert timeout.pool == 600.0


def test_get_timeout_invalid_env_falls_back(monkeypatch: object) -> None:
    """Garbage env value silently falls back to DEFAULT_TIMEOUT."""
    monkeypatch.setenv("ZELOO_LLM_TIMEOUT_SECONDS", "not-a-number")  # type: ignore[attr-defined]
    timeout = get_timeout()
    assert timeout == DEFAULT_TIMEOUT


def test_default_timeout_is_bounded() -> None:
    """The hard-coded DEFAULT_TIMEOUT never exceeds 10 minutes."""
    assert DEFAULT_TIMEOUT.connect == 10.0
    assert DEFAULT_TIMEOUT.read == 300.0
    assert DEFAULT_TIMEOUT.write == 300.0
    assert DEFAULT_TIMEOUT.pool == 300.0


def test_default_timeout_s_constant_intact() -> None:
    """Legacy DEFAULT_TIMEOUT_S is still 60.0 (back-compat)."""
    assert DEFAULT_TIMEOUT_S == 60.0


# ── Integration tests: get_timeout() reaches the HTTP client ──────────


def test_async_post_json_uses_bounded_timeout(monkeypatch: object) -> None:
    """``async_post_json`` must reach ``httpx.AsyncClient(timeout=...)``
    with a value derived from ``get_timeout()`` so a hung provider
    cannot block the loop for ten minutes."""
    captured: dict[str, object] = {}

    class _FakeAsyncClient:
        def __init__(self, *, timeout: object) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def post(self, *args: object, **kwargs: object) -> object:
            class _Resp:
                status_code = 200
                text = "{}"
                reason_phrase = "OK"

                def json(self) -> dict[str, object]:
                    return {}

            return _Resp()

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agent.providers._http.httpx.AsyncClient", _FakeAsyncClient
    )

    import asyncio

    async def _run() -> dict[str, object]:
        return await async_post_json("http://localhost/x", json_payload={"a": 1})

    result = asyncio.run(_run())
    assert result["ok"] is True
    # The captured timeout must be a bounded httpx.Timeout instance.
    assert isinstance(captured["timeout"], httpx.Timeout)
    assert captured["timeout"] == DEFAULT_TIMEOUT


def test_async_get_json_uses_bounded_timeout(monkeypatch: object) -> None:
    """Same guarantee for GET helpers."""
    captured: dict[str, object] = {}

    class _FakeAsyncClient:
        def __init__(self, *, timeout: object) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def get(self, *args: object, **kwargs: object) -> object:
            class _Resp:
                status_code = 200
                text = "{}"
                reason_phrase = "OK"

                def json(self) -> dict[str, object]:
                    return {}

            return _Resp()

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agent.providers._http.httpx.AsyncClient", _FakeAsyncClient
    )

    import asyncio

    async def _run() -> dict[str, object]:
        return await async_get_json("http://localhost/x")

    result = asyncio.run(_run())
    assert result["ok"] is True
    assert isinstance(captured["timeout"], httpx.Timeout)
    assert captured["timeout"] == DEFAULT_TIMEOUT


def test_get_timeout_is_callable_repeatedly(monkeypatch: object) -> None:
    """``get_timeout()`` should be safe to call repeatedly with
    consistent results, since provider layers may invoke it per-call."""
    monkeypatch.delenv("ZELOO_LLM_TIMEOUT_SECONDS", raising=False)  # type: ignore[attr-defined]
    first = get_timeout()
    second = get_timeout()
    assert first == second
    assert first == DEFAULT_TIMEOUT


def test_async_post_json_passes_headers_and_payload(monkeypatch: object) -> None:
    """Smoke check that headers/payload are still forwarded correctly
    after the timeout swap."""
    captured: dict[str, object] = {}

    class _FakeAsyncClient:
        def __init__(self, *, timeout: object) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def post(
            self, url: str, *, headers: dict[str, str], json: dict[str, object]
        ) -> object:
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json

            class _Resp:
                status_code = 200
                text = '{"ok":true}'
                reason_phrase = "OK"

                def json(self) -> dict[str, object]:
                    return {"ok": True}

            return _Resp()

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agent.providers._http.httpx.AsyncClient", _FakeAsyncClient
    )

    import asyncio

    async def _run() -> dict[str, object]:
        return await async_post_json(
            "http://localhost/x",
            headers={"X-Test": "yes"},
            json_payload={"q": "hi"},
        )

    result = asyncio.run(_run())
    assert captured["url"] == "http://localhost/x"
    assert captured["headers"] == {"X-Test": "yes"}
    assert captured["json"] == {"q": "hi"}
    assert result["ok"] is True


def test_async_post_json_timeout_returns_error(monkeypatch: object) -> None:
    """A timeout at the httpx layer must surface as ``ok=False, status=0``."""

    class _FakeAsyncClient:
        def __init__(self, *, timeout: object) -> None:
            pass

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def post(self, *args: object, **kwargs: object) -> object:
            raise httpx.TimeoutException("read timed out")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agent.providers._http.httpx.AsyncClient", _FakeAsyncClient
    )

    import asyncio

    async def _run() -> dict[str, object]:
        return await async_post_json("http://localhost/x", json_payload={"a": 1})

    result = asyncio.run(_run())
    assert result["ok"] is False
    assert result["status"] == 0
    assert "timeout" in result["error"]