"""WhatsApp Business API integration.

Supports WhatsApp Cloud API (Meta) for sending/receiving messages.

Configuration keys:
- phone_number_id (str, required): WhatsApp Business Phone Number ID
- access_token (str, required): Meta App Access Token
- verify_token (str, optional): Webhook verification token
- api_version (str, optional): Graph API version, defaults to "v18.0"
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from typing import Any

import httpx

from tools.integrations.base import (
    AuthError,
    BaseIntegration,
    IntegrationError,
    NotFoundError,
    RateLimitError,
    ReceiveCallback,
    safe_call,
    sleep_for,
)
from tools.integrations.registry import register_integration

logger = logging.getLogger(__name__)

DEFAULT_API_VERSION = "v18.0"
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3


@register_integration("whatsapp")
class WhatsAppIntegration(BaseIntegration):
    """WhatsApp Business API client using Meta Graph API."""

    platform_name = "whatsapp"
    BASE_URL = "https://graph.facebook.com"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.phone_number_id: str = self._require_config("phone_number_id")
        self.access_token: str = self._require_config("access_token")
        self.verify_token: str = config.get("verify_token", "")
        self.api_version: str = config.get("api_version", DEFAULT_API_VERSION)
        self.timeout: float = float(config.get("timeout", DEFAULT_TIMEOUT))
        self._client: httpx.AsyncClient | None = None
        self._event_callback: ReceiveCallback | None = None

    def _require_config(self, key: str) -> str:
        value = self.config.get(key)
        if not value:
            raise AuthError(f"Missing required config key: {key}")
        return str(value)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=f"{self.BASE_URL}/{self.api_version}",
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self) -> None:
        await super().close()
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = await self._get_client()
        attempts = MAX_RETRIES + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await client.request(
                    method,
                    path,
                    json=json_body,
                    params=params,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "WhatsApp HTTP error on %s (attempt %s/%s): %s",
                    path,
                    attempt,
                    attempts,
                    exc,
                )
                await sleep_for(min(2 ** attempt, 10))
                continue

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 1.0))
                logger.info("WhatsApp rate-limited, sleeping %.2fs", retry_after)
                await sleep_for(retry_after)
                if attempt < attempts:
                    continue
                raise RateLimitError(
                    f"WhatsApp rate limit exceeded for {path}",
                    retry_after=retry_after,
                )

            if response.status_code in (401, 403):
                raise AuthError(
                    f"WhatsApp auth failure ({response.status_code}): {response.text}"
                )
            if response.status_code == 404:
                raise NotFoundError(f"WhatsApp resource missing: {path}")
            if 500 <= response.status_code < 600:
                last_error = IntegrationError(
                    f"WhatsApp server error {response.status_code}"
                )
                await sleep_for(min(2 ** attempt, 10))
                continue

            try:
                payload = response.json()
            except Exception as exc:
                raise IntegrationError(f"Invalid WhatsApp response: {exc}") from exc

            if isinstance(payload, dict):
                if payload.get("error"):
                    error = payload["error"]
                    error_code = error.get("code", 0)
                    error_msg = error.get("message", "unknown")
                    if error_code in (102, 190):
                        raise AuthError(f"WhatsApp auth error: {error_msg}")
                    raise IntegrationError(f"WhatsApp API error: {error_msg}")
                return payload

            return {"data": payload}

        assert last_error is not None
        raise IntegrationError(
            f"WhatsApp request failed after retries: {last_error}"
        )

    async def send_message(
        self,
        channel: str,
        content: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a text message via WhatsApp.

        Args:
            channel: Recipient phone number (with country code, no + sign)
            content: Message text content
        """
        return await self.send_text(to=channel, content=content)

    async def send_text(self, to: str, content: str) -> dict[str, Any]:
        """Send a plain text message."""

        async def _do() -> dict[str, Any]:
            payload = {
                "messaging_product": "whatsapp",
                "to": to.lstrip("+"),
                "type": "text",
                "text": {"preview_url": False, "body": content},
            }
            result = await self._request(
                "POST",
                f"{self.phone_number_id}/messages",
                json_body=payload,
            )
            return {
                "ok": True,
                "message_id": result.get("messages", [{}])[0].get("id"),
                "wa_id": result.get("contacts", [{}])[0].get("wa_id"),
                "raw": result,
            }

        return await safe_call(_do)

    async def send_template(
        self,
        to: str,
        template_name: str,
        language: str = "en_US",
        components: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send a message template."""

        async def _do() -> dict[str, Any]:
            payload = {
                "messaging_product": "whatsapp",
                "to": to.lstrip("+"),
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": language},
                },
            }
            if components:
                payload["template"]["components"] = components
            result = await self._request(
                "POST",
                f"{self.phone_number_id}/messages",
                json_body=payload,
            )
            return {
                "ok": True,
                "message_id": result.get("messages", [{}])[0].get("id"),
                "raw": result,
            }

        return await safe_call(_do)

    async def send_image(
        self,
        to: str,
        media_url: str,
        caption: str = "",
    ) -> dict[str, Any]:
        """Send an image message."""

        async def _do() -> dict[str, Any]:
            payload = {
                "messaging_product": "whatsapp",
                "to": to.lstrip("+"),
                "type": "image",
                "image": {"link": media_url},
            }
            if caption:
                payload["image"]["caption"] = caption
            result = await self._request(
                "POST",
                f"{self.phone_number_id}/messages",
                json_body=payload,
            )
            return {
                "ok": True,
                "message_id": result.get("messages", [{}])[0].get("id"),
                "raw": result,
            }

        return await safe_call(_do)

    async def send_document(
        self,
        to: str,
        media_url: str,
        filename: str,
    ) -> dict[str, Any]:
        """Send a document/file message."""

        async def _do() -> dict[str, Any]:
            payload = {
                "messaging_product": "whatsapp",
                "to": to.lstrip("+"),
                "type": "document",
                "document": {"link": media_url, "filename": filename},
            }
            result = await self._request(
                "POST",
                f"{self.phone_number_id}/messages",
                json_body=payload,
            )
            return {
                "ok": True,
                "message_id": result.get("messages", [{}])[0].get("id"),
                "raw": result,
            }

        return await safe_call(_do)

    async def mark_read(self, message_id: str) -> dict[str, Any]:
        """Mark a message as read."""

        async def _do() -> dict[str, Any]:
            payload = {
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id,
            }
            result = await self._request(
                "POST",
                f"{self.phone_number_id}/messages",
                json_body=payload,
            )
            return {"ok": True, "raw": result}

        return await safe_call(_do)

    async def get_profile(self, wa_id: str) -> dict[str, Any]:
        """Get WhatsApp user profile info."""

        async def _do() -> dict[str, Any]:
            result = await self._request(
                "GET",
                f"{self.phone_number_id}/contacts",
                params={"wa_id": wa_id.lstrip("+")},
            )
            contacts = result.get("contacts", [])
            if contacts:
                return {"ok": True, "profile": contacts[0]}
            return {"ok": False, "error": "Contact not found"}

        return await safe_call(_do)

    async def set_webhook(self, url: str, verify_token: str) -> dict[str, Any]:
        """Register webhook URL for incoming messages."""

        async def _do() -> dict[str, Any]:
            result = await self._request(
                "POST",
                f"{self.phone_number_id}/webhooks",
                json_body={
                    "url": url,
                    "verify_token": verify_token,
                    "messaging_product": "whatsapp",
                },
            )
            return {"ok": True, "raw": result}

        return await safe_call(_do)

    def verify_webhook(self, mode: str, token: str) -> bool:
        """Verify webhook challenge from Meta.

        Called by webhook endpoint to validate the setup.
        Returns True if challenge should be echoed back.
        """
        if mode == "subscribe" and token == self.verify_token:
            return True
        return False

    async def handle_webhook_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Process incoming webhook event."""
        callback = self._event_callback
        if callback is not None:
            try:
                await callback(event)
            except Exception as exc:
                logger.warning("WhatsApp webhook callback raised: %s", exc)
        return {"ok": True}

    async def receive_messages(
        self,
        callback: ReceiveCallback,
        **kwargs: Any,
    ) -> None:
        """Store callback for webhook events."""
        self._event_callback = callback

    async def list_channels(self) -> list[dict[str, Any]]:
        """WhatsApp does not support channel listing."""
        return []

    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Get user profile by WhatsApp ID."""
        return await self.get_profile(user_id)
