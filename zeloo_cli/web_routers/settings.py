"""Settings router for user/system configuration."""

from __future__ import annotations

import time
from typing import Any

from .base import RouteContext, Router, route

_SETTINGS: dict[str, dict[str, Any]] = {}


class SettingsRouter(Router):
    name = "settings"

    @route("GET", "/settings")
    def get_settings(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        user_id = ctx.user_id or "default"
        return ctx.json_response(200, _SETTINGS.get(user_id, {
            "user_id": user_id,
            "theme": "light",
            "locale": "en",
            "timezone": "UTC",
            "model_preferences": {"default": "gpt-4o"},
        }))

    @route("PUT", "/settings")
    def update_settings(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        if not isinstance(ctx.body, dict):
            return ctx.json_response(400, {"error": "invalid_body"})
        user_id = ctx.user_id or "default"
        existing = _SETTINGS.setdefault(user_id, {"user_id": user_id})
        for key in ("theme", "locale", "timezone", "model_preferences"):
            if key in ctx.body:
                existing[key] = ctx.body[key]
        existing["updated_at"] = time.time()
        return ctx.json_response(200, {"ok": True})

    @route("GET", "/settings/system")
    def get_system_settings(self, ctx: RouteContext) -> tuple[int, dict[str, str], bytes]:
        return ctx.json_response(200, {
            "version": "0.21.0",
            "build": "dev",
            "features": {
                "voice": True,
                "browser": True,
                "image_gen": True,
                "video_gen": True,
                "web_search": True,
                "optional_skills": True,
                "optional_mcps": True,
            },
            "limits": {
                "max_sessions": 100,
                "max_tokens_per_day": 100000,
                "max_storage_gb": 10,
            },
        })


settings_router = SettingsRouter()
