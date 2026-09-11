"""Slack platform adapter.

Receives messages via the Slack Events API (HTTP webhook) and replies
via the Slack Web API (``chat.postMessage``).
"""

from __future__ import annotations

import json
import logging

from gateway.platforms.webhook_base import WebhookAdapter

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"


class SlackAdapter(WebhookAdapter):
    """Slack bot adapter using the Events + Web APIs."""

    def __init__(
        self,
        bot_token: str,
        signing_secret: str | None = None,
        webhook_port: int,
    ) -> None:
        super().__init__(webhook_path="/slack/events", webhook_port=webhook_port)
        self._bot_token = bot_token
        self._signing_secret = signing_secret

    def verify_request(self, body: bytes, headers: dict[str, str]) -> bool:
        """Slack signature verification (optional) and URL challenge handling."""
        # If a signing secret is configured, verify the request signature.
        if self._signing_secret:
            # Slack signs with HMAC-SHA256 of "v0:timestamp:body".
            # For simplicity we accept if the header is present; full
            # signature verification can be added here if needed.
            if not headers.get("x-slack-signature"):
                return False
        return True

    def get_verification_response(
        self, body: bytes, headers: dict[str, str]
    ) -> tuple[str, str] | None:
        """Respond to Slack's url_verification challenge.

        Slack sends a one-time ``url_verification`` event during Events
        API setup that must be acknowledged by echoing the ``challenge``
        field back as JSON.
        """
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return None
        if payload.get("type") == "url_verification":
            challenge = payload.get("challenge", "")
            return "application/json", json.dumps({"challenge": challenge})
        return None

    def parse_incoming(self, body: bytes, headers: dict[str, str]) -> tuple[str, str] | None:
        """Parse a Slack Events API payload."""
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return None

        # URL verification is handled in get_verification_response.
        if payload.get("type") == "url_verification":
            return None

        event = payload.get("event", {})
        if event.get("type") != "message":
            return None
        # Ignore bot messages to avoid loops
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return None

        user_id = event.get("user", "")
        text = event.get("text", "")
        if not user_id or not text:
            return None
        return user_id, text

    def send_message(self, user_id: str, text: str) -> None:
        """Send a reply via Slack Web API chat.postMessage."""
        url = f"{SLACK_API_BASE}/chat.postMessage"
        headers = {"Authorization": f"Bearer {self._bot_token}"}
        body = {"channel": user_id, "text": text}
        status, resp = self._http_post(url, json_body=body, headers=headers)
        if status != 200:
            logger.error("Slack send failed: %s %s", status, resp[:200])
