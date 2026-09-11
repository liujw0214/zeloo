"""Vercel sandbox terminal backend — executes commands via Vercel Functions runtime."""

from __future__ import annotations

import json
import os
import urllib.request

from .base import CommandResult, TerminalBackend


class VercelSandboxTerminalBackend(TerminalBackend):
    """Execute commands via Vercel sandbox runtime.

    Useful for serverless execution of Python/Node scripts.
    Requires: Vercel account + DEPLOYMENT_URL environment variable.

    Usage::

        backend = VercelSandboxTerminalBackend(
            deployment_url=os.environ["VERCEL_DEPLOYMENT_URL"],
            access_token=os.environ["VERCEL_TOKEN"],
        )
        result = backend.execute("python script.py")
    """

    name = "vercel_sandbox"

    def __init__(
        self,
        deployment_url: str = "",
        access_token: str = "",
        timeout: int = 30,
    ) -> None:
        self._deployment_url = deployment_url or os.environ.get("VERCEL_DEPLOYMENT_URL", "")
        self._token = access_token or os.environ.get("VERCEL_TOKEN", "")
        self._timeout = timeout

    def execute(self, command: str, timeout: int = 30) -> CommandResult:
        if not self._deployment_url:
            return CommandResult(
                stdout="",
                stderr="VERCEL_DEPLOYMENT_URL not set. Configure your sandbox deployment URL.",
                returncode=1,
            )

        payload = json.dumps({"command": command}).encode()
        req = urllib.request.Request(
            f"{self._deployment_url}/api/exec",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._token}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout or self._timeout) as resp:
                data = json.loads(resp.read())
            return CommandResult(
                stdout=data.get("stdout", ""),
                stderr=data.get("stderr", ""),
                returncode=data.get("exitCode", 0),
                timed_out=data.get("timedOut", False),
            )
        except Exception as e:
            return CommandResult(stdout="", stderr=str(e), returncode=1)
