"""Signal platform adapter.

Uses the ``signal-cli`` JSON-RPC HTTP API (when available) to send and
receive messages. Falls back to a subprocess-based approach for sending.
"""

from __future__ import annotations

import json
import logging
import subprocess

from gateway.platforms.webhook_base import WebhookAdapter

logger = logging.getLogger(__name__)


class SignalAdapter(WebhookAdapter):
    """Signal messenger adapter via signal-cli."""

    def __init__(
        self,
        account: str,
        signal_cli_path: str = "signal-cli",
        api_url: str | None = None,
        webhook_port: int,
    ) -> None:
        super().__init__(webhook_path="/signal/webhook", webhook_port=webhook_port)
        self._account = account
        self._signal_cli_path = signal_cli_path
        self._api_url = api_url

    def parse_incoming(self, body: bytes, headers: dict[str, str]) -> tuple[str, str] | None:
        """Parse a Signal message payload (from signal-cli webhook)."""
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return None

        # signal-cli envelope format
        envelope = payload.get("envelope", payload)
        source = envelope.get("sourceNumber") or envelope.get("source")
        message = envelope.get("dataMessage", {}).get("message")
        if not source or not message:
            return None
        return str(source), str(message)

    def send_message(self, user_id: str, text: str) -> None:
        """Send a message via signal-cli (subprocess fallback)."""
        if self._api_url:
            self._send_via_api(user_id, text)
        else:
            self._send_via_cli(user_id, text)

    def _send_via_api(self, user_id: str, text: str) -> None:
        """Send via signal-cli JSON-RPC HTTP API."""
        url = f"{self._api_url}/v1/send"
        body = {"message": text, "number": user_id}
        status, resp = self._http_post(url, json_body=body)
        if status != 200:
            logger.error("Signal API send failed: %s %s", status, resp[:200])

    def _send_via_cli(self, user_id: str, text: str) -> None:
        """Send via signal-cli subprocess."""
        try:
            result = subprocess.run(
                [
                    self._signal_cli_path,
                    "-u",
                    self._account,
                    "send",
                    "-m",
                    text,
                    user_id,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.error("signal-cli send failed: %s", result.stderr[:200])
        except FileNotFoundError:
            logger.error(
                "signal-cli not found at '%s'. Install signal-cli or set api_url.",
                self._signal_cli_path,
            )
        except Exception:
            logger.exception("signal-cli send failed")
