"""Session management router."""

from __future__ import annotations

import secrets
import time
from typing import Any

from .base import RouteContext, Router, route

_SESSIONS: dict[str, dict[str, Any]] = {}


class SessionsRouter(Router):
    name = "sessions"

    @route("GET", "/sessions")
    def list_sessions(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        user_id = ctx.query.get("user_id")
        sessions = list(_SESSIONS.values())
        if user_id:
            sessions = [s for s in sessions if s.get("user_id") == user_id]
        return ctx.json_response(200, {"sessions": sessions, "count": len(sessions)})

    @route("POST", "/sessions")
    def create_session(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        if not isinstance(ctx.body, dict):
            return ctx.json_response(400, {"error": "invalid_body"})
        workspace = ctx.body.get("workspace", "default")
        model = ctx.body.get("model", "default")
        session_id = secrets.token_urlsafe(16)
        _SESSIONS[session_id] = {
            "id": session_id,
            "user_id": ctx.user_id or "anonymous",
            "workspace": workspace,
            "model": model,
            "created_at": time.time(),
            "status": "active",
            "turn_count": 0,
        }
        return ctx.json_response(201, {"id": session_id, "workspace": workspace, "model": model})

    @route("GET", "/sessions/{id}")
    def get_session(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        target_id = ctx.path.rsplit("/", 1)[-1]
        s = _SESSIONS.get(target_id)
        if s is None:
            return ctx.json_response(404, {"error": "not_found"})
        return ctx.json_response(200, s)

    @route("DELETE", "/sessions/{id}")
    def delete_session(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        target_id = ctx.path.rsplit("/", 1)[-1]
        if target_id in _SESSIONS:
            _SESSIONS[target_id]["status"] = "deleted"
            return ctx.json_response(200, {"ok": True})
        return ctx.json_response(404, {"error": "not_found"})

    @route("POST", "/sessions/{id}/archive")
    def archive_session(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        target_id = ctx.path.rsplit("/", 1)[-1]
        s = _SESSIONS.get(target_id)
        if s is None:
            return ctx.json_response(404, {"error": "not_found"})
        s["status"] = "archived"
        s["archived_at"] = time.time()
        return ctx.json_response(200, {"ok": True})

    @route("POST", "/sessions/{id}/messages")
    def append_message(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        target_id = ctx.path.rsplit("/", 1)[-1]
        s = _SESSIONS.get(target_id)
        if s is None:
            return ctx.json_response(404, {"error": "not_found"})
        if not isinstance(ctx.body, dict):
            return ctx.json_response(400, {"error": "invalid_body"})
        s.setdefault("messages", []).append({
            "role": ctx.body.get("role", "user"),
            "content": ctx.body.get("content", ""),
            "ts": time.time(),
        })
        s["turn_count"] = s.get("turn_count", 0) + 1
        return ctx.json_response(201, {"ok": True, "turn_count": s["turn_count"]})


sessions_router = SessionsRouter()
