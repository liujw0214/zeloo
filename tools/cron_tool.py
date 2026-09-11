"""Cron scheduling tools — register and manage timed tasks.

Jobs execute a shell command (through the active terminal backend) when
their cron expression fires. The scheduler runs in a background daemon
thread owned by the AIAgent.
"""

from __future__ import annotations

import logging

from tools.base import tool

logger = logging.getLogger(__name__)


def _get_scheduler():
    """Return the active CronScheduler from the current agent, or None."""
    try:
        from run_agent import _current_agent

        agent = _current_agent.get()
        if agent is not None:
            return getattr(agent, "cron_scheduler", None)
    except Exception:
        pass
    return None


def _run_shell(command: str) -> None:
    """Execute a shell command as a cron callback (errors logged only)."""
    try:
        from tools.shell_tool import shell

        result = shell(command)
        logger.info("Cron job output: %s", str(result)[:200])
    except Exception:
        logger.exception("Cron job failed: %s", command[:100])


@tool(
    name="cron_add",
    description="Register a timed task that runs a shell command",
    toolset="cron",
)
def cron_add(name: str, expression: str, command: str) -> str:
    """Register a cron job that executes *command* on schedule.

    Args:
        name: Unique job name.
        expression: 5-field cron expression (min hour dom month dow).
        command: Shell command to run when the job fires.
    """
    scheduler = _get_scheduler()
    if scheduler is None:
        return "Error: Cron scheduler is not available in this environment."
    try:
        scheduler.add_job(name, expression, lambda: _run_shell(command))
        return f"Cron job '{name}' registered ({expression}) -> {command}"
    except ValueError as e:
        return f"Error: invalid cron expression: {e}"


@tool(name="cron_list", description="List all registered cron jobs", toolset="cron")
def cron_list() -> str:
    """Return a summary of all registered cron jobs."""
    scheduler = _get_scheduler()
    if scheduler is None:
        return "Error: Cron scheduler is not available in this environment."
    jobs = scheduler.list_jobs()
    if not jobs:
        return "(no cron jobs)"
    lines = [f"{j['name']}: {j['expression']} (last_run={j['last_run']})" for j in jobs]
    return "\n".join(lines)


@tool(name="cron_remove", description="Remove a cron job by name", toolset="cron")
def cron_remove(name: str) -> str:
    """Remove a cron job.

    Args:
        name: Name of the job to remove.
    """
    scheduler = _get_scheduler()
    if scheduler is None:
        return "Error: Cron scheduler is not available in this environment."
    scheduler.remove_job(name)
    return f"Cron job '{name}' removed."
