"""WhatsApp Business API platform adapter.

Receives messages via WhatsApp webhook and replies via the
WhatsApp Cloud API (Graph API).
"""

from __future__ import annotations

import json
import logging
import os

from gateway.platforms.webhook_base import WebhookAdapter

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"


class WhatsAppAdapter(WebhookAdapter):
    """WhatsApp Business API adapter."""

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        verify_token: str | None = None,
        webhook_port: int,
    ) -> None:
        super().__init__(
            webhook_path="/whatsapp/webhook",
            webhook_port=webhook_port,
            verify_token=verify_token or os.environ.get("WHATSAPP_VERIFY_TOKEN"),
        )
        self._access_token = access_token
        self._phone_number_id = phone_number_id

    def verify_request(self, body: bytes, headers: dict[str, str]) -> bool:
        """WhatsApp webhook verification (hub.mode / hub.challenge)."""
        # WhatsApp verifies via GET with hub.mode, hub.challenge, hub.verify_token
        # The base handler only handles POST; GET verification is handled in
        # a separate path. For POST payloads, accept all (no signature check
        # without the app secret).
        return True

    def parse_incoming(self, body: bytes, headers: dict[str, str]) -> tuple[str, str] | None:
        """Parse a WhatsApp webhook payload."""
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return None

        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None

        msg = messages[0]
        if msg.get("type") != "text":
            return None

        user_id = msg.get("from", "")
        text = msg.get("text", {}).get("body", "")
        if not user_id or not text:
            return None
        return user_id, text

    def send_message(self, user_id: str, text: str) -> None:
        """Send a text message via the WhatsApp Cloud API."""
        url = f"{GRAPH_API_BASE}/{self._phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self._access_token}"}
        body = {
            "messaging_product": "whatsapp",
            "to": user_id,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        status, resp = self._http_post(url, json_body=body, headers=headers)
        if status != 200:
            logger.error("WhatsApp send failed: %s %s", status, resp[:200])
