"""Terminal backend interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class CommandResult:
    """Result of a terminal command execution."""

    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.returncode == 0


@runtime_checkable
class TerminalBackend(Protocol):
    """Protocol for terminal backends."""

    name: str

    def execute(self, command: str, timeout: int = 30) -> CommandResult: ...

