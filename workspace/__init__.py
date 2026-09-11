"""Zeloo workspace management — self-contained project environments.

A Workspace is a self-contained directory capturing everything needed for a
project or task: source code, config, memory, skills, state, and metadata.

Archives are frozen snapshots of workspaces that can be restored at any time.
"""

from workspace.manager import WorkspaceManager
from workspace.snapshot import WorkspaceSnapshot

__all__ = ["WorkspaceManager", "WorkspaceSnapshot"]
