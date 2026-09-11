"""Provider client lifecycle management — connection pools, health checks, graceful shutdown."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ClientHealth:
    """Health status of a provider client."""

    provider: str
    healthy: bool
    last_check: float
    error: str | None = None
    request_count: int = 0
    error_count: int = 0


class ClientLifecycle:
    """Provider client lifecycle manager.

    Manages a pool of LLM provider HTTP clients with:
    - Lazy connection acquisition
    - Health monitoring
    - Graceful shutdown
    - Request counting
    """

    def __init__(
        self,
        provider: Any,
        max_idle_time: float = 300.0,
        health_check_interval: float = 60.0,
    ):
        self.provider = provider
        self.max_idle_time = max_idle_time
        self.health_check_interval = health_check_interval

        self._clients: dict[str, Any] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._health: dict[str, ClientHealth] = {}
        self._last_used: dict[str, float] = {}
        self._monitor_thread: threading.Thread | None = None
        self._shutdown = threading.Event()

        self._provider_meta: dict[str, str] = {}
        for name in self._discover_providers():
            self._locks[name] = threading.Lock()
            self._health[name] = ClientHealth(
                provider=name,
                healthy=True,
                last_check=time.time(),
            )

    def _discover_providers(self) -> list[str]:
        """Discover available provider names from the provider router."""
        if hasattr(self.provider, "providers"):
            return list(self.provider.providers.keys())
        return [getattr(self.provider, "primary", "openai")]

    def acquire(self, provider_name: str) -> Any:
        """Acquire a client for the given provider.

        Creates a new client if one does not exist in the pool.

        Args:
            provider_name: Name of the provider.

        Returns:
            HTTP client instance.
        """
        if provider_name not in self._clients:
            with self._locks.get(provider_name):
                if provider_name not in self._clients:
                    client = self._create_client(provider_name)
                    self._clients[provider_name] = client
                    logger.debug("Created new client for provider: %s", provider_name)

        self._last_used[provider_name] = time.time()
        health = self._health.get(provider_name)
        if health:
            health.request_count += 1

        return self._clients[provider_name]

    def release(self, provider_name: str) -> None:
        """Release a client back to the pool (no-op in current design).

        Clients are kept alive for reuse. Callers should not hold references
        to the client between requests.
        """
        self._last_used[provider_name] = time.time()

    def health_check(self) -> dict[str, ClientHealth]:
        """Check health of all active provider clients.

        Returns:
            Dict mapping provider name to ClientHealth status.
        """
        now = time.time()
        results: dict[str, ClientHealth] = {}

        for name in list(self._clients.keys()):
            health = self._health.get(name)
            if not health:
                health = ClientHealth(provider=name, healthy=True, last_check=now)
                self._health[name] = health

            client = self._clients.get(name)
            if client:
                try:
                    is_healthy = self._ping_client(client, name)
                    health.healthy = is_healthy
                    health.last_check = now
                    health.error = None
                except Exception as e:
                    health.healthy = False
                    health.last_check = now
                    health.error = str(e)
                    logger.warning("Health check failed for %s: %s", name, e)

            results[name] = health

        return results

    def start_monitoring(self) -> None:
        """Start background health monitoring thread."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        self._shutdown.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="client-lifecycle-monitor",
            daemon=True,
        )
        self._monitor_thread.start()
        logger.info("Client lifecycle monitoring started")

    def stop_monitoring(self) -> None:
        """Stop background health monitoring."""
        self._shutdown.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
            self._monitor_thread = None
        logger.info("Client lifecycle monitoring stopped")

    def graceful_shutdown(self) -> None:
        """Gracefully shut down all client connections.

        Stops monitoring, closes all HTTP sessions, and cleans up resources.
        """
        logger.info("Initiating graceful shutdown of all clients")
        self.stop_monitoring()

        for name, client in list(self._clients.items()):
            try:
                self._close_client(client, name)
                logger.debug("Closed client for provider: %s", name)
            except Exception as e:
                logger.warning("Error closing client for %s: %s", name, e)

        self._clients.clear()
        self._health.clear()
        self._last_used.clear()

    def get_stats(self) -> dict[str, Any]:
        """Return usage statistics for all clients.

        Returns:
            Dict with request counts, error rates, and health status.
        """
        stats = {}
        for name, health in self._health.items():
            error_rate = (
                health.error_count / max(health.request_count, 1)
            )
            stats[name] = {
                "healthy": health.healthy,
                "request_count": health.request_count,
                "error_count": health.error_count,
                "error_rate": round(error_rate, 4),
                "last_check": health.last_check,
                "idle_seconds": round(
                    time.time() - self._last_used.get(name, time.time()), 1
                ),
            }
        return stats

    def _create_client(self, provider_name: str) -> Any:
        """Create a new HTTP client for the provider."""
        try:
            import httpx

            client = httpx.Client(
                timeout=httpx.Timeout(60.0, connect=10.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                follow_redirects=True,
            )
            return client
        except ImportError:
            logger.warning("httpx not available, using stub client")
            return _StubClient(provider_name)

    def _close_client(self, client: Any, name: str) -> None:
        """Close a client connection."""
        if hasattr(client, "close"):
            client.close()
        elif hasattr(client, "aclose"):
            import asyncio
            asyncio.get_event_loop().run_until_complete(client.aclose())

    def _ping_client(self, client: Any, name: str) -> bool:
        """Ping a client to check liveness."""
        try:
            if hasattr(client, "get"):
                resp = client.get(
                    self._get_health_url(name),
                    timeout=5.0,
                )
                return resp.status_code < 500
        except Exception:
            return False
        return True

    def _get_health_url(self, name: str) -> str:
        """Get the health check URL for a provider."""
        from agent.provider_router import _KNOWN_PROVIDERS

        base = _KNOWN_PROVIDERS.get(name, "https://api.openai.com/v1")
        if base.endswith("/"):
            base = base[:-1]
        return f"{base}/models"

    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while not self._shutdown.is_set():
            self.health_check()
            self._evict_idle_clients()
            self._shutdown.wait(self.health_check_interval)

    def _evict_idle_clients(self) -> None:
        """Close clients that have been idle too long."""
        now = time.time()
        for name, last_used in list(self._last_used.items()):
            idle = now - last_used
            if idle > self.max_idle_time:
                if name in self._clients:
                    logger.debug("Evicting idle client: %s (idle=%.0fs)", name, idle)
                    try:
                        self._close_client(self._clients[name], name)
                        del self._clients[name]
                    except Exception as e:
                        logger.warning("Error evicting client %s: %s", name, e)


class _StubClient:
    """Fallback stub client when httpx is unavailable."""

    def __init__(self, name: str):
        self.name = name

    def get(self, url: str, **kwargs: Any) -> Any:
        class _Response:
            status_code = 200

        return _Response()
