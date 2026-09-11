"""Pluggable middleware chain for the HTTP gateway.

Defines the :class:`Middleware` base class along with four concrete
implementations commonly used at the gateway layer:

* :class:`RateLimitMiddleware` — per-IP / per-token sliding-window limiter.
* :class:`AuthMiddleware`      — bearer-token API-key authentication.
* :class:`LoggingMiddleware`   — structured request/response logging.
* :class:`CORSMiddleware`      — CORS header injection.

The :class:`MiddlewareChain` orchestrates them in registration order. Each
middleware is awaited with the ``request`` dict and a ``next_handler``
callable; calling the next handler triggers the remainder of the chain.

NOTE: This is the HTTP gateway middleware (used by ``api_server`` and friends).
It is intentionally separate from ``zeloo_cli/core/middleware.py``, which
operates on the higher-level ``RequestContext`` dataclass used by the CLI
command pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Middleware:
    """Base class for gateway middleware.

    Subclasses override :meth:`__call__` to inspect / mutate ``request``,
    delegate to ``next_handler``, and post-process the response. Returning
    a dict that contains ``{"_blocked": True, ...}`` short-circuits the
    chain (the remaining middlewares are skipped).
    """

    name: str = "middleware"

    async def __call__(self, request: dict, next_handler: Callable) -> dict:
        """Process ``request`` and forward to ``next_handler``.

        Args:
            request: Plain dictionary describing the incoming HTTP call.
                Always contains at least ``"path"``, ``"method"`` and
                ``"headers"`` keys.
            next_handler: Awaitable callable that resumes the chain. Call
                it to invoke subsequent middlewares; omit it to short
                circuit.

        Returns:
            The response dictionary. May include extra meta keys such as
            ``"status"`` or ``"duration_ms"``.
        """
        return await next_handler(request)


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class RateLimitMiddleware(Middleware):
    """Sliding-window rate limiter keyed by client IP or API token."""

    name = "rate_limit"

    def __init__(
        self,
        max_requests: int = 100,
        window_seconds: int = 60,
    ) -> None:
        """Store the limit and start a per-key deque of recent timestamps."""
        if max_requests <= 0:
            raise ValueError("max_requests must be > 0")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self._max = max_requests
        self._window = float(window_seconds)
        self._buckets: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    def _key(self, request: dict) -> str:
        """Pick the rate-limit key from headers, falling back to client IP."""
        headers = request.get("headers", {}) or {}
        token = headers.get("X-API-Key") or headers.get("Authorization", "")
        if isinstance(token, str) and token.startswith("Bearer "):
            token = token[7:].strip()
        if token:
            return f"tok:{token}"
        client = request.get("client") or request.get("remote_addr") or "unknown"
        return f"ip:{client}"

    async def __call__(self, request: dict, next_handler: Callable) -> dict:
        """Reject when ``key`` already exceeded the window, else forward."""
        key = self._key(request)
        now = time.monotonic()
        async with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            cutoff = now - self._window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._max:
                logger.warning("Rate limit exceeded for %s", key)
                return {
                    "status": 429,
                    "body": {"error": {"message": "Rate limit exceeded", "type": "rate_limit_error"}},
                    "_blocked": True,
                }
            bucket.append(now)
        return await next_handler(request)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class AuthMiddleware(Middleware):
    """Bearer-token / API-key authentication gate."""

    name = "auth"

    def __init__(
        self,
        allowed_tokens: list[str] | None = None,
        exempt_paths: list[str] | None = None,
    ) -> None:
        """Configure the allow-list and any path exemptions."""
        self._tokens: set[str] = set(allowed_tokens or [])
        self._exempt: tuple[str, ...] = tuple(exempt_paths or ("/health",))

    def _extract_token(self, headers: dict[str, Any]) -> str:
        """Pull the bearer / API key out of an HTTP header map."""
        token = headers.get("X-API-Key") or headers.get("Authorization", "")
        if isinstance(token, str) and token.startswith("Bearer "):
            return token[7:].strip()
        return token.strip() if isinstance(token, str) else ""

    async def __call__(self, request: dict, next_handler: Callable) -> dict:
        """Reject unauthorised requests unless the path is exempt."""
        if not self._tokens:
            return await next_handler(request)
        path = request.get("path", "/")
        if any(path == p or path.startswith(p.rstrip("/") + "/") for p in self._exempt):
            return await next_handler(request)
        headers = request.get("headers", {}) or {}
        token = self._extract_token(headers)
        if token and token in self._tokens:
            request.setdefault("auth", {})["token"] = token[:8] + "***"
            return await next_handler(request)
        logger.info("Auth rejected for %s", path)
        return {
            "status": 401,
            "body": {"error": {"message": "Unauthorized", "type": "authentication_error"}},
            "_blocked": True,
        }


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class LoggingMiddleware(Middleware):
    """Structured access log for every request/response pair."""

    def __init__(self, log_level: int = logging.INFO) -> None:
        """Pick the log level used for the access log line."""
        self._level = log_level

    async def __call__(self, request: dict, next_handler: Callable) -> dict:
        """Log method/path before, status/duration after."""
        start = time.perf_counter()
        method = request.get("method", "GET")
        path = request.get("path", "/")
        logger.log(self._level, "→ %s %s", method, path)
        try:
            response = await next_handler(request)
        except Exception:
            elapsed = (time.perf_counter() - start) * 1000.0
            logger.exception("✗ %s %s (%.1fms)", method, path, elapsed)
            raise
        elapsed = (time.perf_counter() - start) * 1000.0
        status = response.get("status", 200) if isinstance(response, dict) else 200
        response.setdefault("duration_ms", elapsed)
        logger.log(self._level, "← %s %s %d (%.1fms)", method, path, status, elapsed)
        return response


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


class CORSMiddleware(Middleware):
    """Inject CORS headers into every response."""

    def __init__(
        self,
        allowed_origins: list[str] | None = None,
        allowed_methods: list[str] | None = None,
    ) -> None:
        """Store the allowed origins / HTTP methods."""
        self._origins: tuple[str, ...] = tuple(allowed_origins or ["*"])
        self._methods: str = ", ".join(
            allowed_methods or ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
        )

    def _origin(self) -> str:
        """Return the value for the ``Access-Control-Allow-Origin`` header."""
        return self._origins[0] if len(self._origins) == 1 else ", ".join(self._origins)

    async def __call__(self, request: dict, next_handler: Callable) -> dict:
        """Answer pre-flight ``OPTIONS`` requests directly, else wrap."""
        method = request.get("method", "GET")
        if method == "OPTIONS":
            return {
                "status": 204,
                "headers": {
                    "Access-Control-Allow-Origin": self._origin(),
                    "Access-Control-Allow-Methods": self._methods,
                    "Access-Control-Allow-Headers": "Authorization, Content-Type",
                    "Access-Control-Max-Age": "600",
                },
                "body": "",
            }
        response = await next_handler(request)
        if isinstance(response, dict):
            headers = response.setdefault("headers", {})
            headers.setdefault("Access-Control-Allow-Origin", self._origin())
            headers.setdefault("Access-Control-Allow-Methods", self._methods)
        return response


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------


class MiddlewareChain:
    """Ordered chain of middleware executed left-to-right."""

    def __init__(self, middlewares: list[Middleware] | None = None) -> None:
        """Initialise the chain with an optional starter list."""
        self._middlewares: list[Middleware] = list(middlewares or [])

    def add(self, middleware: Middleware) -> None:
        """Append ``middleware`` to the end of the chain."""
        self._middlewares.append(middleware)

    def remove(self, name: str) -> bool:
        """Remove the first middleware whose ``name`` matches. Returns success flag."""
        for idx, mw in enumerate(self._middlewares):
            if getattr(mw, "name", None) == name:
                del self._middlewares[idx]
                return True
        return False

    def __len__(self) -> int:
        """Return the current middleware count."""
        return len(self._middlewares)

    async def execute(self, request: dict, handler: Callable) -> dict:
        """Run the chain. ``handler`` is invoked last if no middleware blocks."""
        async def _dispatch(idx: int, req: dict) -> dict:
            if idx >= len(self._middlewares):
                return await handler(req)
            return await self._middlewares[idx](req, lambda r: _dispatch(idx + 1, r))

        return await _dispatch(0, request)