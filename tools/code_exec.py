"""Code execution tool — run Python code in an isolated subprocess.

The code is executed in a fresh Python interpreter with a timeout,
preventing it from crashing the agent process. Output (stdout/stderr)
is captured and returned.

Sandbox hardening:
- Runs inside a fresh temporary working directory (not the project root).
- Strips sensitive environment variables (API keys, credentials, home paths).
- On Unix, enforces memory and CPU-time limits via ``resource.setrlimit``.
- Optional static pre-flight check blocks known-dangerous modules
  (``socket``, ``subprocess``, ``os.system``, ``ctypes``, etc.).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.base import tool

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
DEFAULT_MAX_OUTPUT = 10000
DEFAULT_MAX_MEMORY_MB = 512

# Modules whose import is blocked by the static pre-flight check.
# These can bypass the subprocess-level isolation.
_BLOCKED_MODULES = frozenset({
    "socket",
    "subprocess",
    "ctypes",
    "multiprocessing",
    "threading",
})

# Patterns that indicate code is trying to spawn processes or access
# the network directly via builtins.
_BLOCKED_PATTERNS = (
    re.compile(r"os\.system\s*\("),
    re.compile(r"os\.popen\s*\("),
    re.compile(r"os\.exec"),
    re.compile(r"__import__\s*\(\s*['\"]subprocess"),
    re.compile(r"__import__\s*\(\s*['\"]socket"),
    re.compile(r"__import__\s*\(\s*['\"]ctypes"),
)


def _strip_env() -> dict[str, str]:
    """Return a cleaned environment for the child process.

    Removes variables that contain credentials, tokens, or sensitive
    filesystem paths so that untrusted code cannot exfiltrate them.
    """
    sensitive_prefixes = (
        "API_KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD",
        "OPENAI_", "ANTHROPIC_", "DEEPSEEK_", "GEMINI_",
        "AWS_", "AZURE_", "GCP_", "GITHUB_", "SLACK_",
        "DISCORD_", "TELEGRAM_", "zeloo_",
    )
    clean: dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if any(upper.startswith(p) for p in sensitive_prefixes):
            continue
        if upper in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG", "LC_ALL"}:
            clean[key] = value
        # Keep Python-specific vars so the interpreter works.
        if upper.startswith("PYTHON"):
            clean[key] = value
    # Minimal PATH so python itself can be found.
    clean.setdefault("PATH", os.environ.get("PATH", ""))
    return clean


def _preflight_check(code: str) -> str | None:
    """Return an error message if *code* uses blocked constructs.

    Returns ``None`` when the code passes the check.
    """
    for blocked in _BLOCKED_MODULES:
        # Match `import socket`, `from socket import`, `import socket as ...`
        if re.search(rf"^\s*(?:import|from)\s+{blocked}\b", code, re.MULTILINE):
            return (
                f"Error: import of '{blocked}' is blocked in the sandbox "
                f"for safety. Use the agent's built-in tools instead."
            )
    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(code):
            return (
                "Error: code contains a blocked pattern that could escape "
                "the sandbox. Use the agent's built-in tools instead."
            )
    return None


def _build_preexec(memory_mb: int):  # type: ignore[no-untyped-def]
    """Return a preexec_fn that sets Unix resource limits, or None.

    On non-Unix platforms returns ``None`` (the ``resource`` module is
    unavailable).
    """
    try:
        import resource  # type: ignore[import-not-found]
    except ImportError:
        return None

    def _set_limits() -> None:
        bytes_limit = memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (bytes_limit, bytes_limit))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (DEFAULT_TIMEOUT, DEFAULT_TIMEOUT))
        except (ValueError, OSError):
            pass

    return _set_limits


@tool(
    name="execute_code",
    description="Execute Python code in an isolated sandbox",
    dangerous=True,
    toolset="code_execution",
)
def execute_code(
    code: str,
    timeout: int = DEFAULT_TIMEOUT,
    max_memory_mb: int = DEFAULT_MAX_MEMORY_MB,
    allow_network: bool = False,
) -> str:
    """Execute Python code and return its output.

    Args:
        code: The Python source code to execute.
        timeout: Maximum execution time in seconds.
        max_memory_mb: Maximum memory the process may use (Unix only).
        allow_network: If False (default), network access is discouraged
            by removing proxy/network env vars. The static check still
            blocks ``socket``/``subprocess`` imports.

    Returns:
        The combined stdout/stderr output of the code.
    """
    # Static pre-flight check for known-dangerous constructs.
    preflight_error = _preflight_check(code)
    if preflight_error:
        return preflight_error

    try:
        # Use a fresh temp directory as both the script location and cwd
        # so the code cannot read project files by relative path.
        with tempfile.TemporaryDirectory(prefix="Zeloo-sandbox-") as tmpdir:
            script_path = Path(tmpdir) / "user_code.py"
            script_path.write_text(code, encoding="utf-8")

            env = _strip_env()
            if not allow_network:
                env.pop("http_proxy", None)
                env.pop("https_proxy", None)
                env.pop("HTTP_PROXY", None)
                env.pop("HTTPS_PROXY", None)
                env.pop("no_proxy", None)

            preexec = _build_preexec(max_memory_mb)

            try:
                result = subprocess.run(
                    [sys.executable, str(script_path)],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=tmpdir,
                    env=env,
                    preexec_fn=preexec,
                )
                output = result.stdout
                if result.stderr:
                    output += ("\n" if output else "") + result.stderr
                if result.returncode != 0:
                    output += f"\n[exit code: {result.returncode}]"
                if len(output) > DEFAULT_MAX_OUTPUT:
                    output = output[:DEFAULT_MAX_OUTPUT] + "\n...[truncated]"
                return output or "(no output)"
            except subprocess.TimeoutExpired:
                return f"Error: Code execution timed out after {timeout}s"
    except Exception as e:
        logger.exception("execute_code failed")
        return f"Error executing code: {e}"
