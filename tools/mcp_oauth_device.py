"""MCP OAuth Device Code Flow (RFC 8628).

For MCP servers that don't have a web browser (CLI/headless scenarios),
the device authorization grant lets a user complete consent on a
secondary device (phone, laptop). The agent prints a short code and a
URL; the user visits the URL, enters the code, and approves the
requested scopes.

This module reuses :class:`tools.mcp_oauth.MCPOAuthClient` for the
HTTP plumbing but keeps the polling logic here so callers can opt out
of automatic prompting (e.g. for embedded use inside a TUI).
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

from tools.mcp_oauth import OAuthError

logger = logging.getLogger(__name__)


@dataclass
class DeviceCodeResponse:
    """The user-facing challenge returned by the AS.

    Mirrors RFC 8628 §3.2 field names.
    """

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None  # convenience link with code embedded
    expires_in: int
    interval: int

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> DeviceCodeResponse:
        """Parse a raw AS response, raising on missing required fields."""
        try:
            return cls(
                device_code=payload["device_code"],
                user_code=payload["user_code"],
                verification_uri=payload["verification_uri"],
                verification_uri_complete=payload.get(
                    "verification_uri_complete"
                ),
                expires_in=int(payload.get("expires_in", 600)),
                interval=int(payload.get("interval", 5)),
            )
        except KeyError as exc:
            raise OAuthError(
                f"Device authorization response missing field: {exc}",
                response_body=str(payload)[:512],
            ) from exc


class DeviceCodeClient:
    """OAuth 2.0 Device Authorization Grant (RFC 8628).

    Lifecycle::

        client = DeviceCodeClient(device_auth_endpoint, token_endpoint, client_id)
        challenge = await client.request_device_code(scope="read")
        print(f"Visit {challenge.verification_uri} and enter {challenge.user_code}")
        token = await client.poll_for_token(challenge.device_code, challenge.interval)
        # or, in one shot:
        token = await client.run(scope="read")

    The class never blocks the event loop: ``poll_for_token`` uses
    ``asyncio.sleep`` between attempts.
    """

    _GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

    def __init__(
        self,
        device_authorization_endpoint: str,
        token_endpoint: str,
        client_id: str,
        client_secret: str | None = None,
        audience: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.device_authorization_endpoint = device_authorization_endpoint
        self.token_endpoint = token_endpoint
        self.client_id = client_id
        self.client_secret = client_secret
        self.audience = audience
        self._timeout = timeout
        # Same ownership semantics as MCPOAuthClient — we never mutate
        # a caller-provided httpx client.
        self._external_client = http_client
        self._owns_client = http_client is None

    # ── Context manager support ──────────────────────────────────────

    async def __aenter__(self) -> DeviceCodeClient:
        if self._external_client is None:
            self._external_client = httpx.AsyncClient(timeout=self._timeout)
            self._owns_client = True
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._external_client is not None:
            await self._external_client.aclose()
            self._external_client = None

    # ── Step 1: request device code ──────────────────────────────────

    async def request_device_code(self, scope: str = "") -> DeviceCodeResponse:
        """Request a device code from the authorization server.

        Returns a :class:`DeviceCodeResponse` describing what the user
        must do (visit URL, enter code) and the polling parameters.
        """
        if not self.device_authorization_endpoint:
            raise OAuthError("device_authorization_endpoint not configured")
        payload: dict[str, str] = {"client_id": self.client_id}
        if scope:
            payload["scope"] = scope
        if self.audience:
            payload["audience"] = self.audience
        # Some confidential clients include the secret here too; it's
        # harmless for public clients (the AS will ignore it).
        if self.client_secret:
            payload["client_secret"] = self.client_secret

        owns = self._external_client is None
        client = self._external_client or httpx.AsyncClient(timeout=self._timeout)
        try:
            try:
                resp = await client.post(
                    self.device_authorization_endpoint,
                    data=payload,
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise OAuthError(
                    f"Device authorization request failed: {exc}"
                ) from exc
            try:
                body = resp.json()
            except ValueError as exc:
                raise OAuthError(
                    f"Device authorization returned non-JSON body: {exc}",
                    status_code=resp.status_code,
                    response_body=resp.text[:512],
                ) from exc
            if resp.status_code >= 400 or "error" in body:
                raise OAuthError(
                    body.get("error_description") or body.get("error")
                    or f"Device authorization failed: HTTP {resp.status_code}",
                    error_code=body.get("error"),
                    status_code=resp.status_code,
                    response_body=resp.text[:512],
                )
            return DeviceCodeResponse.from_payload(body)
        finally:
            if owns and isinstance(client, httpx.AsyncClient):
                await client.aclose()

    # ── Step 2: poll for token ───────────────────────────────────────

    async def poll_for_token(
        self,
        device_code: str,
        interval: int = 5,
        expires_in: int = 600,
        prompt: bool = True,
        output=sys.stdout,
    ) -> dict[str, Any]:
        """Poll the token endpoint until the user authenticates.

        Args:
            device_code: The opaque token from :meth:`request_device_code`.
            interval: Minimum seconds between polls. The AS may extend
                this via ``slow_down`` (RFC 8628 §3.5).
            expires_in: How long to wait before giving up. The AS sets
                this in the device-code response.
            prompt: When ``True`` (default), print a waiting message on
                the first poll so the user knows something is happening.
            output: File-like object to write user-facing prompts to.
                Defaults to stdout; tests can pass an ``io.StringIO``.

        Returns:
            The parsed token response (contains ``access_token`` and
            optionally ``refresh_token``).

        Raises:
            OAuthError: On any non-recoverable AS error.
            TimeoutError: If the user does not authorize in time.
        """
        if not self.token_endpoint:
            raise OAuthError("token_endpoint not configured")
        # Floor the interval at 1s — RFC 8628 §3.5 specifies a minimum
        # of 5s but allows the AS to relax that, and we should never
        # hammer the endpoint.
        current_interval = max(1, int(interval))
        deadline = time.monotonic() + int(expires_in)
        first_poll = True
        owns = self._external_client is None
        client = self._external_client or httpx.AsyncClient(timeout=self._timeout)
        try:
            while time.monotonic() < deadline:
                if first_poll and prompt:
                    self._print_waiting_message(output)
                    first_poll = False
                payload: dict[str, str] = {
                    "grant_type": self._GRANT_TYPE,
                    "device_code": device_code,
                    "client_id": self.client_id,
                }
                if self.client_secret:
                    payload["client_secret"] = self.client_secret
                try:
                    resp = await client.post(
                        self.token_endpoint,
                        data=payload,
                        headers={"Accept": "application/json"},
                    )
                except httpx.HTTPError as exc:
                    # Transient network errors — retry after interval.
                    logger.warning("Device-flow poll network error: %s", exc)
                    await asyncio.sleep(current_interval)
                    continue
                try:
                    body = resp.json()
                except ValueError:
                    body = {}
                # Recoverable errors per RFC 8628 §3.5.
                if "error" in body:
                    err = body["error"]
                    if err == "authorization_pending":
                        await asyncio.sleep(current_interval)
                        continue
                    if err == "slow_down":
                        current_interval += 5
                        await asyncio.sleep(current_interval)
                        continue
                    if err == "expired_token":
                        raise TimeoutError(
                            "Device code expired before user completed "
                            "authorization"
                        )
                    # Anything else is a real failure.
                    raise OAuthError(
                        body.get("error_description") or err,
                        error_code=err,
                        status_code=resp.status_code,
                        response_body=resp.text[:512],
                    )
                if resp.status_code >= 400:
                    raise OAuthError(
                        f"Token endpoint returned HTTP {resp.status_code}",
                        status_code=resp.status_code,
                        response_body=resp.text[:512],
                    )
                if "access_token" not in body:
                    raise OAuthError(
                        "Device-flow token response missing 'access_token'",
                        status_code=resp.status_code,
                        response_body=resp.text[:512],
                    )
                return body
            raise TimeoutError(
                f"Device-flow timed out after {expires_in}s; user did not "
                "complete authorization in time"
            )
        finally:
            if owns and isinstance(client, httpx.AsyncClient):
                await client.aclose()

    # ── Convenience: full flow ───────────────────────────────────────

    async def run(self, scope: str = "", output=sys.stdout) -> dict[str, Any]:
        """Run the complete device code flow with user prompts.

        This is a convenience wrapper for CLI / interactive use:

        1. Request a device code.
        2. Print the URL + user code to ``output``.
        3. Poll until the user completes authorization (or timeout).

        For TUI integration prefer calling :meth:`request_device_code`
        and :meth:`poll_for_token` separately so you can render the
        prompt in your own widgets.
        """
        challenge = await self.request_device_code(scope=scope)
        self._print_challenge(challenge, output)
        return await self.poll_for_token(
            device_code=challenge.device_code,
            interval=challenge.interval,
            expires_in=challenge.expires_in,
            prompt=False,  # already printed by _print_challenge
            output=output,
        )

    # ── Output helpers ───────────────────────────────────────────────

    @staticmethod
    def _print_challenge(
        challenge: DeviceCodeResponse, output=sys.stdout
    ) -> None:
        """Display the URL + code the user must visit."""
        url = challenge.verification_uri_complete or challenge.verification_uri
        print(f"\nTo authorize this device, visit:\n  {url}", file=output)
        print(f"and enter the code: {challenge.user_code}\n", file=output)
        print(
            f"Waiting for authorization (expires in {challenge.expires_in}s)…",
            file=output,
        )

    @staticmethod
    def _print_waiting_message(output=sys.stdout) -> None:
        print(".", file=output, end="", flush=True)


__all__ = [
    "DeviceCodeClient",
    "DeviceCodeResponse",
]


async def _selftest() -> None:  # pragma: no cover - manual smoke test
    """Verify the dataclass round-trips a typical AS response."""
    payload = {
        "device_code": "abc",
        "user_code": "WDDD-BFRT",
        "verification_uri": "https://example.com/activate",
        "verification_uri_complete": "https://example.com/activate?code=WDDD-BFRT",
        "expires_in": 600,
        "interval": 5,
    }
    challenge = DeviceCodeResponse.from_payload(payload)
    assert challenge.user_code == "WDDD-BFRT"
    assert challenge.interval == 5
    print("device-flow selftest OK:", challenge.user_code)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_selftest())
