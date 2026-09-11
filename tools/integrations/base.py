"""Platform integration base classes.

This module defines the abstract base class and supporting helpers that all
platform integrations (Discord, Slack, Feishu, Telegram, ...) must implement.

The base class is intentionally minimal — it captures the surface that the
Zeloo runtime expects from every integration while leaving room for each
platform to implement its own authentication, rate-limit handling and
real-time receive mechanism.

Conventions
-----------
- All HTTP calls must be ``async`` and use ``httpx.AsyncClient``.
- Subclasses should expose a ``platform_name`` (lower-case identifier).
- Errors raised from integrations must be caught at the call site and
  returned as ``{"ok": False, "error": str(...)}`` payloads whenever
  possible (see ``safe_call``).
"""

from __future__ import annotations

import abc
import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

# Generic type for the receive-loop callback.
ReceiveCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class IntegrationError(Exception):
    """Base exception raised by integrations.

    The ``code`` attribute carries a stable identifier that callers can
    branch on (e.g. ``"rate_limited"``, ``"unauthorized"``).
    """

    def __init__(self, message: str, *, code: str = "integration_error") -> None:
        super().__init__(message)
        self.code = code


class RateLimitError(IntegrationError):
    """Raised when the upstream platform reports a 429 / rate limit.

    ``retry_after`` is expressed in seconds.
    """

    def __init__(self, message: str, retry_after: float = 1.0) -> None:
        super().__init__(message, code="rate_limited")
        self.retry_after = retry_after


class AuthError(IntegrationError):
    """Raised when credentials are missing or invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="unauthorized")


class NotFoundError(IntegrationError):
    """Raised when the requested resource does not exist."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="not_found")


class BaseIntegration(abc.ABC):
    """Abstract base class for platform integrations.

    Subclasses must override :meth:`send_message`, :meth:`list_channels`,
    :meth:`get_user_info` and :meth:`receive_messages`. They may also
    override :meth:`close` to release HTTP resources.

    Attributes
    ----------
    platform_name:
        Lower-case identifier used by the registry.
    config:
        Raw configuration dictionary supplied at construction time.
    """

    platform_name: str = ""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._closed: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def close(self) -> None:
        """Release any resources held by the integration.

        The default implementation is a no-op. Subclasses that open
        long-lived HTTP clients or websocket connections should override
        this method and make it idempotent.
        """
        self._closed = True

    @property
    def is_closed(self) -> bool:
        """Return ``True`` after :meth:`close` has been called."""
        return self._closed

    # ------------------------------------------------------------------
    # Required API surface
    # ------------------------------------------------------------------
    @abc.abstractmethod
    async def send_message(
        self,
        channel: str,
        content: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a message to ``channel``.

        Implementations must return a dict with at least the keys ``ok``
        (bool) and either ``message_id`` / ``ts`` on success or
        ``error`` on failure.
        """

    @abc.abstractmethod
    async def list_channels(self) -> list[dict[str, Any]]:
        """Return a list of channel descriptors.

        The exact shape is platform-specific but every item should
        include at least ``id`` and ``name``.
        """

    @abc.abstractmethod
    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Return basic profile information for ``user_id``."""

    @abc.abstractmethod
    async def receive_messages(
        self,
        callback: ReceiveCallback,
        **kwargs: Any,
    ) -> None:
        """Receive messages in real time and dispatch them to ``callback``.

        Implementations may use websockets, polling, or webhooks
        depending on the platform's capabilities.
        """


# ---------------------------------------------------------------------------
# Helpers shared across integrations
# ---------------------------------------------------------------------------
async def safe_call(
    coro_factory: Callable[[], Coroutine[Any, Any, Any]],
    *,
    default: Any = None,
) -> Any:
    """Run ``coro_factory`` and convert exceptions into a dict payload.

    The returned object on failure has the shape::

        {"ok": False, "error": "<message>", "code": "<code>"}

    This helper is used by subclasses to keep their public API
    exception-free while still surfacing meaningful error information.
    """

    try:
        result = await coro_factory()
        return result
    except asyncio.CancelledError:
        raise
    except IntegrationError as exc:
        logger.warning("Integration error (%s): %s", exc.code, exc)
        return {"ok": False, "error": str(exc), "code": exc.code}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected integration error: %s", exc)
        return {"ok": False, "error": str(exc), "code": "unexpected"}


def require_config(config: dict[str, Any], key: str) -> Any:
    """Return ``config[key]`` or raise :class:`AuthError`.

    Centralises the credential-checking boilerplate so subclasses can
    stay short.
    """

    if key not in config or config[key] in (None, ""):
        raise AuthError(f"Missing required config key: {key}")
    return config[key]


async def sleep_for(seconds: float) -> None:
    """Async-friendly sleep wrapper that survives cancellation cleanly."""

    if seconds <= 0:
        return
    await asyncio.sleep(seconds)