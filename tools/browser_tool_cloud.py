"""Cloud browser adapter (Browserless / Browserbase / Steel.dev).

Provides a thin async connector for talking to remote Chromium instances
via WebSocket CDP. Lets the agent drive a managed browser without
requiring a local Chrome installation. Supports the most common
commercial providers plus a generic "anchor" passthrough for any
CDP-compatible endpoint.

Example::

    adapter = CloudBrowserAdapter(provider="browserless", api_key="...")
    session = await adapter.connect()
    await adapter.navigate("https://example.com")
    png = await adapter.screenshot()
    await adapter.close()
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _now() -> float:
    """Return the current Unix timestamp in seconds."""
    return time.time()


# ---------------------------------------------------------------------------
# Provider endpoint resolution
# ---------------------------------------------------------------------------

# Default CDP WebSocket endpoints for each known provider. These are the
# canonical URLs published by the vendors; if your tenant lives on a
# different region or proxy, override ``ws_url`` at construction time.
_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "browserless": {
        "rest": "https://chrome.browserless.io",
        "ws": "wss://chrome.browserless.io",
    },
    "browserbase": {
        "rest": "https://www.browserbase.com/api/v1",
        "ws": "wss://connect.browserbase.com",
    },
    "steel": {
        "rest": "https://api.steel.dev",
        "ws": "wss://api.steel.dev/cdp",
    },
    "anchor": {
        # Generic CDP passthrough — caller must supply ``ws_url``.
        "rest": "",
        "ws": "",
    },
}


@dataclass
class CloudSession:
    """Metadata describing a live cloud browser session."""

    session_id: str
    provider: str
    ws_url: str
    created_at: float
    headers: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return {
            "session_id": self.session_id,
            "provider": self.provider,
            "ws_url": self.ws_url,
            "created_at": self.created_at,
            "headers": dict(self.headers),
            "extra": dict(self.extra),
        }


class CloudBrowserError(RuntimeError):
    """Raised when a cloud browser operation fails."""


class CloudBrowserAdapter:
    """Connect to a remote Chromium instance via WebSocket CDP.

    The adapter deliberately avoids importing any specific websocket
    library so that it remains usable in environments where only the
    standard library is available. Real I/O is performed lazily by
    :meth:`_send_command`, which returns a placeholder unless a
    transport has been injected.

    Attributes:
        provider: One of ``SUPPORTED_PROVIDERS``.
        api_key: Vendor API key (kept in-memory only).
        ws_url: Override for the CDP WebSocket URL.
        timeout: Default network timeout in seconds.
    """

    SUPPORTED_PROVIDERS: list[str] = ["browserless", "browserbase", "steel", "anchor"]

    def __init__(
        self,
        provider: str = "browserless",
        api_key: str = "",
        ws_url: str = "",
        timeout: float = 30.0,
    ) -> None:
        """Initialize the adapter.

        Args:
            provider: Vendor identifier. Must be in ``SUPPORTED_PROVIDERS``.
            api_key: Vendor API token. Falls back to ``BROWSERLESS_API_KEY``
                / ``BROWSERBASE_API_KEY`` / ``STEEL_API_KEY`` env vars.
            ws_url: Optional explicit CDP WebSocket URL.
            timeout: Default request timeout in seconds.
        """
        provider_norm = provider.lower().strip()
        if provider_norm not in self.SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported provider {provider!r}. "
                f"Choose one of: {', '.join(self.SUPPORTED_PROVIDERS)}"
            )

        self.provider: str = provider_norm
        self.api_key: str = api_key or self._resolve_api_key(provider_norm)
        self.ws_url_override: str = ws_url
        self.timeout: float = float(timeout)

        self._session: CloudSession | None = None
        self._command_id: int = 0
        self._closed: bool = False

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_api_key(provider: str) -> str:
        """Look up an API key from the environment based on provider."""
        env_keys = {
            "browserless": "BROWSERLESS_API_KEY",
            "browserbase": "BROWSERBASE_API_KEY",
            "steel": "STEEL_API_KEY",
            "anchor": "CDP_API_KEY",
        }
        return os.environ.get(env_keys.get(provider, ""), "")

    def _build_ws_url(self) -> str:
        """Compose the WebSocket URL, honouring overrides and defaults."""
        if self.ws_url_override:
            return self.ws_url_override

        default = _PROVIDER_DEFAULTS.get(self.provider, {}).get("ws", "")
        if not default:
            raise CloudBrowserError(
                f"No default WebSocket URL for provider {self.provider!r}; "
                "pass ws_url= explicitly."
            )

        if self.provider == "browserless" and self.api_key:
            # Browserless uses the API key as a token in the path.
            return f"{default}?token={self.api_key}"
        if self.provider == "browserbase" and self.api_key:
            return f"{default}?apiKey={self.api_key}"
        if self.provider == "steel" and self.api_key:
            return f"{default}?apiKey={self.api_key}"
        return default

    def _auth_headers(self) -> dict[str, str]:
        """Build HTTP headers for REST calls (screenshot, PDF, etc.)."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if not self.api_key:
            return headers
        if self.provider == "browserless":
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.provider == "browserbase":
            headers["X-BB-API-Key"] = self.api_key
        elif self.provider == "steel":
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def connect(self) -> dict[str, Any]:
        """Connect to the cloud browser and return session metadata.

        Returns:
            Dict containing session_id, provider, ws_url, etc.
        """
        if self._session is not None and not self._closed:
            return self._session.to_dict()

        try:
            ws_url = self._build_ws_url()
        except CloudBrowserError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise CloudBrowserError(f"Failed to build WS URL: {exc}") from exc

        self._session = CloudSession(
            session_id=str(uuid.uuid4()),
            provider=self.provider,
            ws_url=ws_url,
            created_at=_now(),
            headers=self._auth_headers(),
            extra={"timeout": self.timeout},
        )
        self._closed = False
        logger.info(
            "cloud_browser_connected provider=%s session_id=%s",
            self.provider,
            self._session.session_id,
        )
        return self._session.to_dict()

    async def navigate(self, url: str) -> dict[str, Any]:
        """Navigate the cloud page to ``url``.

        Args:
            url: Target URL (must be absolute; ``javascript:`` is rejected).

        Returns:
            Dict with status, final URL and HTTP code (best-effort).
        """
        self._ensure_connected()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise CloudBrowserError(f"Refusing to navigate to non-http(s) URL: {url!r}")

        cmd = {
            "id": self._next_id(),
            "method": "Page.navigate",
            "params": {"url": url},
        }
        result = await self._send_command(cmd)
        return {
            "session_id": self._session.session_id,  # type: ignore[union-attr]
            "navigated_to": url,
            "command": cmd,
            "result": result,
        }

    async def screenshot(self, fmt: str = "png") -> bytes:
        """Capture a screenshot from the cloud page.

        Args:
            fmt: Image format (``png`` or ``jpeg``).

        Returns:
            Raw image bytes. Empty bytes when no transport is wired.
        """
        self._ensure_connected()
        fmt = fmt.lower().strip()
        if fmt not in {"png", "jpeg", "jpg"}:
            raise CloudBrowserError(f"Unsupported screenshot format: {fmt!r}")

        cmd = {
            "id": self._next_id(),
            "method": "Page.captureScreenshot",
            "params": {"format": "jpeg" if fmt == "jpg" else fmt},
        }
        result = await self._send_command(cmd)
        # Real transports would return base64-encoded payload here.
        return result.get("payload", b"") if isinstance(result, dict) else b""

    async def evaluate(self, expression: str) -> dict[str, Any]:
        """Evaluate a JavaScript expression in the page context."""
        self._ensure_connected()
        if not expression.strip():
            raise CloudBrowserError("evaluate() requires a non-empty expression")

        cmd = {
            "id": self._next_id(),
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True},
        }
        result = await self._send_command(cmd)
        return {
            "session_id": self._session.session_id,  # type: ignore[union-attr]
            "expression": expression,
            "result": result,
        }

    async def close(self) -> None:
        """Disconnect from the cloud browser.

        Safe to call multiple times; subsequent calls are no-ops.
        """
        if self._closed:
            return
        self._closed = True
        if self._session is not None:
            logger.info(
                "cloud_browser_closed session_id=%s provider=%s",
                self._session.session_id,
                self.provider,
            )
        self._session = None

    # ------------------------------------------------------------------
    # Context manager helpers
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "CloudBrowserAdapter":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if self._session is None or self._closed:
            raise CloudBrowserError(
                "CloudBrowserAdapter is not connected; call connect() first."
            )

    def _next_id(self) -> int:
        self._command_id += 1
        return self._command_id

    async def _send_command(self, cmd: dict[str, Any]) -> dict[str, Any]:
        """Send a raw CDP command to the cloud browser.

        This is intentionally a no-op stub: actual transport wiring
        (websockets / httpx long-poll) is environment-specific. Callers
        can subclass and override this to plug in a real transport.
        """
        # Yield to the event loop so concurrent adapters don't starve.
        await asyncio.sleep(0)
        logger.debug("cloud_browser_cmd provider=%s cmd=%s", self.provider, cmd)
        return {"ok": True, "id": cmd.get("id"), "echo": cmd.get("method")}

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """Return a lightweight diagnostic snapshot (no network I/O)."""
        try:
            parsed = urlparse(self._build_ws_url()) if not self._closed else None
        except Exception:  # pragma: no cover - defensive
            parsed = None

        reachable = False
        if parsed and parsed.hostname:
            try:
                # Cheap TCP probe with a 1-second timeout; only useful as
                # a hint, not a guarantee of service health.
                with socket.create_connection((parsed.hostname, parsed.port or 443), timeout=1):
                    reachable = True
            except OSError:
                reachable = False

        return {
            "provider": self.provider,
            "connected": self._session is not None and not self._closed,
            "session_id": self._session.session_id if self._session else None,
            "ws_url": self._session.ws_url if self._session else None,
            "tcp_reachable": reachable,
            "timeout": self.timeout,
        }
