"""Mattermost platform adapter.

Receives messages via the Mattermost outgoing webhook (HTTP POST) and
replies via the Mattermost REST API ``/api/v4/posts`` endpoint using a
bot personal access token.

Mattermost outgoing webhooks post form-encoded fields (``text``,
``user_id``, ``channel_id``); the adapter parses these and caches the
``channel_id`` keyed by ``user_id`` so replies can be addressed back to
the originating channel.

Reference: https://developers.mattermost.com/integrate/webhooks/outgoing/
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs

from gateway.platforms.webhook_base import WebhookAdapter

logger = logging.getLogger(__name__)


class MattermostAdapter(WebhookAdapter):
    """Mattermost bot adapter using outgoing webhook + REST API."""

    def __init__(
        self,
        base_url: str,
        bot_token: str,
        webhook_port: int = 9113,
    ) -> None:
        super().__init__(webhook_path="/mattermost/webhook", webhook_port=webhook_port)
        # Normalize: strip trailing slash so we can append paths cleanly.
        self._base_url = base_url.rstrip("/")
        self._bot_token = bot_token
        self._channel_map: dict[str, str] = {}

    # ── Verification ─────────────────────────────────────────────────

    def verify_request(self, body: bytes, headers: dict[str, str]) -> bool:
        """Verify the incoming Mattermost webhook.

        Mattermost outgoing webhooks optionally include a ``token`` form
        field that can be matched against a configured verify token. When
        no ``verify_token`` is set on the adapter, all requests are
        accepted.
        """
        if not self._verify_token:
            return True
        fields = parse_qs(body.decode("utf-8", errors="replace"))
        token_values = fields.get("token", [])
        if not token_values:
            return False
        return any(t == self._verify_token for t in token_values)

    # ── Incoming ─────────────────────────────────────────────────────

    def parse_incoming(self, body: bytes, headers: dict[str, str]) -> tuple[str, str] | None:
        """Parse a Mattermost outgoing webhook payload.

        Mattermost posts form-encoded fields: ``text``, ``user_id``,
        ``user_name``, ``channel_id``, ``team_id`` etc. We extract the
        message text and user id, and cache the ``channel_id`` for
        replying back to the same channel.

        Returns:
            ``(user_id, text)`` tuple, or ``None`` when the payload is
            missing required fields.
        """
        fields = parse_qs(body.decode("utf-8", errors="replace"))
        text_values = fields.get("text", [])
        user_values = fields.get("user_id", [])
        channel_values = fields.get("channel_id", [])
        if not text_values or not user_values:
            return None
        text = text_values[0].strip()
        user_id = user_values[0]
        if not text or not user_id:
            return None
        if channel_values:
            self._channel_map[user_id] = channel_values[0]
        return user_id, text

    # ── Outgoing ─────────────────────────────────────────────────────

    def send_message(self, user_id: str, text: str) -> None:
        """Send a reply via the Mattermost REST API.

        Looks up the ``channel_id`` cached during ``parse_incoming`` for
        the given ``user_id`` and posts the reply there. Falls back to a
        direct message to ``user_id`` when no channel mapping exists.
        """
        channel_id = self._channel_map.get(user_id, user_id)
        url = f"{self._base_url}/api/v4/posts"
        headers = {
            "Authorization": f"Bearer {self._bot_token}",
        }
        body: dict[str, Any] = {
            "channel_id": channel_id,
            "message": text[:16383],  # Mattermost post message cap
        }
        status, resp = self._http_post(url, json_body=body, headers=headers)
        if status != 200 and status != 201:
            logger.error("Mattermost send failed: %s %s", status, resp[:200])

    # ── Verification response helper ─────────────────────────────────

    def get_verification_response(
        self, body: bytes, headers: dict[str, str]
    ) -> tuple[str, str] | None:
        """Optionally echo back a Mattermost challenge payload.

        Mattermost outgoing webhooks do not require a challenge
        handshake, so this always returns ``None``. Provided for
        consistency with the base class contract.
        """
        _ = body, headers  # unused — no challenge flow for Mattermost
        return None
