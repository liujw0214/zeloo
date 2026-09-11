"""Chrome DevTools Protocol (CDP) wrapper for advanced browser control.

This module provides a Python wrapper for the Chrome DevTools Protocol,
allowing direct communication with Chrome/Chromium for advanced automation tasks.

Example::

    from tools.browser_cdp_tool import CDPClient, CDPCommand

    client = CDPClient("localhost", 9222)
    client.connect()
    client.execute_command(CDPCommand("Page.enable"))
    client.disconnect()
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class CDPMessage:
    """A Chrome DevTools Protocol message."""

    id: int
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to CDP protocol format."""
        msg = {"id": self.id, "method": self.method}
        if self.params:
            msg["params"] = self.params
        return msg

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CDPMessage:
        """Parse from CDP protocol format."""
        return cls(
            id=data.get("id", 0),
            method=data.get("method", ""),
            params=data.get("params", {}),
            result=data.get("result"),
            error=data.get("error"),
        )


@dataclass
class CDPCommand:
    """A CDP command to send to the browser."""

    method: str
    params: dict[str, Any] | None = None
    command_id: int | None = None

    def __post_init__(self) -> None:
        if self.params is None:
            self.params = {}

    def to_message(self, msg_id: int) -> CDPMessage:
        """Convert to CDPMessage."""
        return CDPMessage(id=msg_id, method=self.method, params=self.params or {})


class CDPClient:
    """Chrome DevTools Protocol client for direct browser communication.

    This client connects to a Chrome instance via CDP (Chrome DevTools Protocol),
    allowing low-level control over browser operations.

    Attributes:
        host: CDP server host address.
        port: CDP server port number.
        timeout: Connection and command timeout in seconds.

    Example::

        client = CDPClient("localhost", 9222)
        if client.connect():
            # Enable Page domain
            client.execute_command(CDPCommand("Page.enable"))
            # Navigate to URL
            client.execute_command(CDPCommand("Page.navigate", {"url": "https://example.com"}))
            # Get page title
            result = client.execute_command(CDPCommand("Runtime.evaluate", {"expression": "document.title"}))
            print(result)
            client.disconnect()
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9222,
        timeout: float = 30.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._message_id = 0
        self._pending: dict[int, asyncio.Future[CDPMessage]] = {}
        self._event_handlers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if client is connected to CDP server."""
        return self._connected and self._socket is not None

    def connect(self) -> bool:
        """Connect to the CDP WebSocket server.

        Returns:
            True if connection successful, False otherwise.
        """
        if self._connected:
            logger.warning("CDP client already connected")
            return True

        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self.timeout)
            self._socket.connect((self.host, self.port))
            self._connected = True
            logger.info("Connected to CDP at %s:%d", self.host, self.port)
            return True
        except socket.error as e:
            logger.error("Failed to connect to CDP at %s:%d: %s", self.host, self.port, e)
            self._socket = None
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect from the CDP server."""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        self._connected = False
        self._pending.clear()
        logger.info("Disconnected from CDP")

    def _get_next_id(self) -> int:
        """Generate next message ID."""
        self._message_id += 1
        return self._message_id

    def execute_command(
        self,
        command: CDPCommand,
        wait_for_result: bool = True,
    ) -> dict[str, Any]:
        """Execute a CDP command and optionally wait for result.

        Args:
            command: The CDP command to execute.
            wait_for_result: Whether to wait for command result.

        Returns:
            Command result dictionary with 'success' key and either 'data' or 'error'.
        """
        if not self.is_connected:
            return {"success": False, "error": "Not connected to CDP server"}

        try:
            msg_id = self._get_next_id()
            msg = command.to_message(msg_id)
            data = json.dumps(msg).encode("utf-8") + b"\n"

            self._socket.sendall(data)
            logger.debug("CDP Command sent: %s (id=%d)", command.method, msg_id)

            if not wait_for_result:
                return {"success": True, "data": {"method": command.method, "sent": True}}

            response_data = self._receive_response(msg_id)
            if response_data is None:
                return {"success": False, "error": "Timeout waiting for response"}

            if "error" in response_data:
                return {
                    "success": False,
                    "error": response_data["error"].get("message", "Unknown CDP error"),
                    "error_code": response_data["error"].get("code"),
                }

            return {"success": True, "data": response_data.get("result", {})}

        except socket.timeout:
            return {"success": False, "error": f"Command timeout after {self.timeout}s"}
        except Exception as e:
            logger.exception("CDP command execution failed")
            return {"success": False, "error": str(e)}

    def _receive_response(self, expected_id: int) -> dict[str, Any] | None:
        """Receive and parse CDP response from socket."""
        if not self._socket:
            return None

        self._socket.settimeout(self.timeout)
        try:
            data = b""
            while True:
                chunk = self._socket.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break

            if data:
                response = json.loads(data.decode("utf-8"))
                return response
        except json.JSONDecodeError as e:
            logger.error("Failed to parse CDP response: %s", e)
        except socket.timeout:
            logger.warning("Timeout waiting for CDP response (id=%d)", expected_id)

        return None

    def register_event_handler(
        self,
        event: str,
        handler: Callable[[dict[str, Any]], None],
    ) -> None:
        """Register a handler for a CDP event.

        Args:
            event: CDP event name (e.g., "Page.loadEventFired").
            handler: Callback function to handle the event.
        """
        if event not in self._event_handlers:
            self._event_handlers[event] = []
        self._event_handlers[event].append(handler)
        logger.debug("Registered handler for CDP event: %s", event)

    def unregister_event_handler(
        self,
        event: str,
        handler: Callable[[dict[str, Any]], None],
    ) -> None:
        """Unregister a handler for a CDP event.

        Args:
            event: CDP event name.
            handler: Handler function to remove.
        """
        if event in self._event_handlers:
            try:
                self._event_handlers[event].remove(handler)
            except ValueError:
                pass

    def send_command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a CDP command by method name.

        Args:
            method: CDP method name (e.g., "Page.navigate").
            params: Optional parameters for the command.

        Returns:
            Command result dictionary.
        """
        command = CDPCommand(method=method, params=params)
        return self.execute_command(command)


