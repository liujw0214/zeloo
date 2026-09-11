"""Email platform adapter.

Sends replies via SMTP and receives incoming messages by polling an
IMAP inbox. Uses only the Python standard library.
"""

from __future__ import annotations

import email
import imaplib
import logging
import smtplib
import threading
from collections.abc import Callable
from email.message import EmailMessage

logger = logging.getLogger(__name__)


class EmailAdapter:
    """Email adapter — SMTP out, IMAP in (polled)."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        imap_host: str,
        imap_port: int,
        username: str,
        password: str,
        use_tls: bool = True,
        poll_interval: int = 30,
    ) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._imap_host = imap_host
        self._imap_port = imap_port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._poll_interval = poll_interval

        self._handler: Callable[[str, str, str], str] | None = None
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None

    def start(self, handler: Callable[[str, str, str], str]) -> None:
        """Start the IMAP polling loop in a background thread."""
        self._handler = handler
        self._stop_event.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="email-poll"
        )
        self._poll_thread.start()
        logger.info("Email adapter started (polling every %ds)", self._poll_interval)

    def stop(self) -> None:
        """Stop the polling loop."""
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=5)
            self._poll_thread = None
        logger.info("Email adapter stopped")

    # ── Internal ────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._check_inbox()
            except Exception:
                logger.exception("Email inbox check failed")
            self._stop_event.wait(self._poll_interval)

    def _check_inbox(self) -> None:
        """Connect to IMAP, fetch unread messages, process them."""
        if self._use_tls:
            mail = imaplib.IMAP4_SSL(self._imap_host, self._imap_port)
        else:
            mail = imaplib.IMAP4(self._imap_host, self._imap_port)
        mail.login(self._username, self._password)
        mail.select("INBOX")

        _status, data = mail.search(None, "UNSEEN")
        for num in data[0].split():
            _status, msg_data = mail.fetch(num, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            sender = msg.get("From", "")
            subject = msg.get("Subject", "")
            body = self._get_body(msg)
            text = f"Subject: {subject}\n\n{body}" if subject else body

            if self._handler and sender and text:
                try:
                    reply = self._handler("email", sender, text)
                except Exception:
                    logger.exception("Email handler failed for %s", sender)
                    reply = "An internal error occurred. Please try again."
                self.send_message(sender, reply)

        mail.close()
        mail.logout()

    @staticmethod
    def _get_body(msg: email.message.Message) -> str:
        """Extract the text body from an email message."""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode("utf-8", errors="replace")
            return ""
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode("utf-8", errors="replace")
        return ""

    def send_message(self, to: str, text: str) -> None:
        """Send an email reply via SMTP."""
        msg = EmailMessage()
        msg["From"] = self._username
        msg["To"] = to
        msg["Subject"] = "Re: " + text.split("\n", 1)[0][:70]
        msg.set_content(text)

        if self._use_tls:
            with smtplib.SMTP_SSL(self._smtp_host, self._smtp_port) as server:
                server.login(self._username, self._password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
                server.starttls()
                server.login(self._username, self._password)
                server.send_message(msg)
        logger.info("Email sent to %s", to)
