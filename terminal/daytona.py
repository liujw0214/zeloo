"""Daytona cloud terminal backend — executes commands via Daytona sandbox.

https://www.daytona.io
"""

from __future__ import annotations

import os

from .base import CommandResult, TerminalBackend


class DaytonaTerminalBackend(TerminalBackend):
    """Execute commands on Daytona cloud sandbox infrastructure.

    Provides managed dev environments with persistent storage.
    Requires: daytona (pip install daytona)

    Usage::

        backend = DaytonaTerminalBackend(
            api_key=os.environ["DAYTONA_API_KEY"],
            workspace_id="ws-abc123",
        )
        result = backend.execute("python train.py")
    """

    name = "daytona"

    def __init__(
        self,
        api_key: str = "",
        workspace_id: str = "",
        region: str = "us-east-1",
    ) -> None:
        self._api_key = api_key or os.environ.get("DAYTONA_API_KEY", "")
        self._workspace_id = workspace_id
        self._region = region

    def execute(self, command: str, timeout: int = 300) -> CommandResult:
        try:
            import daytona
        except ImportError:
            return CommandResult(
                stdout="",
                stderr="Daytona SDK not installed. Run: pip install daytona",
                returncode=1,
            )

        client = daytona.Client(api_key=self._api_key)
        ws = client.workspace.get(self._workspace_id)

        try:
            result = ws.run(command, timeout=timeout)
            return CommandResult(
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", ""),
                returncode=result.get("exitCode", 0),
                timed_out=result.get("timedOut", False),
            )
        except Exception as e:
            return CommandResult(stdout="", stderr=str(e), returncode=1)
