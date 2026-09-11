"""WeCom (WeChat Work) platform adapter.

Receives messages via WeCom HTTP callback (webhook) and replies via the
WeCom Open API ``cgi-bin/message/send`` endpoint. WeCom verifies callbacks
using a SHA1 signature of ``timestamp + nonce + token``.

Reference: https://developer.work.weixin.qq.com/document/path/90238
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"


class WeComAdapter:
    """WeCom (企业微信) application adapter."""

    def __init__(
        self,
        corp_id: str,
        corp_secret: str,
        agent_id: int,
        webhook_port: int = 9113,
        token: str | None = None,
        encoding_aes_key: str | None = None,
    ) -> None:
        self._corp_id = corp_id
        self._corp_secret = corp_secret
        self._agent_id = agent_id
        self._token = token
        self._encoding_aes_key = encoding_aes_key
        self._webhook_port = webhook_port
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._handler: Callable[[str, str, str], str] | None = None
        self._server = None
        self._server_thread = None

    # ── Auth ────────────────────────────────────────────────────────

    def _get_access_token(self) -> str:
        """Obtain (and cache) a WeCom ``access_token``."""
        now = time.time()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        import urllib.parse
        import urllib.request

        params = urllib.parse.urlencode(
            {"corpid": self._corp_id, "corpsecret": self._corp_secret}
        )
        url = f"{WECOM_API_BASE}/gettoken?{params}"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"WeCom token request failed: {e}") from e
        if data.get("errcode") != 0:
            raise RuntimeError(f"WeCom token error: {data.get('errmsg')}")
        self._access_token = data["access_token"]
        self._token_expires_at = now + data.get("expires_in", 7200) - 300
        return self._access_token

    # ── Signature verification ──────────────────────────────────────

    def _verify_signature(self, timestamp: str, nonce: str, signature: str) -> bool:
        """Verify WeCom callback signature.

        WeCom signs with SHA1 of the sorted concatenation of
        ``token + timestamp + nonce`` (lexicographically sorted).
        """
        if not self._token:
            return True
        sorted_str = "".join(sorted([self._token, timestamp, nonce]))
        expected = hashlib.sha1(sorted_str.encode("utf-8")).hexdigest()
        return expected == signature

    # ── Webhook server ──────────────────────────────────────────────

    def start(self, handler: Callable[[str, str, str], str]) -> None:
        """Start the WeCom webhook HTTP server."""
        self._handler = handler
        adapter = self

        from http.server import BaseHTTPRequestHandler, HTTPServer

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""
                # WeCom passes signature params in the query string
                from urllib.parse import parse_qs, urlparse

                parsed_url = urlparse(self.path)
                query = parse_qs(parsed_url.query)
                msg_signature = query.get("msg_signature", [""])[0]
                timestamp = query.get("timestamp", [""])[0]
                nonce = query.get("nonce", [""])[0]

                if not adapter._verify_signature(timestamp, nonce, msg_signature):
                    self.send_error(403, "Invalid signature")
                    return

                try:
                    parsed = adapter._parse_incoming(body)
                except Exception:
                    logger.exception("Failed to parse WeCom webhook")
                    self.send_error(400)
                    return

                if parsed is None:
                    self._respond_empty()
                    return

                user_id, text = parsed
                try:
                    reply = adapter._handler("wecom", user_id, text)  # type: ignore[misc]
                except Exception:
                    logger.exception("Handler failed for user %s", user_id)
                    from agent.i18n import gettext

                    reply = gettext("internal_error")
                try:
                    adapter.send_message(user_id, reply)
                except Exception:
                    logger.exception("Failed to send WeCom reply to %s", user_id)
                self._respond_empty()

            def _respond_empty(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"")

            def log_message(self, *args: object) -> None:
                pass

        self._server = HTTPServer(("0.0.0.0", self._webhook_port), _Handler)
        import threading

        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name=f"wecom-{self._webhook_port}",
        )
        self._server_thread.start()
        logger.info("WeCom adapter listening on port %d", self._webhook_port)

    def stop(self) -> None:
        """Stop the webhook HTTP server."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            logger.info("WeCom adapter stopped")

    # ── Parsing ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_incoming(body: bytes) -> tuple[str, str] | None:
        """Parse a WeCom message XML callback payload.

        WeCom sends XML-formatted callbacks. We extract ``FromUserName``
        (user id) and ``Content`` (text message).
        """
        import xml.etree.ElementTree as ET

        try:
            root = ET.fromstring(body.decode("utf-8"))
        except ET.ParseError:
            return None

        msg_type = root.findtext("MsgType", "")
        if msg_type != "text":
            return None  # only text messages supported

        from_user = root.findtext("FromUserName", "")
        content = root.findtext("Content", "")
        if not from_user or not content:
            return None
        return from_user, content

    # ── Outgoing ────────────────────────────────────────────────────

    def send_message(self, user_id: str, text: str) -> None:
        """Send a text reply to a WeCom user.

        Uses the ``message/send`` API targeting the user's id.
        """
        token = self._get_access_token()
        url = f"{WECOM_API_BASE}/message/send?access_token={token}"
        body = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": self._agent_id,
            "text": {"content": text[:2048]},
        }
        status, resp = self._http_post(url, json_body=body)
        if status != 200:
            logger.error("WeCom send failed: %s %s", status, resp[:200])

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
