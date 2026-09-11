"""Middleware pipeline — request/response interceptors."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class RequestContext:
    """Context for an incoming request."""

    method: str = "GET"
    path: str = "/"
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    query_params: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)


@dataclass
class ResponseContext:
    """Context for an outgoing response."""

    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


class Middleware(ABC):
    """Base class for middleware."""

    @abstractmethod
    def process_request(self, context: RequestContext) -> RequestContext | None:
        """Process incoming request. Return None to short-circuit."""

    @abstractmethod
    def process_response(
        self, context: RequestContext, response: ResponseContext
    ) -> ResponseContext:
        """Process outgoing response."""


class MiddlewareChain:
    """Chain of middleware executed in order."""

    def __init__(self) -> None:
        self._middlewares: list[Middleware] = []

    def add(self, middleware: Middleware) -> None:
        self._middlewares.append(middleware)

    def execute(
        self, context: RequestContext, handler: Callable[[RequestContext], Any]
    ) -> tuple[RequestContext, ResponseContext]:
        """Execute the middleware chain.

        Returns: (final_request_context, response_context)
        """
        ctx = context
        for mw in self._middlewares:
            result = mw.process_request(ctx)
            if result is None:
                response = ResponseContext(
                    status_code=403,
                    body={"error": "Request blocked by middleware"},
                )
                return ctx, response
            ctx = result

        duration_start = time.time()
        try:
            body = handler(ctx)
            status = 200
        except Exception as e:
            body = {"error": str(e)}
            status = 500
            logger.exception("Handler error: %s", e)
        duration_ms = (time.time() - duration_start) * 1000

        response = ResponseContext(
            status_code=status,
            body=body,
            duration_ms=duration_ms,
        )

        for mw in reversed(self._middlewares):
            response = mw.process_response(ctx, response)

        ctx.metadata["duration_ms"] = duration_ms
        return ctx, response


class LoggingMiddleware(Middleware):
    """Logs all requests."""

    def process_request(self, context: RequestContext) -> RequestContext:
        logger.info("%s %s", context.method, context.path)
        return context

    def process_response(
        self, context: RequestContext, response: ResponseContext
    ) -> ResponseContext:
        logger.info(
            "%s %s → %d (%.1fms)",
            context.method, context.path, response.status_code, response.duration_ms,
        )
        return response


class AuthMiddleware(Middleware):
    """Simple bearer token auth middleware."""

    def __init__(self, required_token: str = "") -> None:
        self.required_token = required_token

    def process_request(self, context: RequestContext) -> RequestContext | None:
        if not self.required_token:
            return context
        auth = context.headers.get("Authorization", "")
        if auth != f"Bearer {self.required_token}":
            return None
        return context

    def process_response(
        self, context: RequestContext, response: ResponseContext
    ) -> ResponseContext:
        response.headers["X-Powered-By"] = "Zeloo"
        return response


class TimingMiddleware(Middleware):
    """Adds timing metadata to responses."""

    def process_request(self, context: RequestContext) -> RequestContext:
        context.started_at = time.time()
        return context

    def process_response(
        self, context: RequestContext, response: ResponseContext
    ) -> ResponseContext:
        response.duration_ms = (time.time() - context.started_at) * 1000
        response.headers["X-Response-Time"] = f"{response.duration_ms:.1f}ms"
        return response


__all__ = [
    "Middleware",
    "MiddlewareChain",
    "RequestContext",
    "ResponseContext",
    "LoggingMiddleware",
    "AuthMiddleware",
    "TimingMiddleware",
]