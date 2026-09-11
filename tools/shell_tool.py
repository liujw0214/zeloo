"""Shell / terminal command tools."""

from __future__ import annotations

import logging
import re
import shlex

from tools.base import tool
from tools.output_scan import scan_tool_output

logger = logging.getLogger(__name__)

# Read-only / non-destructive commands allowed by shell_unsafe without
# explicit user confirmation. Anything not in this set is rejected.
_SAFE_COMMAND_WHITELIST = frozenset({
    "ls", "ll", "dir",
    "pwd",
    "echo", "printf",
    "cat", "head", "tail", "less", "more",
    "grep", "egrep", "fgrep", "rg",
    "find",
    "wc", "sort", "uniq",
    "stat", "file",
    "date", "time",
    "whoami", "id", "hostname", "uname",
    "env", "printenv",
    "ps", "pgrep",
    "df", "du", "free", "top", "htop",
    "tree",
    "which", "where", "command",
    "man", "help", "--help", "-h",
})

# Patterns that indicate a destructive or privileged operation, even if
# the base command is whitelisted (e.g. ``ls | rm``).
_DANGEROUS_PATTERNS = re.compile(
    r"(?:^|\s)(rm|rmdir|mv|cp|chmod|chown|chgrp|mkfs|mount|umount|"
    r"shutdown|reboot|halt|poweroff|kill|killall|pkill|"
    r"dd|fdisk|parted|iptables|sudo|su|doas)(?:\s|$)",
    re.IGNORECASE,
)


def _get_backend():
    """Return the active terminal backend from the current agent.

    Falls back to a local backend when no agent context is active
    (e.g. during unit tests or direct tool calls).
    """
    try:
        from run_agent import _current_agent

        agent = _current_agent.get()
        if agent is not None:
            return agent.terminal_backend
    except Exception:
        pass
    from terminal.local import LocalBackend

    return LocalBackend()


@tool(name="shell", description="Execute a shell command", dangerous=True, toolset="terminal")
def shell(command: str, timeout: int = 30) -> str:
    """Execute a shell command and return its output.

    Uses the configured terminal backend (local / docker / ssh).

    Args:
        command: The command to execute.
        timeout: Timeout in seconds.
    """
    backend = _get_backend()
    try:
        result = backend.execute(command, timeout=timeout)
        output = result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        if output:
            output = scan_tool_output(output, tool_name="shell_unsafe", source=command[:200])
        return output or "(no output)"
    except Exception as e:
        return f"Error executing command: {e}"


@tool(
    name="shell_unsafe",
    description="Execute a restricted, read-only shell command without confirmation",
    dangerous=False,
    toolset="terminal",
)
def shell_unsafe(command: str, timeout: int = 15) -> str:
    """Execute a read-only shell command from a safety whitelist.

    Unlike ``shell``, this tool does not require confirmation because it
    only allows non-destructive commands (ls, cat, grep, find, etc.).
    Commands containing redirection, pipes to destructive tools, or
    sudo/su are rejected.

    Args:
        command: The command to execute (must start with a whitelisted binary).
        timeout: Timeout in seconds (capped at 30).
    """
    timeout = min(timeout, 30)

    # Reject if the command contains obviously destructive patterns
    if _DANGEROUS_PATTERNS.search(command):
        return (
            "Error: command contains a destructive or privileged operation. "
            "Use the 'shell' tool with confirmation for this."
        )

    # Reject shell redirections and backgrounding
    if any(op in command for op in (">", ">>", "<", "<<", "&", ";", "`")):
        return (
            "Error: redirection, backgrounding, and command chaining are "
            "not allowed in shell_unsafe. Use the 'shell' tool instead."
        )

    # Extract the base command name
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return f"Error parsing command: {exc}"

    if not parts:
        return "Error: empty command"

    base = parts[0]
    # Strip path prefix if present (e.g. /usr/bin/ls -> ls)
    base_name = base.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]

    if base_name not in _SAFE_COMMAND_WHITELIST:
        return (
            f"Error: '{base_name}' is not in the shell_unsafe whitelist. "
            f"Allowed commands: {', '.join(sorted(_SAFE_COMMAND_WHITELIST))}"
        )

    backend = _get_backend()
    try:
        result = backend.execute(command, timeout=timeout)
        output = result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output or "(no output)"
    except Exception as e:
        return f"Error executing command: {e}"
