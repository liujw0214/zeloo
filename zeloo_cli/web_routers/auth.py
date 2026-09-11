"""Authentication router (login, logout, token refresh)."""

from __future__ import annotations

import logging
import secrets
import time

from .base import RouteContext, Router, route

logger = logging.getLogger(__name__)

_TOKENS: dict[str, dict[str, str | float]] = {}
_TOKENS_TTL = 86400  # 24h


class AuthRouter(Router):
    name = "auth"

    @route("POST", "/auth/login")
    def login(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        if not isinstance(ctx.body, dict):
            return ctx.json_response(400, {"error": "invalid_body"})
        username = ctx.body.get("username", "")
        password = ctx.body.get("password", "")
        if not username or not password:
            return ctx.json_response(400, {"error": "missing_credentials"})

        token = secrets.token_urlsafe(32)
        _TOKENS[token] = {
            "user_id": username,
            "created_at": time.time(),
            "expires_at": time.time() + _TOKENS_TTL,
        }
        return ctx.json_response(200, {"token": token, "expires_in": _TOKENS_TTL})

    @route("POST", "/auth/logout")
    def logout(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        token = ctx.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        _TOKENS.pop(token, None)
        return ctx.json_response(200, {"ok": True})

    @route("POST", "/auth/refresh")
    def refresh(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        token = ctx.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        info = _TOKENS.get(token)
        if info is None:
            return ctx.json_response(401, {"error": "invalid_token"})
        new_token = secrets.token_urlsafe(32)
        _TOKENS[new_token] = {
            "user_id": info["user_id"],
            "created_at": time.time(),
            "expires_at": time.time() + _TOKENS_TTL,
        }
        _TOKENS.pop(token, None)
        return ctx.json_response(200, {"token": new_token, "expires_in": _TOKENS_TTL})

    @route("GET", "/auth/me")
    def me(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        token = ctx.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        info = _TOKENS.get(token)
        if info is None or time.time() > info["expires_at"]:
            return ctx.json_response(401, {"error": "unauthorized"})
        return ctx.json_response(200, {"user_id": info["user_id"]})


auth_router = AuthRouter()
