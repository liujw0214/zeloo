"""Local terminal backend — executes commands in the local process."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from .base import CommandResult, TerminalBackend


class LocalTerminalBackend(TerminalBackend):
    """Execute commands in the local system process.

    Suitable for local development and testing.
    Commands run with the same permissions as the Zeloo process.
    """

    name = "local"

    def __init__(self, cwd: str | Path | None = None) -> None:
        self._cwd = Path(cwd) if cwd else Path.cwd()
        self._lock = threading.Lock()

    def execute(self, command: str, timeout: int = 30) -> CommandResult:
        with self._lock:
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=str(self._cwd),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                return CommandResult(
                    stdout=result.stdout,
                    stderr=result.stderr,
                    returncode=result.returncode,
                    timed_out=False,
                )
            except subprocess.TimeoutExpired:
                return CommandResult(
                    stdout="",
                    stderr=f"Command timed out after {timeout}s",
                    returncode=124,
                    timed_out=True,
                )
            except OSError as e:
                return CommandResult(
                    stdout="",
                    stderr=str(e),
                    returncode=127,
                    timed_out=False,
                )

    def get_cwd(self) -> Path:
        return self._cwd


LocalBackend = LocalTerminalBackend
