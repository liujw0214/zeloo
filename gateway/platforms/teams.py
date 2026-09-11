"""Microsoft Teams platform adapter.

Receives messages via the Teams Bot Framework HTTP webhook and replies
via the Bot Framework REST API. Access tokens are obtained through the
OAuth 2.0 ``client_credentials`` flow using the bot's app id + password.

Reference: https://learn.microsoft.com/azure/bot-service/rest-api/bot-framework-rest-3-0-api-reference
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from gateway.platforms.webhook_base import WebhookAdapter

logger = logging.getLogger(__name__)

TEAMS_LOGIN_BASE = "https://login.microsoftonline.com"
TEAMS_API_BASE = "https://smba.trafficmanager.net/teams/v3"
TEAMS_TOKEN_TTL = 5400  # access tokens last ~3600s, refresh early


class TeamsAdapter(WebhookAdapter):
    """Microsoft Teams bot adapter using the Bot Framework REST API."""

    def __init__(
        self,
        bot_id: str,
        bot_password: str,
        webhook_port: int = 9113,
    ) -> None:
        super().__init__(webhook_path="/teams/messages", webhook_port=webhook_port)
        self._bot_id = bot_id
        self._bot_password = bot_password
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._conversation_refs: dict[str, dict[str, Any]] = {}

    # ── Auth ────────────────────────────────────────────────────────

    def _get_access_token(self) -> str:
        """Obtain (and cache) an OAuth 2.0 ``client_credentials`` token.

        Tokens are cached and refreshed 5 minutes before expiry to avoid
        race conditions near the TTL boundary.
        """
        now = time.time()
        if self._token and now < self._token_expires_at:
            return self._token

        url = f"{TEAMS_LOGIN_BASE}/{self._bot_id}/oauth2/v2.0/token"
        body = {
            "grant_type": "client_credentials",
            "client_id": self._bot_id,
            "client_secret": self._bot_password,
            "scope": "https://api.botframework.com/.default",
        }
        status, resp = self._http_post(url, json_body=body)
        if status != 200:
            raise RuntimeError(f"Teams token request failed: {status} {resp[:200]}")
        try:
            data = json.loads(resp)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Teams token response not JSON: {resp[:200]}") from e
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"Teams token error: {data}")
        self._token = token
        # expires_in is in seconds; default to the standard 1h
        self._token_expires_at = now + data.get("expires_in", 3600) - 300
        return self._token

    # ── Verification ────────────────────────────────────────────────

    def verify_request(self, body: bytes, headers: dict[str, str]) -> bool:
        """Optional lightweight token verification.

        The Bot Framework recommends validating the signed JWT in the
        ``Authorization`` header. Here we perform a simple presence
        check when ``verify_token`` is configured; full JWT verification
        can be layered on top.
        """
        if not self._verify_token:
            return True
        return headers.get("x-verify-token") == self._verify_token

    # ── Incoming ────────────────────────────────────────────────────

    def parse_incoming(self, body: bytes, headers: dict[str, str]) -> tuple[str, str] | None:
        """Parse a Bot Framework activity payload.

        Handles both ``message`` activities (text messages) and
        ``conversationUpdate`` activities (membership changes) — the
        latter are ignored for the purpose of producing a reply.
        """
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return None

        activity_type = payload.get("type", "")
        if activity_type == "conversationUpdate":
            # Membership events should not be treated as user messages.
            return None
        if activity_type != "message":
            return None

        # Ignore messages emitted by other bots to avoid loops.
        if payload.get("from", {}).get("role") == "bot":
            return None

        # Capture the conversation reference so we can reply asynchronously.
        conversation_id = payload.get("conversation", {}).get("id")
        if conversation_id:
            self._conversation_refs[conversation_id] = {
                "conversationId": conversation_id,
                "serviceUrl": payload.get("serviceUrl", ""),
            }

        user_id = payload.get("from", {}).get("id", "")
        text = payload.get("text", "")
        # Strip mentions: Teams prefixes mentions with the bot's name.
        text = self._strip_mention(text)
        if not user_id or not text:
            return None
        return user_id, text

    @staticmethod
    def _strip_mention(text: str) -> str:
        """Strip the leading ``<at>BotName</at>`` mention from a message."""
        if "<at>" in text and "</at>" in text:
            start = text.find("<at>")
            end = text.find("</at>", start) + len("</at>")
            text = text[:start] + text[end:]
        return text.strip()

    # ── Outgoing ────────────────────────────────────────────────────

    def send_message(self, user_id: str, text: str) -> None:
        """Send a reply via the Bot Framework REST API.

        Uses the cached conversation reference for ``user_id`` (which we
        treat as the Teams conversation id). Text longer than ~4096
        characters is truncated to stay within Bot Framework limits.
        """
        token = self._get_access_token()
        ref = self._conversation_refs.get(user_id)
        conversation_id = ref["conversationId"] if ref else user_id
        url = f"{TEAMS_API_BASE}/conversations/{conversation_id}/activities"
        headers = {"Authorization": f"Bearer {token}"}
        body = {
            "type": "message",
            "text": text[:4096],
        }
        status, resp = self._http_post(url, json_body=body, headers=headers)
        if status != 200:
            logger.error("Teams send failed: %s %s", status, resp[:200])
