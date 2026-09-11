"""Base router classes and helpers."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RouteContext:
    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    user_id: str | None = None

    def json_response(  # noqa: E501
        self, status: int = 200, data: Any = None
    ) -> tuple[int, dict[str, str], bytes]:
        body_bytes = json.dumps(data if data is not None else {}).encode("utf-8")
        return (
            status,
            {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(body_bytes))},  # noqa: E501
            body_bytes,
        )


def route(method: str, path: str) -> Callable:
    """Decorator to register a handler method on a router."""
    def decorator(fn: Callable) -> Callable:
        fn._route_method = method.upper()
        fn._route_path = path
        return fn
    return decorator


class Router:
    """Base router class.

    Subclasses should define handler methods decorated with @route().
    """

    name: str = "base"

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], Callable] = {}

    def register(self, app: Any) -> None:
        """Walk through class methods and attach to the app."""
        for attr_name in dir(self):
            attr = getattr(self, attr_name, None)
            if attr is None:
                continue
            method = getattr(attr, "_route_method", None)
            path = getattr(attr, "_route_path", None)
            if method and path:
                self._routes[(method, path)] = attr
                if hasattr(app, "route"):
                    app.route(method, path)(attr)
                logger.debug("Registered %s %s on %s", method, path, self.name)

    def handle(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes] | None:
        handler = self._routes.get((ctx.method, ctx.path))
        if handler is None:
            return None
        return handler(ctx)
