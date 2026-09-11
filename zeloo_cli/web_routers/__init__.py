"""Web routers package for Zeloo CLI dashboard.

Provides HTTP route handlers for user management, sessions, and settings.
Built on top of standard library http.server for zero external dependencies.
"""

from __future__ import annotations

from .auth import AuthRouter, auth_router
from .base import RouteContext, Router, route
from .sessions import SessionsRouter, sessions_router
from .settings import SettingsRouter, settings_router
from .users import UsersRouter, users_router

__all__ = [
    "Router",
    "RouteContext",
    "route",
    "UsersRouter",
    "users_router",
    "SessionsRouter",
    "sessions_router",
    "SettingsRouter",
    "settings_router",
    "AuthRouter",
    "auth_router",
    "register_all",
]


def register_all(app) -> None:
    """Register all routers on a given app (any object with .router attribute)."""
    for r in (auth_router, users_router, sessions_router, settings_router):
        r.register(app)
