"""Workspace tools — manage isolated project environments.

Each tool is registered via the ``@tool`` decorator on a top-level
function rather than on a ``BaseTool.execute`` method, so the registry
sees distinct names (``workspace_list``, ``workspace_switch``, …)
instead of six overlapping ``execute`` entries.
"""

from __future__ import annotations

from typing import Any

from tools.base import tool


@tool(name="workspace_list", description="List all workspaces, showing name, description, last active time, and tags", toolset="workspace")
def workspace_list() -> str:
    """List all workspaces."""
    from workspace.manager import WorkspaceManager

    mgr = WorkspaceManager()
    workspaces = mgr.list_all()

    if not workspaces:
        return "No workspaces found."

    lines = ["## Workspaces\n"]
    for ws in workspaces:
        from datetime import datetime

        last = datetime.fromtimestamp(ws.last_active).strftime("%Y-%m-%d %H:%M")
        tags = ", ".join(ws.tags) if ws.tags else "—"
        lines.append(f"- **{ws.name}** — {ws.description or '—'}")
        lines.append(f"  - Last active: {last} | Tags: {tags}")
    return "\n".join(lines)


@tool(name="workspace_switch", description="Switch to a different workspace by name", toolset="workspace")
def workspace_switch(name: str) -> str:
    """Switch to a workspace by name."""
    from workspace.manager import WorkspaceManager

    mgr = WorkspaceManager()
    try:
        ws = mgr.switch_to(name)
        return f"Switched to workspace '{ws.name}'"
    except KeyError:
        return f"Workspace '{name}' not found. Available: {[w.name for w in mgr.list_all()]}"


@tool(name="workspace_create", description="Create a new workspace", toolset="workspace")
def workspace_create(
    name: str,
    description: str = "",
    copy_from: str | None = None,
) -> str:
    """Create a new workspace.

    Args:
        name: Unique workspace name
        description: Optional description
        copy_from: Optional existing workspace to copy from
    """
    from workspace.manager import WorkspaceManager

    mgr = WorkspaceManager()
    try:
        ws = mgr.create(name, description=description, copy_from=copy_from)
        return f"Created workspace '{ws.name}' at {ws.path}"
    except ValueError as e:
        return f"Error: {e}"


@tool(name="workspace_archive", description="Archive (snapshot) a workspace", toolset="workspace")
def workspace_archive(
    workspace_name: str,
    reason: str = "",
    archive_name: str | None = None,
) -> str:
    """Archive a workspace.

    Args:
        workspace_name: Name of workspace to archive
        reason: Why this archive is being created
        archive_name: Optional custom archive name
    """
    from workspace.snapshot import WorkspaceSnapshot

    snap = WorkspaceSnapshot()
    try:
        meta = snap.create(workspace_name, reason=reason, archive_name=archive_name)
        return (
            f"Archived '{workspace_name}' as '{meta.archive_name}' "
            f"({meta.size_bytes / 1024:.1f} KB)"
        )
    except KeyError as e:
        return f"Error: {e}"


@tool(name="workspace_restore", description="Restore a workspace from an archive", toolset="workspace")
def workspace_restore(
    workspace_name: str,
    archive_name: str,
    target_name: str | None = None,
) -> str:
    """Restore a workspace from archive.

    Args:
        workspace_name: Original workspace name
        archive_name: Archive to restore
        target_name: Optional new name for restored copy
    """
    from workspace.snapshot import WorkspaceSnapshot

    snap = WorkspaceSnapshot()
    try:
        restored = snap.restore(workspace_name, archive_name, target_name=target_name)
        return f"Restored '{workspace_name}/{archive_name}' as workspace '{restored}'"
    except (KeyError, FileNotFoundError) as e:
        return f"Error: {e}"


@tool(name="archive_list", description="List available workspace archives", toolset="workspace")
def archive_list(workspace_name: str | None = None) -> str:
    """List archives, optionally filtered by workspace."""
    from datetime import datetime

    from workspace.snapshot import WorkspaceSnapshot

    snap = WorkspaceSnapshot()
    archives = snap.list_archives(workspace_name)

    if not archives:
        return "No archives found."

    lines = ["## Archives\n"]
    for arc in sorted(archives, key=lambda a: a.created_at, reverse=True):
        ts = datetime.fromtimestamp(arc.created_at).strftime("%Y-%m-%d %H:%M")
        size_kb = arc.size_bytes / 1024
        lines.append(
            f"- **{arc.workspace_name}/{arc.archive_name}** — {ts} "
            f"({size_kb:.1f} KB)"
        )
        if arc.reason:
            lines.append(f"  - Reason: {arc.reason}")
    return "\n".join(lines)


__all__ = [
    "workspace_list",
    "workspace_switch",
    "workspace_create",
    "workspace_archive",
    "workspace_restore",
    "archive_list",
]


def __getattr__(name: str) -> Any:
    """Lazy-export legacy class names so external callers using
    ``from tools.workspace_tools import WorkspaceListTool`` keep working
    without registering them as tools.
    """
    aliases = _legacy_class_aliases()
    if name in aliases:
        return aliases[name]
    raise AttributeError(f"module 'tools.workspace_tools' has no attribute {name!r}")


def _legacy_class_aliases() -> dict[str, Any]:
    """Provide class names for backward compatibility with callers that
    imported the old BaseTool subclasses. These shims are not registered
    as tools and are not used internally — only kept so external imports
    keep working.
    """
    from tools.base import BaseTool

    class _WorkspaceListTool(BaseTool):
        name = "workspace_list"
        description = "List all workspaces"

        def execute(self) -> str:  # pragma: no cover - legacy shim
            return workspace_list()

    class _WorkspaceSwitchTool(BaseTool):
        name = "workspace_switch"
        description = "Switch to a different workspace by name"

        def execute(self, name: str) -> str:  # pragma: no cover
            return workspace_switch(name)

    class _WorkspaceCreateTool(BaseTool):
        name = "workspace_create"
        description = "Create a new workspace"

        def execute(  # pragma: no cover
            self,
            name: str,
            description: str = "",
            copy_from: str | None = None,
        ) -> str:
            return workspace_create(name, description=description, copy_from=copy_from)

    class _WorkspaceArchiveTool(BaseTool):
        name = "workspace_archive"
        description = "Archive (snapshot) a workspace"

        def execute(  # pragma: no cover
            self,
            workspace_name: str,
            reason: str = "",
            archive_name: str | None = None,
        ) -> str:
            return workspace_archive(
                workspace_name, reason=reason, archive_name=archive_name
            )

    class _WorkspaceRestoreTool(BaseTool):
        name = "workspace_restore"
        description = "Restore a workspace from an archive"

        def execute(  # pragma: no cover
            self,
            workspace_name: str,
            archive_name: str,
            target_name: str | None = None,
        ) -> str:
            return workspace_restore(
                workspace_name, archive_name, target_name=target_name
            )

    class _ArchiveListTool(BaseTool):
        name = "archive_list"
        description = "List available workspace archives"

        def execute(  # pragma: no cover
            self, workspace_name: str | None = None
        ) -> str:
            return archive_list(workspace_name)

    return {
        "WorkspaceListTool": _WorkspaceListTool,
        "WorkspaceSwitchTool": _WorkspaceSwitchTool,
        "WorkspaceCreateTool": _WorkspaceCreateTool,
        "WorkspaceArchiveTool": _WorkspaceArchiveTool,
        "WorkspaceRestoreTool": _WorkspaceRestoreTool,
        "ArchiveListTool": _ArchiveListTool,
    }