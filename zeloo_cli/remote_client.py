"""Remote gateway client for `zeloo run --remote` mode.

Connects to a remote Zeloo gateway and forwards chat completion requests
over HTTP. Useful for thin-client setups where the heavy model runs on
a VPS while the local CLI is just a UI.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RemoteConfig:
    """Configuration for remote gateway connection."""
    host: str = "localhost"
    port: int = 9113
    use_tls: bool = False
    api_key: str | None = None
    timeout: float = 60.0

    @property
    def base_url(self) -> str:
        scheme = "https" if self.use_tls else "http"
        return f"{scheme}://{self.host}:{self.port}"

    @classmethod
    def from_url(cls, url: str, api_key: str | None = None) -> "RemoteConfig":
        """Parse URL like https://zeloo.example.com:9113 or zeloo://host:port"""
        # Handle zeloo:// scheme
        if url.startswith("zeloo://"):
            url = "https://" + url[8:]
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return cls(
            host=parsed.hostname or "localhost",
            port=parsed.port or 9113,
            use_tls=parsed.scheme == "https",
            api_key=api_key,
        )


class RemoteClient:
    """HTTP client for forwarding chat completion to a remote gateway."""

    def __init__(self, config: RemoteConfig):
        self.config = config
        self._session_id: str | None = None

    def health_check(self) -> bool:
        """Check if remote gateway is reachable."""
        try:
            req = urllib.request.Request(f"{self.config.base_url}/health")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError) as e:
            logger.debug("Health check failed: %s", e)
            return False

    def list_models(self) -> list[str]:
        """List available models on the remote gateway."""
        try:
            req = urllib.request.Request(f"{self.config.base_url}/v1/models")
            self._add_auth_header(req)
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read())
                return [m["id"] for m in data.get("data", [])]
        except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
            logger.error("Failed to list models: %s", e)
            return []

    def chat_completion(
        self,
        messages: list[dict],
        model: str | None = None,
        stream: bool = False,
        **kwargs,
    ) -> dict:
        """Send a chat completion request to the remote gateway."""
        payload = {
            "model": model or "zeloo-default",
            "messages": messages,
            "stream": stream,
            **kwargs,
        }
        req = urllib.request.Request(
            f"{self.config.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        self._add_auth_header(req)
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Remote gateway error {e.code}: {error_body}") from e

    def _add_auth_header(self, req: urllib.request.Request) -> None:
        if self.config.api_key:
            req.add_header("Authorization", f"Bearer {self.config.api_key}")
