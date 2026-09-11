"""User management router."""

from __future__ import annotations

import secrets
import time
from typing import Any

from .base import RouteContext, Router, route

_USERS: dict[str, dict[str, Any]] = {}


def _hash_password(p: str) -> str:
    import hashlib
    return hashlib.sha256(p.encode()).hexdigest()


class UsersRouter(Router):
    name = "users"

    @route("GET", "/users")
    def list_users(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        return ctx.json_response(200, {"users": list(_USERS.values()), "count": len(_USERS)})

    @route("POST", "/users")
    def create_user(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        if not isinstance(ctx.body, dict):
            return ctx.json_response(400, {"error": "invalid_body"})
        username = ctx.body.get("username", "")
        password = ctx.body.get("password", "")
        email = ctx.body.get("email", "")
        if not username or not password:
            return ctx.json_response(400, {"error": "missing_fields"})
        if username in _USERS:
            return ctx.json_response(409, {"error": "user_exists"})

        user_id = secrets.token_urlsafe(8)
        _USERS[username] = {
            "id": user_id,
            "username": username,
            "email": email,
            "password_hash": _hash_password(password),
            "role": ctx.body.get("role", "user"),
            "created_at": time.time(),
        }
        return ctx.json_response(201, {"id": user_id, "username": username})

    @route("GET", "/users/{id}")
    def get_user(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        for u in _USERS.values():
            if u["id"] == ctx.path.rsplit("/", 1)[-1]:
                return ctx.json_response(200, u)
        return ctx.json_response(404, {"error": "not_found"})

    @route("PATCH", "/users/{id}")
    def update_user(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        target_id = ctx.path.rsplit("/", 1)[-1]
        for u in _USERS.values():
            if u["id"] == target_id:
                if isinstance(ctx.body, dict):
                    if "email" in ctx.body:
                        u["email"] = ctx.body["email"]
                    if "role" in ctx.body:
                        u["role"] = ctx.body["role"]
                return ctx.json_response(200, {"ok": True})
        return ctx.json_response(404, {"error": "not_found"})

    @route("DELETE", "/users/{id}")
    def delete_user(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        target_id = ctx.path.rsplit("/", 1)[-1]
        for username, u in list(_USERS.items()):
            if u["id"] == target_id:
                del _USERS[username]
                return ctx.json_response(200, {"ok": True})
        return ctx.json_response(404, {"error": "not_found"})


users_router = UsersRouter()
