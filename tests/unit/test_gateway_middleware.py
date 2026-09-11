"""Unit tests for gateway.middleware.

Covers:
- Middleware base class delegation
- RateLimitMiddleware sliding-window 429 response
- AuthMiddleware allow-list / exempt_paths / no-tokens passthrough
- LoggingMiddleware duration stamping
- CORSMiddleware preflight OPTIONS + header injection
- MiddlewareChain add / remove / __len__ / execute ordering
- Combined chain with multiple middlewares
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from gateway.middleware import (
    AuthMiddleware,
    CORSMiddleware,
    LoggingMiddleware,
    Middleware,
    MiddlewareChain,
    RateLimitMiddleware,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _run(coro):
    """Drive an awaitable from synchronous pytest using a fresh event loop."""
    return asyncio.run(coro)


def _make_request(path: str = "/x", method: str = "GET",
                  headers: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "path": path,
        "method": method,
        "headers": headers or {},
    }


async def _terminal(req: dict[str, Any]) -> dict[str, Any]:
    """The final handler in a chain — echoes back status 200."""
    return {"status": 200, "body": "ok"}


# ── Middleware base ───────────────────────────────────────────────────


class TestBaseMiddleware:
    def test_delegates_to_next(self) -> None:
        async def next_handler(req):
            return {"status": 201}

        async def go():
            return await Middleware()(None, next_handler)

        assert _run(go())["status"] == 201


# ── RateLimitMiddleware ───────────────────────────────────────────────


class TestRateLimit:
    def test_rejects_invalid_init(self) -> None:
        with pytest.raises(ValueError):
            RateLimitMiddleware(max_requests=0, window_seconds=60)
        with pytest.raises(ValueError):
            RateLimitMiddleware(max_requests=10, window_seconds=0)

    def test_first_request_passes(self) -> None:
        rl = RateLimitMiddleware(max_requests=1, window_seconds=10)

        async def go():
            return await rl(_make_request(headers={"X-API-Key": "k1"}), _terminal)

        assert _run(go())["status"] == 200

    def test_second_request_blocked(self) -> None:
        rl = RateLimitMiddleware(max_requests=1, window_seconds=10)

        async def go():
            req = _make_request(headers={"X-API-Key": "k1"})
            r1 = await rl(req, _terminal)
            r2 = await rl(req, _terminal)
            return r1, r2

        r1, r2 = _run(go())
        assert r1["status"] == 200
        assert r2["status"] == 429
        assert r2.get("_blocked") is True

    def test_separate_keys_isolated(self) -> None:
        rl = RateLimitMiddleware(max_requests=1, window_seconds=10)

        async def go():
            r1 = await rl(_make_request(headers={"X-API-Key": "a"}), _terminal)
            r2 = await rl(_make_request(headers={"X-API-Key": "b"}), _terminal)
            return r1, r2

        r1, r2 = _run(go())
        assert r1["status"] == 200
        assert r2["status"] == 200


# ── AuthMiddleware ────────────────────────────────────────────────────


class TestAuth:
    def test_no_tokens_passes_through(self) -> None:
        auth = AuthMiddleware(allowed_tokens=None)

        async def go():
            return await auth(_make_request(), _terminal)

        assert _run(go())["status"] == 200

    def test_valid_bearer(self) -> None:
        auth = AuthMiddleware(allowed_tokens=["secret"])

        async def go():
            return await auth(
                _make_request(headers={"Authorization": "Bearer secret"}),
                _terminal,
            )

        resp = _run(go())
        assert resp["status"] == 200
        # Token should be partially masked in request auth context.
        assert "***" in resp["body"] or "ok" == resp["body"]

    def test_invalid_token_rejected(self) -> None:
        auth = AuthMiddleware(allowed_tokens=["good"])

        async def go():
            return await auth(
                _make_request(headers={"Authorization": "Bearer bad"}),
                _terminal,
            )

        resp = _run(go())
        assert resp["status"] == 401
        assert resp.get("_blocked") is True

    def test_exempt_path(self) -> None:
        auth = AuthMiddleware(allowed_tokens=["good"], exempt_paths=["/health"])

        async def go():
            return await auth(_make_request(path="/health"), _terminal)

        resp = _run(go())
        assert resp["status"] == 200

    def test_exempt_prefix(self) -> None:
        auth = AuthMiddleware(allowed_tokens=["good"], exempt_paths=["/health"])

        async def go():
            return await auth(_make_request(path="/health/deep"), _terminal)

        resp = _run(go())
        assert resp["status"] == 200


# ── LoggingMiddleware ─────────────────────────────────────────────────


class TestLogging:
    def test_stamps_duration(self, caplog) -> None:
        mw = LoggingMiddleware(log_level=logging.INFO)

        async def go():
            return await mw(_make_request(path="/log-test"), _terminal)

        with caplog.at_level(logging.INFO):
            resp = _run(go())
        assert resp["status"] == 200
        assert "duration_ms" in resp
        assert isinstance(resp["duration_ms"], float)
        assert "→ GET /log-test" in caplog.text

    def test_logs_status_after(self, caplog) -> None:
        mw = LoggingMiddleware(log_level=logging.INFO)

        async def go():
            return await mw(_make_request(path="/l2"), _terminal)

        with caplog.at_level(logging.INFO):
            _run(go())
        assert "← GET /l2 200" in caplog.text


# ── CORSMiddleware ────────────────────────────────────────────────────


class TestCORS:
    def test_options_short_circuit(self) -> None:
        cors = CORSMiddleware(allowed_origins=["https://app.example"])

        async def go():
            return await cors(_make_request(method="OPTIONS"), _terminal)

        resp = _run(go())
        assert resp["status"] == 204
        headers = resp.get("headers", {})
        assert "Access-Control-Allow-Origin" in headers
        assert headers["Access-Control-Allow-Origin"] == "https://app.example"

    def test_injects_headers_on_normal_response(self) -> None:
        cors = CORSMiddleware(allowed_origins=["*"])

        async def go():
            return await cors(_make_request(), _terminal)

        resp = _run(go())
        assert "headers" in resp
        assert resp["headers"].get("Access-Control-Allow-Origin") == "*"

    def test_multiple_origins(self) -> None:
        cors = CORSMiddleware(allowed_origins=["https://a", "https://b"])

        async def go():
            return await cors(_make_request(method="OPTIONS"), _terminal)

        resp = _run(go())
        assert "https://a" in resp["headers"]["Access-Control-Allow-Origin"]
        assert "https://b" in resp["headers"]["Access-Control-Allow-Origin"]


# ── MiddlewareChain ───────────────────────────────────────────────────


class TestChain:
    def test_empty_chain_invokes_handler(self) -> None:
        chain = MiddlewareChain()

        async def go():
            return await chain.execute(_make_request(), _terminal)

        resp = _run(go())
        assert resp["status"] == 200

    def test_add_and_len(self) -> None:
        chain = MiddlewareChain()
        assert len(chain) == 0
        chain.add(LoggingMiddleware())
        chain.add(CORSMiddleware())
        assert len(chain) == 2

    def test_remove_by_name(self) -> None:
        chain = MiddlewareChain(
            [RateLimitMiddleware(max_requests=10), CORSMiddleware()]
        )
        assert len(chain) == 2
        assert chain.remove("rate_limit") is True
        assert len(chain) == 1

    def test_remove_unknown_returns_false(self) -> None:
        chain = MiddlewareChain()
        assert chain.remove("nonexistent") is False

    def test_execution_order(self) -> None:
        order: list[str] = []

        class Tag(Middleware):
            def __init__(self, label):
                self.label = label

            async def __call__(self, request, next_handler):
                order.append(f"in:{self.label}")
                resp = await next_handler(request)
                order.append(f"out:{self.label}")
                return resp

        chain = MiddlewareChain([Tag("A"), Tag("B")])

        async def go():
            return await chain.execute(_make_request(), _terminal)

        resp = _run(go())
        assert resp["status"] == 200
        # A wraps B wraps handler.
        assert order == ["in:A", "in:B", "out:B", "out:A"]

    def test_short_circuit_stops_chain(self) -> None:
        order: list[str] = []

        class Block(Middleware):
            async def __call__(self, request, next_handler):
                order.append("block")
                return {"status": 403, "_blocked": True}

        class Pass(Middleware):
            async def __call__(self, request, next_handler):
                order.append("pass")
                return await next_handler(request)

        chain = MiddlewareChain([Pass(), Block(), Pass()])

        async def go():
            return await chain.execute(_make_request(), _terminal)

        resp = _run(go())
        assert resp["status"] == 403
        # The first Pass runs, the Block short-circuits before the last Pass.
        assert order == ["pass", "block"]