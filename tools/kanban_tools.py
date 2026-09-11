"""Kanban tools — multi-agent collaborative task board.

Exposes the :class:`agent.kanban.KanbanBoard` as agent tools so the
agent can create, list, show, assign, and complete tasks on a board.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from agent.kanban import KanbanBoard
from tools.base import tool

logger = logging.getLogger(__name__)

_BOARD_ID = "default"


def _get_board() -> KanbanBoard:
    """Return the default kanban board singleton."""
    home = os.environ.get("zeloo_HOME") or str(Path.home() / ".Zeloo")
    storage = Path(home) / "kanban" / f"{_BOARD_ID}.json"
    return KanbanBoard(board_id=_BOARD_ID, storage_path=storage)


@tool(
    name="kanban_create",
    description="Create a new task on the kanban board",
    toolset="kanban",
)
def kanban_create(
    title: str,
    description: str = "",
    tenant: str = "default",
    priority: int = 0,
) -> str:
    """Create a new task on the kanban board.

    Args:
        title: Short title for the task.
        description: Optional detailed description.
        tenant: Tenant/team namespace (default: "default").
        priority: Priority level (higher = more urgent).
    """
    board = _get_board()
    task_id = board.create_task(
        title=title,
        description=description,
        tenant=tenant,
        priority=priority,
    )
    return f"Created task '{task_id}': {title} [{tenant}] priority={priority}"


@tool(
    name="kanban_list",
    description="List tasks on the kanban board",
    toolset="kanban",
)
def kanban_list(tenant: str = "", status: str = "") -> str:
    """List tasks, optionally filtered by tenant and/or status.

    Args:
        tenant: Filter by tenant name (empty = all).
        status: Filter by status (todo/in_progress/completed/failed/blocked).
    """
    from agent.kanban import TaskStatus

    board = _get_board()
    status_filter = None
    if status:
        try:
            status_filter = TaskStatus(status)
        except ValueError:
            valid = ", ".join(s.value for s in TaskStatus)
            return f"Error: Invalid status '{status}'. Use one of: {valid}"

    tenant_filter = tenant or None
    tasks = board.list_tasks(tenant=tenant_filter, status=status_filter)
    if not tasks:
        return "(no tasks)"

    lines = []
    for t in tasks:
        lines.append(
            f"[{t.status.value}] {t.id[:8]} (p{t.priority}) {t.title} "
            f"-- assignee={t.assignee or 'unassigned'} tenant={t.tenant}"
        )
    return "\n".join(lines)


@tool(
    name="kanban_show",
    description="Show details of a specific kanban task",
    toolset="kanban",
)
def kanban_show(task_id: str) -> str:
    """Show full details of a task.

    Args:
        task_id: The task ID.
    """
    board = _get_board()
    task = board.get_task(task_id)
    if task is None:
        return f"Error: Task '{task_id}' not found"
    return (
        f"Task: {task.id}\n"
        f"Title: {task.title}\n"
        f"Description: {task.description or '(none)'}\n"
        f"Status: {task.status.value}\n"
        f"Tenant: {task.tenant}\n"
        f"Assignee: {task.assignee or 'unassigned'}\n"
        f"Priority: {task.priority}\n"
        f"Retries: {task.retry_count}/{task.max_retries}\n"
        f"Created: {task.created_at}"
    )


@tool(
    name="kanban_assign",
    description="Assign a kanban task to a worker",
    toolset="kanban",
)
def kanban_assign(task_id: str, worker_id: str) -> str:
    """Assign a task to a worker (marks it in_progress).

    Args:
        task_id: The task ID.
        worker_id: The worker/agent identifier.
    """
    board = _get_board()
    if board.assign_task(task_id, worker_id):
        return f"Task '{task_id[:8]}' assigned to worker '{worker_id}'"
    return f"Error: Task '{task_id}' not found"


@tool(
    name="kanban_complete",
    description="Mark a kanban task as completed",
    toolset="kanban",
)
def kanban_complete(task_id: str, result: str = "") -> str:
    """Mark a task as completed.

    Args:
        task_id: The task ID.
        result: Optional result summary to store.
    """
    board = _get_board()
    if board.complete_task(task_id, result=result):
        return f"Task '{task_id[:8]}' completed"
    return f"Error: Task '{task_id}' not found"


@tool(
    name="kanban_heartbeat",
    description="Send a heartbeat for an in-progress kanban task",
    toolset="kanban",
)
def kanban_heartbeat(task_id: str) -> str:
    """Send a heartbeat to keep an in-progress task alive.

    Args:
        task_id: The task ID.
    """
    board = _get_board()
    if board.heartbeat(task_id):
        return f"Heartbeat sent for task '{task_id[:8]}'"
    return f"Error: Task '{task_id}' not found"
