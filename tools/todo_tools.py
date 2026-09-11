"""Todo list tools — create, list, complete, and remove tasks.

Todos are persisted as a JSON file under the agent's home directory so
they survive across sessions.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from tools.base import tool

logger = logging.getLogger(__name__)


def _todo_path() -> Path:
    """Return the path to the todos JSON file."""
    home = os.environ.get("zeloo_HOME") or str(Path.home() / ".Zeloo")
    path = Path(home) / "todos.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_todos() -> list[dict[str, Any]]:
    path = _todo_path()
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_todos(todos: list[dict[str, Any]]) -> None:
    _todo_path().write_text(json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8")


@tool(name="todo_add", description="Add a task to the todo list", toolset="todo")
def todo_add(task: str, priority: str = "normal") -> str:
    """Add a new task to the todo list.

    Args:
        task: Description of the task.
        priority: Priority level (low, normal, high).
    """
    todos = _load_todos()
    todo = {
        "id": len(todos) + 1,
        "task": task,
        "priority": priority,
        "done": False,
        "created_at": time.time(),
    }
    todos.append(todo)
    _save_todos(todos)
    return f"Added todo #{todo['id']}: {task} [{priority}]"


@tool(name="todo_list", description="List all tasks", toolset="todo")
def todo_list(show_done: bool = True) -> str:
    """List all tasks.

    Args:
        show_done: Include completed tasks.
    """
    todos = _load_todos()
    if not show_done:
        todos = [t for t in todos if not t["done"]]
    if not todos:
        return "(no tasks)"
    lines = []
    for t in todos:
        status = "x" if t["done"] else " "
        lines.append(f"[{status}] #{t['id']} ({t['priority']}) {t['task']}")
    return "\n".join(lines)


@tool(name="todo_complete", description="Mark a task as done", toolset="todo")
def todo_complete(todo_id: int) -> str:
    """Mark a task as completed.

    Args:
        todo_id: The ID of the task to complete.
    """
    todos = _load_todos()
    for t in todos:
        if t["id"] == todo_id:
            t["done"] = True
            _save_todos(todos)
            return f"Completed todo #{todo_id}: {t['task']}"
    return f"Error: Todo #{todo_id} not found"


@tool(name="todo_remove", description="Remove a task from the list", toolset="todo")
def todo_remove(todo_id: int) -> str:
    """Remove a task from the list.

    Args:
        todo_id: The ID of the task to remove.
    """
    todos = _load_todos()
    new_todos = [t for t in todos if t["id"] != todo_id]
    if len(new_todos) == len(todos):
        return f"Error: Todo #{todo_id} not found"
    _save_todos(new_todos)
    return f"Removed todo #{todo_id}"
