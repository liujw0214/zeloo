"""DingTalk platform adapter.

Receives messages via DingTalk robot HTTP callback (webhook) and replies
via the DingTalk Open API ``topapi/robot/send`` endpoint. Requests are
authenticated using HMAC-SHA256 over the timestamp + body.

Reference: https://open.dingtalk.com/document/orgapp/receive-message
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

DINGTALK_API_BASE = "https://api.dingtalk.com/v1.0"


class DingTalkAdapter:
    """DingTalk custom robot adapter using HTTP callback + Open API."""

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        webhook_port: int = 9113,
        verify_token: str | None = None,
    ) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._verify_token = verify_token
        self._webhook_port = webhook_port
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._handler: Callable[[str, str, str], str] | None = None
        self._server = None
        self._server_thread = None

    # ── Auth ────────────────────────────────────────────────────────

    def _get_access_token(self) -> str:
        """Obtain (and cache) a DingTalk ``access_token``."""
        now = time.time()
        if self._token and now < self._token_expires_at:
            return self._token

        url = f"{DINGTALK_API_BASE}/oauth2/accessToken"
        body = {"appKey": self._app_key, "appSecret": self._app_secret}
        status, resp = self._http_post(url, json_body=body)
        if status != 200:
            raise RuntimeError(f"DingTalk token request failed: {status} {resp[:200]}")
        try:
            data = json.loads(resp)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"DingTalk token response not JSON: {resp[:200]}") from e
        self._token = data.get("accessToken")
        if not self._token:
            raise RuntimeError(f"DingTalk token error: {data}")
        # DingTalk tokens are valid for ~7200s
        self._token_expires_at = now + data.get("expireIn", 7200) - 300
        return self._token

    # ── Signature verification ──────────────────────────────────────

    def _verify_signature(self, timestamp: str, signature: str, body: bytes) -> bool:
        """Verify DingTalk callback signature.

        DingTalk signs with HMAC-SHA256 of ``timestamp + "\\n" + body``
        using the app secret as the key, then base64-encodes the result.
        """
        if not self._app_secret:
            return True
        string_to_sign = f"{timestamp}\n".encode() + body
        h = hmac.new(self._app_secret.encode("utf-8"), string_to_sign, hashlib.sha256)
        expected = base64.b64encode(h.digest()).decode("utf-8")
        return hmac.compare_digest(expected, signature)

    # ── Webhook server ──────────────────────────────────────────────

    def start(self, handler: Callable[[str, str, str], str]) -> None:
        """Start the DingTalk webhook HTTP server."""
        self._handler = handler
        adapter = self

        from http.server import BaseHTTPRequestHandler, HTTPServer

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""
                headers = {k.lower(): v for k, v in self.headers.items()}

                # Signature verification
                timestamp = headers.get("timestamp", "")
                signature = headers.get("sign", "")
                if not adapter._verify_signature(timestamp, signature, body):
                    self.send_error(403, "Invalid signature")
                    return

                # Optional token check
                if adapter._verify_token:
                    payload_token = ""
                    try:
                        payload = json.loads(body.decode("utf-8"))
                        payload_token = payload.get("token", "")
                    except json.JSONDecodeError:
                        pass
                    if payload_token != adapter._verify_token:
                        self.send_error(403, "Invalid token")
                        return

                try:
                    parsed = adapter._parse_incoming(body)
                except Exception:
                    logger.exception("Failed to parse DingTalk webhook")
                    self.send_error(400)
                    return

                if parsed is None:
                    self._respond_empty()
                    return

                user_id, text = parsed
                try:
                    reply = adapter._handler("dingtalk", user_id, text)  # type: ignore[misc]
                except Exception:
                    logger.exception("Handler failed for user %s", user_id)
                    from agent.i18n import gettext

                    reply = gettext("internal_error")
                try:
                    adapter.send_message(user_id, reply)
                except Exception:
                    logger.exception("Failed to send DingTalk reply to %s", user_id)
                self._respond_empty()

            def _respond_empty(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args: object) -> None:
                pass

        self._server = HTTPServer(("0.0.0.0", self._webhook_port), _Handler)
        import threading

        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name=f"dingtalk-{self._webhook_port}",
        )
        self._server_thread.start()
        logger.info("DingTalk adapter listening on port %d", self._webhook_port)

    def stop(self) -> None:
        """Stop the webhook HTTP server."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            logger.info("DingTalk adapter stopped")

    # ── Parsing ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_incoming(body: bytes) -> tuple[str, str] | None:
        """Parse a DingTalk text message callback payload."""
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return None

        # DingTalk callback payloads include a "msgtype" field
        msg_type = payload.get("msgtype", "")
        if msg_type != "text":
            return None  # only text messages supported

        text = payload.get("text", {}).get("content", "")
        sender_id = payload.get("senderId") or payload.get("senderStaffId", "")
        if not text or not sender_id:
            return None
        return sender_id, text

    # ── Outgoing ────────────────────────────────────────────────────

    def send_message(self, user_id: str, text: str) -> None:
        """Send a text reply to a DingTalk user.

        Uses the robot send API with the user's staffId as the recipient.
        """
        token = self._get_access_token()
        url = f"{DINGTALK_API_BASE}/robot/groupMessages/send"
        headers = {"x-acs-dingtalk-access-token": token}
        body = {
            "msgKey": "sampleText",
            "msgParam": json.dumps({"content": text[:20000]}),
        }
        status, resp = self._http_post(url, json_body=body, headers=headers)
        if status != 200:
            logger.error("DingTalk send failed: %s %s", status, resp[:200])

    # ── HTTP helper ─────────────────────────────────────────────────

    @staticmethod
    def _http_post(
        url: str,
        json_body: dict | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> tuple[int, str]:
        """Perform an HTTP POST using stdlib (no external deps)."""
        import urllib.error
        import urllib.request

        data = json.dumps(json_body).encode("utf-8") if json_body else b""
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")
