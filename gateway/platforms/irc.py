"""IRC (Internet Relay Chat) platform adapter.

Uses a raw TCP socket connection (stdlib only) to connect to an IRC
server, join a channel, and exchange messages. Unlike HTTP-webhook
adapters, IRC is a persistent TCP protocol.

Independent class (does not inherit WebhookAdapter) because IRC uses
a TCP socket rather than HTTP webhooks.

Reference: https://datatracker.ietf.org/doc/html/rfc1459
"""

from __future__ import annotations

import logging
import socket
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

IRC_RECV_BUFFER = 4096


class IRCAdapter:
    """IRC adapter using raw TCP sockets (stdlib only).

    Uses the ``socket`` module to implement the IRC protocol
    (NICK, USER, JOIN, PRIVMSG, PING/PONG, QUIT).
    """

    def __init__(
        self,
        server: str,
        nickname: str,
        channel: str,
        port: int = 6667,
        password: str | None = None,
    ) -> None:
        self._server = server
        self._port = port
        self._nickname = nickname
        self._channel = channel
        self._password = password
        self._handler: Callable[[str, str, str], str] | None = None
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ── Lifecycle ───────────────────────────────────────────────────

    def start(self, handler: Callable[[str, str, str], str]) -> None:
        """Connect to the IRC server, join the channel, and start the
        receive loop in a background thread.

        Args:
            handler: Callback receiving ``(platform, user_id, message)``
                     and returning the assistant's reply string.
        """
        self._handler = handler
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((self._server, self._port))
        if self._password:
            self._send_raw(f"PASS {self._password}")
        self._send_raw(f"NICK {self._nickname}")
        self._send_raw(f"USER {self._nickname} 0 * :{self._nickname}")
        self._thread = threading.Thread(
            target=self._recv_loop,
            daemon=True,
            name="irc-recv",
        )
        self._thread.start()
        logger.info("IRC adapter connected to %s:%d", self._server, self._port)

    def stop(self) -> None:
        """Send QUIT command and close the socket."""
        self._stop_event.set()
        if self._sock is not None:
            try:
                self._send_raw("QUIT :Adapter shutting down")
            except Exception:
                logger.exception("Failed to send IRC QUIT")
            try:
                self._sock.close()
            except Exception:
                logger.exception("Failed to close IRC socket")
            self._sock = None
        logger.info("IRC adapter stopped")

    # ── IRC protocol ────────────────────────────────────────────────

    def _send_raw(self, line: str) -> None:
        """Send a raw IRC command line to the server.

        Args:
            line: IRC command string (without trailing CRLF).
        """
        if self._sock is None:
            return
        self._sock.sendall((line + "\r\n").encode())

    def _recv_loop(self) -> None:
        """Background receive loop.

        Reads lines from the socket, responds to PING keepalives,
        joins the channel after the 001 (RPL_WELCOME) reply, and
        dispatches PRIVMSG events to the handler.
        """
        buffer = ""
        while not self._stop_event.is_set():
            assert self._sock is not None
            try:
                chunk = self._sock.recv(IRC_RECV_BUFFER).decode(
                    "utf-8", errors="replace"
                )
            except (OSError, ConnectionError):
                break
            if not chunk:
                break
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.rstrip("\r")
                self._handle_line(line)

    def _handle_line(self, line: str) -> None:
        """Process a single IRC line from the server.

        Args:
            line: A single IRC protocol line (without trailing CRLF).
        """
        # Respond to PING keepalive
        if line.startswith("PING"):
            pong = line.replace("PING", "PONG", 1)
            self._send_raw(pong)
            return

        # Join channel after registration is accepted (RPL_WELCOME)
        if " 001 " in line:
            self._send_raw(f"JOIN {self._channel}")
            return

        # Parse and dispatch PRIVMSG
        parsed = self.parse(line)
        if parsed is None:
            return
        user_id, text = parsed
        if self._handler is None:
            return
        try:
            reply = self._handler("irc", user_id, text)
        except Exception:
            logger.exception("Handler failed for user %s", user_id)
            from agent.i18n import gettext

            reply = gettext("internal_error")
        try:
            self.send_message(user_id, reply)
        except Exception:
            logger.exception("Failed to send IRC reply to %s", user_id)

    # ── Parsing ─────────────────────────────────────────────────────

    @staticmethod
    def parse(line: str) -> tuple[str, str] | None:
        """Parse an IRC PRIVMSG line.

        Parses the standard IRC message format::

            :nick!user@host PRIVMSG #channel :text

        Args:
            line: A single IRC protocol line.

        Returns:
            A ``(nick, message_text)`` tuple, or None if the line is
            not a PRIVMSG or has no text content.
        """
        if not line.startswith(":"):
            return None
        rest = line[1:]
        parts = rest.split(" ", 2)
        if len(parts) < 3:
            return None
        source = parts[0]  # e.g. "nick!user@host"
        command = parts[1]  # e.g. "PRIVMSG"
        trailing = parts[2]  # e.g. "#channel :text"
        if command != "PRIVMSG":
            return None
        nick = source.split("!", 1)[0] if "!" in source else source
        if ":" not in trailing:
            return None
        text = trailing.split(":", 1)[1]
        if not text:
            return None
        return nick, text

    # ── Outgoing ────────────────────────────────────────────────────

    def send_message(self, user_id: str, text: str) -> None:
        """Send a PRIVMSG to the joined channel.

        Args:
            user_id: Sender nickname (unused for channel messages, kept
                     for API compatibility with other adapters).
            text: Message text to send to the channel.
        """
        # IRC lines must not contain embedded CR/LF in the text
        safe_text = text.replace("\r", " ").replace("\n", " ")[:500]
        self._send_raw(f"PRIVMSG {self._channel} :{safe_text}")
