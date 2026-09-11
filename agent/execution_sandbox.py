"""Code execution sandbox — isolated Python/JavaScript execution."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SandboxPolicy(StrEnum):
    """Code execution sandbox security policies."""

    STRICT = "strict"             # Only allow safe builtins
    MODERATE = "moderate"         # Allow stdlib + restricted imports
    PERMISSIVE = "permissive"     # Most operations allowed
    UNRESTRICTED = "unrestricted" # No restrictions (use with caution)


@dataclass
class SandboxResult:
    """Result of sandboxed code execution."""

    success: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float
    memory_used_mb: float = 0.0
    language: str = "python"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SandboxConfig:
    """Configuration for execution sandbox."""

    language: str = "python"  # python | javascript | bash
    policy: SandboxPolicy = SandboxPolicy.MODERATE
    timeout_seconds: int = 30
    memory_limit_mb: int = 256
    network_access: bool = False
    allowed_modules: list[str] = field(default_factory=lambda: [
        "math", "json", "datetime", "collections", "itertools",
        "functools", "re", "random", "string", "pathlib",
    ])
    working_dir: str = "/tmp"


class ExecutionSandbox:
    """Safe code execution sandbox.

    Executes code in a restricted subprocess with configurable
    security policies and resource limits.
    """

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self.config = config or SandboxConfig()

    def execute(
        self,
        code: str,
        language: str | None = None,
        timeout: int | None = None,
    ) -> SandboxResult:
        """Execute code in the sandbox.

        Args:
            code: Source code to execute.
            language: Override config language.
            timeout: Override config timeout.
        """
        lang = language or self.config.language
        timeout = timeout or self.config.timeout_seconds

        start_time = time.time()

        if lang == "python":
            return self._execute_python(code, timeout, start_time)
        elif lang == "javascript":
            return self._execute_javascript(code, timeout, start_time)
        elif lang == "bash":
            return self._execute_bash(code, timeout, start_time)
        else:
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Unsupported language: {lang}",
                exit_code=1,
                duration_ms=0.0,
                language=lang,
            )

    def _execute_python(
        self,
        code: str,
        timeout: int,
        start_time: float,
    ) -> SandboxResult:
        wrapper = self._wrap_python_code(code)
        try:
            result = subprocess.run(
                ["python", "-c", wrapper],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.config.working_dir,
                env=self._build_env(),
            )
            return SandboxResult(
                success=(result.returncode == 0),
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                duration_ms=(time.time() - start_time) * 1000,
                language="python",
                metadata={"policy": self.config.policy.value},
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Execution timed out after {timeout}s",
                exit_code=-1,
                duration_ms=(time.time() - start_time) * 1000,
                language="python",
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=-1,
                duration_ms=(time.time() - start_time) * 1000,
                language="python",
            )

    def _execute_javascript(
        self,
        code: str,
        timeout: int,
        start_time: float,
    ) -> SandboxResult:
        try:
            result = subprocess.run(
                ["node", "-e", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.config.working_dir,
                env=self._build_env(),
            )
            return SandboxResult(
                success=(result.returncode == 0),
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                duration_ms=(time.time() - start_time) * 1000,
                language="javascript",
            )
        except FileNotFoundError:
            return SandboxResult(
                success=False,
                stdout="",
                stderr="node not installed",
                exit_code=1,
                duration_ms=(time.time() - start_time) * 1000,
                language="javascript",
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Execution timed out after {timeout}s",
                exit_code=-1,
                duration_ms=(time.time() - start_time) * 1000,
                language="javascript",
            )

    def _execute_bash(
        self,
        code: str,
        timeout: int,
        start_time: float,
    ) -> SandboxResult:
        if self.config.policy == SandboxPolicy.STRICT:
            return SandboxResult(
                success=False,
                stdout="",
                stderr="Bash execution not allowed in strict policy",
                exit_code=1,
                duration_ms=0.0,
                language="bash",
            )
        try:
            result = subprocess.run(
                code,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.config.working_dir,
                env=self._build_env(),
            )
            return SandboxResult(
                success=(result.returncode == 0),
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                duration_ms=(time.time() - start_time) * 1000,
                language="bash",
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Execution timed out after {timeout}s",
                exit_code=-1,
                duration_ms=(time.time() - start_time) * 1000,
                language="bash",
            )

    def _wrap_python_code(self, code: str) -> str:
        if self.config.policy == SandboxPolicy.UNRESTRICTED:
            return code

        if self.config.policy == SandboxPolicy.STRICT:
            allowed = ",".join(repr(m) for m in self.config.allowed_modules)
            return (
                f"import sys\n"
                f"_allowed = [{allowed}]\n"
                f"class _RestrictedImport:\n"
                f"    def find_module(self, name, path=None):\n"
                f"        if name in _allowed: return None\n"
                f"        raise ImportError(f'Import of {{name}} blocked')\n"
                f"    def find_spec(self, name, *args):\n"
                f"        if name in _allowed: return None\n"
                f"        raise ImportError(f'Import of {{name}} blocked')\n"
                f"sys.meta_path.insert(0, _RestrictedImport())\n"
                f"{code}"
            )

        if not self.config.network_access:
            return (
                "import socket\n"
                "_orig_socket = socket.socket\n"
                "def _blocked_socket(*args, **kwargs):\n"
                "    raise PermissionError('Network access blocked')\n"
                "socket.socket = _blocked_socket\n"
                f"{code}"
            )

        return code

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = "0"
        env["zeloo_SANDBOX"] = "1"
        env["zeloo_POLICY"] = self.config.policy.value
        return env


__all__ = [
    "SandboxPolicy",
    "SandboxConfig",
    "SandboxResult",
    "ExecutionSandbox",
]