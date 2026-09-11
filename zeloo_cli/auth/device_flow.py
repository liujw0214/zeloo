"""RFC 8628 OAuth 2.0 Device Authorization Grant.

The device flow is well suited to CLI tools and headless services
because the user authenticates on a separate device (typically a
phone) by visiting a short URL and entering a short user code.
This module provides a reusable client so every provider that
supports the grant (GitHub, Google, OpenAI Codex, …) can share the
same polling / cancellation logic.

Reference: https://www.rfc-editor.org/rfc/rfc8628
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from zeloo_cli.auth.base import AuthError, TokenResponse

logger = logging.getLogger(__name__)


@dataclass
class DeviceFlowResult:
    """The initial response from a device-authorization endpoint."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str = ""
    expires_in: int = 600
    interval: int = 5
    extras: dict[str, Any] = field(default_factory=dict)

    def prompt(self) -> str:
        """Return a multi-line human-readable prompt."""
        uri = self.verification_uri_complete or self.verification_uri
        return (
            f"To authorize this device, open:\n  {uri}\n"
            f"and enter the code:\n  {self.user_code}\n"
            f"(code expires in {self.expires_in} seconds)"
        )


class DeviceFlowError(AuthError):
    """Raised when the device flow fails for a provider-specific reason."""


class DeviceFlowClient:
    """Reusable RFC 8628 device-flow client.

    Instances are stateless aside from the provider endpoints passed
    at construction time.  Use one instance per provider; share
    across multiple flows as needed.

    Example
    -------

    .. code-block:: python

        client = DeviceFlowClient(
            device_authorization_url="https://github.com/login/device/code",
            token_url="https://github.com/login/oauth/access_token",
            client_id="...,
        )
        flow = await client.request_device_code(scope="repo read:user")
        print(flow.prompt())
        token = await client.poll_for_token(flow)
    """

    DEFAULT_TIMEOUT: int = 600
    """Total polling budget in seconds (mirrors GitHub's default)."""

    def __init__(
        self,
        device_authorization_url: str,
        token_url: str,
        client_id: str,
        audience: str | None = None,
        default_scope: str = "",
    ) -> None:
        self.device_authorization_url = device_authorization_url
        self.token_url = token_url
        self.client_id = client_id
        self.audience = audience
        self.default_scope = default_scope

    # ── Step 1: request a device code ────────────────────────────

    async def request_device_code(
        self,
        scope: str | None = None,
        **extra: Any,
    ) -> DeviceFlowResult:
        """POST to the device-authorization endpoint.

        Args:
            scope: Space-separated scopes.  Defaults to the client's
                ``default_scope`` if not provided.
            **extra: Additional form fields merged into the request
                (e.g. ``audience`` for Auth0-backed providers).

        Returns:
            A :class:`DeviceFlowResult` ready for user display.

        Raises:
            DeviceFlowError: If the endpoint rejects the request.
        """
        import httpx

        payload: dict[str, Any] = {"client_id": self.client_id}
        chosen_scope = scope if scope is not None else self.default_scope
        if chosen_scope:
            payload["scope"] = chosen_scope
        if self.audience:
            payload["audience"] = self.audience
        payload.update(extra)

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(
                    self.device_authorization_url,
                    data=payload,
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise DeviceFlowError(
                    f"Network error contacting {self.device_authorization_url}: {exc}"
                ) from exc

        if resp.status_code >= 400:
            raise DeviceFlowError(
                f"Device authorization failed: HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise DeviceFlowError(
                "Provider returned non-JSON from device authorization endpoint"
            ) from exc

        try:
            return DeviceFlowResult(
                device_code=data["device_code"],
                user_code=data["user_code"],
                verification_uri=data["verification_uri"],
                verification_uri_complete=data.get("verification_uri_complete", ""),
                expires_in=int(data.get("expires_in", self.DEFAULT_TIMEOUT)),
                interval=int(data.get("interval", 5)),
                extras={
                    k: v
                    for k, v in data.items()
                    if k
                    not in {
                        "device_code",
                        "user_code",
                        "verification_uri",
                        "verification_uri_complete",
                        "expires_in",
                        "interval",
                    }
                },
            )
        except KeyError as exc:
            raise DeviceFlowError(
                f"Provider response missing required field: {exc.args[0]}"
            ) from exc

    # ── Step 2: poll the token endpoint ──────────────────────────

    async def poll_for_token(
        self,
        flow: DeviceFlowResult,
        timeout: int | None = None,
        scope: str | None = None,
    ) -> TokenResponse:
        """Poll the token endpoint until the user authorises or times out.

        Handles the standard ``authorization_pending`` and
        ``slow_down`` error responses per RFC 8628 §3.5.

        Args:
            flow: The :class:`DeviceFlowResult` returned by
                :meth:`request_device_code`.
            timeout: Total polling budget.  Defaults to the flow's
                ``expires_in`` value (capped at ``DEFAULT_TIMEOUT``).
            scope: Optional scope to echo back to the token endpoint.

        Returns:
            A populated :class:`TokenResponse`.

        Raises:
            DeviceFlowError: On terminal errors (``access_denied``,
                ``expired_token``) or transport failures.
            asyncio.TimeoutError: If the user does not authorise
                within ``timeout`` seconds.
        """
        import httpx

        budget = timeout if timeout is not None else min(self.DEFAULT_TIMEOUT, flow.expires_in)
        deadline = time.monotonic() + budget
        interval = max(flow.interval, 1)

        while True:
            now = time.monotonic()
            if now >= deadline:
                raise asyncio.TimeoutError(
                    f"Device flow timed out after {budget}s"
                )

            payload: dict[str, Any] = {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": flow.device_code,
                "client_id": self.client_id,
            }
            if scope or self.default_scope:
                payload["scope"] = scope or self.default_scope

            async with httpx.AsyncClient(timeout=30.0) as client:
                try:
                    resp = await client.post(
                        self.token_url,
                        data=payload,
                        headers={"Accept": "application/json"},
                    )
                except httpx.HTTPError as exc:
                    raise DeviceFlowError(
                        f"Network error contacting {self.token_url}: {exc}"
                    ) from exc

            # RFC 8628 §3.5: slow_down / authorization_pending come
            # back as HTTP 400 with the error in the body.
            if resp.status_code == 400:
                try:
                    err = resp.json().get("error", "")
                except ValueError:
                    err = ""
                if err == "authorization_pending":
                    await asyncio.sleep(interval)
                    continue
                if err == "slow_down":
                    interval += 5
                    await asyncio.sleep(interval)
                    continue
                if err in {"access_denied", "expired_token"}:
                    raise DeviceFlowError(f"Device flow ended: {err}")
                raise DeviceFlowError(
                    f"Device flow token request failed: HTTP {resp.status_code}: {resp.text[:200]}"
                )

            if resp.status_code >= 400:
                raise DeviceFlowError(
                    f"Device flow token request failed: HTTP {resp.status_code}: {resp.text[:200]}"
                )
            try:
                data = resp.json()
            except ValueError as exc:
                raise DeviceFlowError(
                    "Provider returned non-JSON from token endpoint"
                ) from exc

            if "access_token" not in data:
                raise DeviceFlowError(
                    f"Token endpoint response missing access_token: {data}"
                )

            expires_in = data.get("expires_in")
            return TokenResponse(
                access_token=data["access_token"],
                token_type=data.get("token_type", "Bearer"),
                refresh_token=data.get("refresh_token"),
                expires_in=int(expires_in) if expires_in is not None else None,
                scope=data.get("scope", scope or self.default_scope or ""),
                extras={
                    k: v
                    for k, v in data.items()
                    if k
                    not in {
                        "access_token",
                        "token_type",
                        "refresh_token",
                        "expires_in",
                        "scope",
                    }
                },
            )

    # ── Convenience: full flow ──────────────────────────────────

    async def run(
        self,
        scope: str | None = None,
        on_prompt: Any | None = None,
        timeout: int | None = None,
    ) -> TokenResponse:
        """Run the full device-flow end-to-end.

        Args:
            scope: Optional scope override.
            on_prompt: Optional callable invoked with the
                :class:`DeviceFlowResult` so callers can print /
                render the user prompt.  Defaults to ``print``.
            timeout: Total polling budget.

        Returns:
            The resulting :class:`TokenResponse`.
        """
        flow = await self.request_device_code(scope=scope)
        prompt = on_prompt or (lambda f: print(f.prompt()))
        prompt(flow)
        return await self.poll_for_token(flow, timeout=timeout, scope=scope)


__all__ = ["DeviceFlowClient", "DeviceFlowError", "DeviceFlowResult"]