class CDPServer:
    """CDP WebSocket server for browser connections.

    This class provides a simple CDP server that can be used to
    spawn Chrome with remote debugging enabled and manage connections.

    Example::

        server = CDPServer()
        server.start()
        # Chrome should connect automatically
        client = server.get_next_client()
        if client:
            client.execute_command(CDPCommand("Page.enable"))
            server.stop()
    """

    def __init__(self, host: str = "localhost", port: int = 9222) -> None:
        self.host = host
        self.port = port
        self._server: socket.socket | None = None
        self._running = False

    def start(self) -> bool:
        """Start the CDP server.

        Returns:
            True if server started successfully.
        """
        try:
            self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server.bind((self.host, self.port))
            self._server.listen(5)
            self._running = True
            logger.info("CDP server started on %s:%d", self.host, self.port)
            return True
        except socket.error as e:
            logger.error("Failed to start CDP server: %s", e)
            return False

    def stop(self) -> None:
        """Stop the CDP server."""
        self._running = False
        if self._server:
            try:
                self._server.close()
            except Exception:
                pass
            self._server = None
        logger.info("CDP server stopped")

    def get_debugging_url(self) -> str:
        """Get the Chrome debugging URL for this server.

        Returns:
            WebSocket URL for connecting to Chrome DevTools.
        """
        return f"ws://{self.host}:{self.port}"

    def get_browser_url(self) -> str:
        """Get the Chrome remote debugging URL.

        Returns:
            HTTP URL for browser debugging API.
        """
        return f"http://{self.host}:{self.port}"


def get_cdp_debugging_url(port: int = 9222) -> str:
    """Generate Chrome debugging URL with specified port.

    Args:
        port: Debugging port number.

    Returns:
        Chrome remote debugging URL.
    """
    return f"http://localhost:{port}/json"


def parse_cdp_ws_url(ws_url: str) -> tuple[str, int]:
    """Parse WebSocket URL to get host and port.

    Args:
        ws_url: WebSocket URL (e.g., ws://localhost:9222/devtools/page/...).

    Returns:
        Tuple of (host, port).
    """
    parsed = urlparse(ws_url)
    return (parsed.hostname or "localhost", parsed.port or 9222)


def create_cdp_client_from_url(ws_url: str) -> CDPClient:
    """Create a CDP client from a WebSocket URL.

    Args:
        ws_url: WebSocket URL from /json endpoint.

    Returns:
        Configured CDPClient instance.
    """
    host, port = parse_cdp_ws_url(ws_url)
    return CDPClient(host=host, port=port)


def get_available_tabs(port: int = 9222) -> list[dict[str, Any]]:
    """Get list of available browser tabs via CDP JSON API.

    Args:
        port: Chrome debugging port.

    Returns:
        List of tab information dictionaries.
    """
    import urllib.request

    try:
        url = f"http://localhost:{port}/json/list"
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        logger.error("Failed to get tabs from CDP: %s", e)
        return []
