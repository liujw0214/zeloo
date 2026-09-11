"""Home Assistant integration for smart home control.

Connects to Home Assistant via REST API.

Configuration keys:
- url (str, required): Home Assistant URL (e.g., http://homeassistant:8123)
- token (str, required): Long-lived access token
- timeout (float, optional): Request timeout in seconds, defaults to 30
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from tools.integrations.base import (
    AuthError,
    BaseIntegration,
    IntegrationError,
    NotFoundError,
    RateLimitError,
    ReceiveCallback,
    safe_call,
    sleep_for,
)
from tools.integrations.registry import register_integration

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3


@register_integration("homeassistant")
class HomeAssistantIntegration(BaseIntegration):
    """Home Assistant REST API client."""

    platform_name = "homeassistant"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.url: str = self._require_config("url").rstrip("/")
        self.token: str = self._require_config("token")
        self.timeout: float = float(config.get("timeout", DEFAULT_TIMEOUT))
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None
        self._event_callback: ReceiveCallback | None = None

    def _require_config(self, key: str) -> str:
        value = self.config.get(key)
        if not value:
            raise AuthError(f"Missing required config key: {key}")
        return str(value)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.url,
                timeout=self.timeout,
                headers=self.headers,
            )
        return self._client

    async def close(self) -> None:
        await super().close()
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = await self._get_client()
        attempts = MAX_RETRIES + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await client.request(
                    method,
                    path,
                    json=json_body,
                    params=params,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "HomeAssistant HTTP error on %s (attempt %s/%s): %s",
                    path,
                    attempt,
                    attempts,
                    exc,
                )
                await sleep_for(min(2 ** attempt, 10))
                continue

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 1.0))
                logger.info("HomeAssistant rate-limited, sleeping %.2fs", retry_after)
                await sleep_for(retry_after)
                if attempt < attempts:
                    continue
                raise RateLimitError(
                    f"HomeAssistant rate limit exceeded for {path}",
                    retry_after=retry_after,
                )

            if response.status_code == 401:
                raise AuthError(
                    f"HomeAssistant auth failure: {response.text}"
                )
            if response.status_code == 404:
                raise NotFoundError(f"HomeAssistant resource missing: {path}")
            if 500 <= response.status_code < 600:
                last_error = IntegrationError(
                    f"HomeAssistant server error {response.status_code}"
                )
                await sleep_for(min(2 ** attempt, 10))
                continue

            try:
                payload = response.json()
            except Exception as exc:
                raise IntegrationError(f"Invalid HomeAssistant response: {exc}") from exc

            return payload

        assert last_error is not None
        raise IntegrationError(
            f"HomeAssistant request failed after retries: {last_error}"
        )

    async def send_message(
        self,
        channel: str,
        content: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a notification via Home Assistant.

        Args:
            channel: Notification service (e.g., "notify.notify")
            content: Notification message
        """
        return await self.call_service(
            domain="notify",
            service=channel.split(".")[-1] if "." in channel else "notify",
            data={"message": content},
        )

    async def get_states(
        self,
        entity_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get states of all entities or filtered by entity_ids."""

        async def _do() -> list[dict[str, Any]]:
            params: dict[str, Any] | None = None
            if entity_ids:
                params = {"entity_id": ",".join(entity_ids)}
            result = await self._request("GET", "/api/states", params=params)
            if isinstance(result, list):
                return result
            return [result]

        return await safe_call(_do)

    async def get_state(self, entity_id: str) -> dict[str, Any]:
        """Get state of a single entity."""

        async def _do() -> dict[str, Any]:
            result = await self._request("GET", f"/api/states/{entity_id}")
            return {"ok": True, "state": result}

        return await safe_call(_do)

    async def call_service(
        self,
        domain: str,
        service: str,
        data: dict[str, Any] | None = None,
        entity_id: str | None = None,
    ) -> dict[str, Any]:
        """Call a Home Assistant service.

        Args:
            domain: Service domain (e.g., "light", "switch", "notify")
            service: Service name (e.g., "turn_on", "notify")
            data: Optional service data payload
            entity_id: Optional entity to target
        """

        async def _do() -> dict[str, Any]:
            payload: dict[str, Any] = {}
            if data:
                payload.update(data)
            if entity_id:
                payload["entity_id"] = entity_id
            result = await self._request(
                "POST",
                f"/api/services/{domain}/{service}",
                json_body=payload,
            )
            return {"ok": True, "context": result}

        return await safe_call(_do)

    async def fire_event(
        self,
        event_type: str,
        event_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Fire a custom Home Assistant event."""

        async def _do() -> dict[str, Any]:
            result = await self._request(
                "POST",
                f"/api/events/{event_type}",
                json_body=event_data,
            )
            return {"ok": True, "event": result}

        return await safe_call(_do)

    async def get_config(self) -> dict[str, Any]:
        """Get Home Assistant configuration."""

        async def _do() -> dict[str, Any]:
            result = await self._request("GET", "/api/config")
            return {"ok": True, "config": result}

        return await safe_call(_do)

    async def get_services(self) -> dict[str, Any]:
        """Get available services in Home Assistant."""

        async def _do() -> dict[str, Any]:
            result = await self._request("GET", "/api/services")
            return {"ok": True, "services": result}

        return await safe_call(_do)

    async def render_template(self, template: str) -> str:
        """Render a Jinja2 template and return the result."""

        async def _do() -> str:
            result = await self._request(
                "POST",
                "/api/template",
                json_body={"template": template},
            )
            return str(result.get("result", ""))

        response = await safe_call(_do)
        if isinstance(response, dict) and not response.get("ok"):
            return f"Template error: {response.get('error', 'unknown')}"
        return response if isinstance(response, str) else str(response)

    async def get_history(
        self,
        entity_id: str,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get history for an entity.

        Args:
            entity_id: Entity ID to get history for
            start_time: ISO format start time
            end_time: ISO format end time
        """

        async def _do() -> list[dict[str, Any]]:
            params: dict[str, Any] = {"filter_entity_id": entity_id}
            if start_time:
                params["start_time"] = start_time
            if end_time:
                params["end_time"] = end_time
            result = await self._request("GET", "/api/history", params=params)
            if isinstance(result, list):
                return result
            return []

        return await safe_call(_do)

    def ws_url(self) -> str:
        """Return WebSocket URL for real-time connection."""
        return self.url.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"

    async def list_channels(self) -> list[dict[str, Any]]:
        """List entity groups as pseudo-channels."""
        states = await self.get_states()
        domains: dict[str, list[str]] = {}
        for state in states:
            entity_id = state.get("entity_id", "")
            domain = entity_id.split(".")[0] if "." in entity_id else "unknown"
            if domain not in domains:
                domains[domain] = []
            domains[domain].append(entity_id)
        return [{"domain": d, "entities": e} for d, e in domains.items()]

    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Get user information (limited info via REST API)."""
        async def _do() -> dict[str, Any]:
            result = await self._request("GET", "/api/config")
            return {
                "ok": True,
                "user": {
                    "name": result.get("name", ""),
                    "location": result.get("latitude", ""),
                },
            }
        return await safe_call(_do)

    async def receive_messages(
        self,
        callback: ReceiveCallback,
        **kwargs: Any,
    ) -> None:
        """Store callback for event stream (requires WebSocket for real events)."""
        self._event_callback = callback
        logger.info(
            "HomeAssistant receive_messages registered. "
            "Use ws_url() for WebSocket connection."
        )
