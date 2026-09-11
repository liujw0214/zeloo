"""Feishu / Lark platform integration.

Implements :class:`BaseIntegration` against the Feishu Open API
(``https://open.feishu.cn/open-apis/...``). Supports both Feishu
(``open.feishu.cn``) and Lark (``open.larksuite.com``) endpoints.

Features
--------
- Tenant Access Token (auto-issued and cached) **or** User Access Token
- Sending text / rich-text / interactive card messages
- @mention users (``<at user_id="...">name</at>``) and ``@all``
- File/image uploads via ``im/v1/images`` / ``im/v1/files``
- Rate-limit handling on HTTP 429 with ``Retry-After``

Configuration keys
------------------
- ``app_id`` (str, required for tenant token)
- ``app_secret`` (str, required for tenant token)
- ``tenant_access_token`` (str, optional): pre-issued token
- ``user_access_token`` (str, optional): use a user token instead of
  the tenant token
- ``api_base`` (str, optional): ``https://open.feishu.cn/open-apis``
- ``lark`` (bool, optional): Use ``open.larksuite.com`` instead.
- ``max_retries`` (int, optional): Defaults to ``3``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from tools.integrations.base import (
    AuthError,
    BaseIntegration,
    IntegrationError,
    NotFoundError,
    RateLimitError,
    ReceiveCallback,
    require_config,
    safe_call,
    sleep_for,
)
from tools.integrations.registry import register_integration

logger = logging.getLogger(__name__)

DEFAULT_FEISHU_API = "https://open.feishu.cn/open-apis"
DEFAULT_LARK_API = "https://open.larksuite.com/open-apis"
DEFAULT_MAX_RETRIES = 3
TOKEN_EXPIRY_BUFFER_SECONDS = 60


@register_integration("feishu")
class FeishuIntegration(BaseIntegration):
    """Feishu / Lark integration."""

    platform_name = "feishu"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)

        is_lark = bool(config.get("lark", False))
        self.api_base: str = (
            config.get("api_base")
            or (DEFAULT_LARK_API if is_lark else DEFAULT_FEISHU_API)
        ).rstrip("/")
        self.max_retries: int = int(config.get("max_retries", DEFAULT_MAX_RETRIES))
        self.timeout: float = float(config.get("timeout", 30.0))

        self._app_id: str | None = config.get("app_id")
        self._app_secret: str | None = config.get("app_secret")
        self._tenant_token_override: str | None = config.get("tenant_access_token")
        self._tenant_token_expiry: float = 0.0
        self._user_token: str | None = config.get("user_access_token")
        self._token_lock = asyncio.Lock()

        self._client: httpx.AsyncClient | None = None
        self._webhook_task: asyncio.Task[None] | None = None

        if not self._user_token and not self._tenant_token_override:
            # We can defer app_secret validation until first call.
            if not (self._app_id and self._app_secret):
                # Allow lazy authentication; surface warning only.
                logger.debug(
                    "FeishuIntegration configured without credentials; "
                    "tenant token will be requested lazily."
                )

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.api_base,
                timeout=self.timeout,
                headers={"User-Agent": "ZelooFeishuIntegration/1.0"},
            )
        return self._client

    async def close(self) -> None:
        await super().close()
        if self._webhook_task is not None and not self._webhook_task.done():
            self._webhook_task.cancel()
            try:
                await self._webhook_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _ensure_tenant_token(self) -> str:
        """Return a valid Tenant Access Token, refreshing if necessary."""
        if self._user_token:
            return self._user_token
        if self._tenant_token_override:
            return self._tenant_token_override
        async with self._token_lock:
            now = time.time()
            if (
                self._tenant_token_override
                and now < self._tenant_token_expiry - TOKEN_EXPIRY_BUFFER_SECONDS
            ):
                return self._tenant_token_override

            app_id = require_config(self.config, "app_id")
            app_secret = require_config(self.config, "app_secret")
            client = await self._get_client()
            try:
                response = await client.post(
                    "/auth/v3/tenant_access_token/internal",
                    json={
                        "app_id": app_id,
                        "app_secret": app_secret,
                    },
                )
            except httpx.HTTPError as exc:
                raise IntegrationError(f"Feishu auth HTTP error: {exc}") from exc

            if response.status_code >= 400:
                raise AuthError(
                    f"Feishu tenant token request failed: {response.text}"
                )
            payload = response.json()
            if payload.get("code") != 0:
                raise AuthError(
                    f"Feishu auth error: {payload.get('msg')} "
                    f"({payload.get('code')})"
                )
            self._tenant_token_override = payload.get("tenant_access_token", "")
            self._tenant_token_expiry = now + int(payload.get("expire", 7200))
            if not self._tenant_token_override:
                raise AuthError("Feishu auth returned empty token")
            return self._tenant_token_override

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        multipart: dict[str, Any] | None = None,
        auth: str = "tenant",
    ) -> dict[str, Any]:
        client = await self._get_client()
        attempts = self.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            token = await self._ensure_tenant_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            }

            try:
                if multipart is not None:
                    response = await client.request(
                        method,
                        path,
                        params=params,
                        files=multipart.get("files"),
                        data=multipart.get("data"),
                        headers={"Authorization": headers["Authorization"]},
                    )
                else:
                    response = await client.request(
                        method,
                        path,
                        params=params,
                        json=json_body,
                        headers=headers,
                    )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "Feishu HTTP transport error on %s (attempt %s/%s): %s",
                    path,
                    attempt,
                    attempts,
                    exc,
                )
                await sleep_for(min(2 ** attempt, 10))
                continue

            # Feishu uses HTTP 429 + ``Retry-After``.
            if response.status_code == 429:
                retry_after_raw = response.headers.get("Retry-After", "1")
                try:
                    retry_after = float(retry_after_raw)
                except ValueError:
                    retry_after = 1.0
                logger.info(
                    "Feishu rate-limited (%s), sleeping %.2fs", path, retry_after
                )
                await sleep_for(retry_after)
                if attempt < attempts:
                    continue
                raise RateLimitError(
                    f"Feishu rate limit exceeded for {path}", retry_after=retry_after
                )

            if response.status_code in (401, 403):
                # Force token refresh on next loop.
                self._tenant_token_override = None
                self._tenant_token_expiry = 0.0
                if attempt < attempts:
                    continue
                raise AuthError(
                    f"Feishu auth failure ({response.status_code}): {response.text}"
                )
            if response.status_code == 404:
                raise NotFoundError(f"Feishu resource missing: {path}")
            if 500 <= response.status_code < 600:
                last_error = IntegrationError(
                    f"Feishu server error {response.status_code}: {response.text}"
                )
                logger.warning(
                    "Feishu server error %s on %s (attempt %s/%s)",
                    response.status_code,
                    path,
                    attempt,
                    attempts,
                )
                await sleep_for(min(2 ** attempt, 10))
                continue

            try:
                payload = response.json()
            except Exception as exc:  # noqa: BLE001
                raise IntegrationError(f"Invalid Feishu response: {exc}") from exc

            code = payload.get("code", -1) if isinstance(payload, dict) else -1
            if code != 0:
                msg = payload.get("msg") if isinstance(payload, dict) else "unknown"
                err_detail = payload.get("error", {}) if isinstance(payload, dict) else {}
                # ``99991663`` / ``99991664`` indicate token issues.
                if code in (99991663, 99991664, 99991668):
                    self._tenant_token_override = None
                    self._tenant_token_expiry = 0.0
                    if attempt < attempts:
                        continue
                    raise AuthError(f"Feishu auth error: {msg}")
                if code in (230020, 230021, 230002):
                    raise NotFoundError(f"Feishu resource error: {msg}")
                raise IntegrationError(f"Feishu API error: {msg} (code={code})")

            return payload.get("data") if isinstance(payload, dict) else {}

        assert last_error is not None
        raise IntegrationError(f"Feishu request failed after retries: {last_error}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def send_message(
        self,
        channel: str,
        content: str,
        *,
        msg_type: str = "text",
        rich_text_blocks: list[dict[str, Any]] | None = None,
        card: dict[str, Any] | None = None,
        mentions: list[dict[str, str]] | None = None,
        receive_id_type: str = "chat_id",
        **_: Any,
    ) -> dict[str, Any]:
        """Send a message via ``im/v1/messages``.

        Parameters
        ----------
        channel:
            ``receive_id`` (chat id, open id, union id, email or
            user id depending on ``receive_id_type``).
        content:
            Text body. When ``msg_type`` is ``"rich_text"`` or
            ``"interactive"``, ``content`` is JSON-encoded as the
            payload body. Provide ``card`` to send an interactive
            card directly without re-encoding.
        mentions:
            List of ``{"id_type": "...", "id": "..."}`` entries that
            Feishu should mention. ``"@all"`` triggers an ``@all``.
        """

        async def _do() -> dict[str, Any]:
            payload_body: dict[str, Any] = {"receive_id": channel}
            if msg_type == "interactive" and card is not None:
                payload_body["msg_type"] = "interactive"
                payload_body["content"] = json.dumps(card, ensure_ascii=False)
            elif msg_type == "rich_text":
                payload_body["msg_type"] = "rich_text"
                payload_body["content"] = json.dumps(
                    rich_text_blocks
                    if rich_text_blocks is not None
                    else [{"tag": "text", "text": content}],
                    ensure_ascii=False,
                )
            else:
                payload_body["msg_type"] = "text"
                payload_body["content"] = json.dumps(
                    {"text": content}, ensure_ascii=False
                )

            if mentions:
                at_tag = _build_at_tag(mentions)
                if at_tag:
                    # Merge into content where possible.
                    try:
                        content_obj = json.loads(payload_body["content"])
                    except (TypeError, ValueError):
                        content_obj = {"text": content}
                    if isinstance(content_obj, dict) and "text" in content_obj:
                        content_obj["text"] = (
                            f"{at_tag} " + content_obj["text"]
                        ).strip()
                        payload_body["content"] = json.dumps(
                            content_obj, ensure_ascii=False
                        )

            result = await self._request(
                "POST",
                f"/im/v1/messages?receive_id_type={receive_id_type}",
                json_body=payload_body,
            )
            return {
                "ok": True,
                "message_id": result.get("message_id"),
                "chat_id": result.get("chat_id"),
                "create_time": result.get("create_time"),
                "raw": result,
            }

        return await safe_call(_do)

    async def list_channels(self) -> list[dict[str, Any]]:
        """List chats via ``im/v1/chats`` (paginated)."""

        async def _do() -> list[dict[str, Any]]:
            chats: list[dict[str, Any]] = []
            page_token: str | None = None
            while True:
                params: dict[str, Any] = {"page_size": 100}
                if page_token:
                    params["page_token"] = page_token
                result = await self._request("GET", "/im/v1/chats", params=params)
                chats.extend(result.get("items", []) if isinstance(result, dict) else [])
                if not isinstance(result, dict) or not result.get("has_more"):
                    break
                page_token = result.get("page_token")
                if not page_token:
                    break
            return chats

        result = await safe_call(_do)
        return result if isinstance(result, list) else []

    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Return contact info via ``contact/v3/users/{user_id}``."""

        async def _do() -> dict[str, Any]:
            user_id_type = self.config.get("user_id_type", "open_id")
            result = await self._request(
                "GET",
                f"/contact/v3/users/{user_id}",
                params={"user_id_type": user_id_type},
            )
            return result.get("user") if isinstance(result, dict) else result

        return await safe_call(_do) or {"ok": False, "error": "unknown"}

    # ------------------------------------------------------------------
    # File / image upload helpers
    # ------------------------------------------------------------------
    async def upload_image(
        self,
        file_path: str,
        *,
        image_type: str = "message",
    ) -> dict[str, Any]:
        """Upload an image via ``im/v1/images`` (multipart)."""

        async def _do() -> dict[str, Any]:
            import os

            with open(file_path, "rb") as fh:
                files = {"image": (os.path.basename(file_path), fh)}
                data = {"image_type": image_type}
                result = await self._request(
                    "POST",
                    "/im/v1/images",
                    multipart={"data": data, "files": files},
                )
            return result

        return await safe_call(_do) or {"ok": False, "error": "unknown"}

    async def upload_file(
        self,
        file_path: str,
        *,
        file_type: str = "stream",
    ) -> dict[str, Any]:
        """Upload a generic file via ``im/v1/files``."""

        async def _do() -> dict[str, Any]:
            import os

            with open(file_path, "rb") as fh:
                files = {"file": (os.path.basename(file_path), fh)}
                data = {"file_type": file_type}
                result = await self._request(
                    "POST",
                    "/im/v1/files",
                    multipart={"data": data, "files": files},
                )
            return result

        return await safe_call(_do) or {"ok": False, "error": "unknown"}

    # ------------------------------------------------------------------
    # Receive loop
    # ------------------------------------------------------------------
    async def receive_messages(
        self,
        callback: ReceiveCallback,
        *,
        event_subscription: dict[str, Any] | None = None,
        **_: Any,
    ) -> None:
        """Register the event-callback for incoming webhook deliveries.

        Feishu events are normally delivered to a webhook URL hosted by
        the application. This method does **not** open a long-lived
        connection — instead it stores ``callback`` so the host
        application can call :meth:`handle_event` for each request.
        """
        # Stash the callback on the instance for the host to invoke.
        self._event_callback = callback
        if event_subscription:
            logger.info(
                "Feishu receive_messages() called with event_subscription=%s",
                list(event_subscription.keys()),
            )

    async def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a single inbound Feishu webhook event.

        Feishu's webhook protocol includes an encrypted payload; the
        host should decrypt and shape it into the standard envelope
        ``{"type": ..., "event": {...}}`` before calling this method.
        """
        callback = getattr(self, "_event_callback", None)
        if callback is not None:
            try:
                await callback(event)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Feishu event callback raised: %s", exc)
        return {"ok": True, "type": event.get("type", "event")}


def _build_at_tag(mentions: list[dict[str, str]]) -> str:
    """Compose a Feishu ``@`` tag from a list of mention dicts."""
    parts: list[str] = []
    for mention in mentions:
        mid = mention.get("id")
        mtype = mention.get("id_type", "open_id")
        if mid == "@all":
            parts.append("<at user_id=\"all\">@所有人</at>")
        elif mid:
            parts.append(f"<at user_id=\"{mid}\"></at>")
    return " ".join(parts)


_ = Callable  # placate linters when unused