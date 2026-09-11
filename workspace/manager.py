"""Workspace manager — create, list, switch, and manage project workspaces."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

WORKSPACE_MD_FILES = (
    "SOUL.md",
    "AGENTS.md",
    "USER.md",
    "TOOLS.md",
    "IDENTITY.md",
    "HEARTBEAT.md",
    "BOOTSTRAP.md",
    "MEMORY.md",
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass
class WorkspaceProfile:
    name: str
    path: Path
    description: str = ""
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    last_active: float = field(default_factory=lambda: datetime.now().timestamp())
    memory_backend: str = "localfile"
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.path),
            "description": self.description,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "memory_backend": self.memory_backend,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict) -> WorkspaceProfile:
        return cls(
            name=data["name"],
            path=Path(data["path"]),
            description=data.get("description", ""),
            created_at=data.get("created_at", 0),
            last_active=data.get("last_active", 0),
            memory_backend=data.get("memory_backend", "localfile"),
            tags=data.get("tags", []),
        )


class WorkspaceManager:
    """Manages multiple isolated project workspaces.

    Each workspace is a self-contained environment with its own:
    - Working directory (source code, project files)
    - Zeloo profile (config, memory, skills)
    - Metadata (description, tags, created/accessed times)

    Directory layout:
        ~/.Zeloo/workspace/
        ├── workspace.json          # Index of all workspaces
        ├── default/               # Default workspace
        │   ├── profile/           # Zeloo profile for this workspace
        │   ├── memory/            # Persistent memory files
        │   ├── skills/            # Workspace-local skills
        │   ├── SOUL.md           # Optional workspace-specific identity
        │   └── metadata.json     # Workspace metadata
        ├── project-a/             # Another workspace
        └── ...
    """

    INDEX_FILE = "workspace.json"

    def __init__(self, workspace_root: Path | None = None):
        if workspace_root is None:
            from agent.zeloo_constants import get_zeloo_home
            workspace_root = get_zeloo_home() / "workspace"
        self.workspace_root = workspace_root
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, WorkspaceProfile] = {}
        self._load_index()

    def _index_path(self) -> Path:
        return self.workspace_root / self.INDEX_FILE

    def _load_index(self) -> None:
        idx = self._index_path()
        if idx.exists():
            with open(idx, encoding="utf-8") as f:
                data = json.load(f)
            self._index = {
                name: WorkspaceProfile.from_dict(info)
                for name, info in data.items()
            }
        else:
            self._default_workspace()
            self._save_index()

    def _save_index(self) -> None:
        data = {name: ws.to_dict() for name, ws in self._index.items()}
        with open(self._index_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _default_workspace(self) -> None:
        name = "default"
        ws_path = self.workspace_root / name
        self._init_workspace_dir(ws_path)
        self._index[name] = WorkspaceProfile(
            name=name,
            path=ws_path,
            description="Default workspace",
        )

    def _init_workspace_dir(self, ws_path: Path) -> None:
        (ws_path / "profile").mkdir(parents=True, exist_ok=True)
        (ws_path / "memory").mkdir(parents=True, exist_ok=True)
        (ws_path / "skills").mkdir(parents=True, exist_ok=True)
        self._init_md_files(ws_path)
        metadata = ws_path / "metadata.json"
        if not metadata.exists():
            with open(metadata, "w", encoding="utf-8") as f:
                json.dump({"version": 1}, f)

    def _init_md_files(self, ws_path: Path) -> None:
        for md_file in WORKSPACE_MD_FILES:
            target = ws_path / md_file
            if not target.exists():
                src = _TEMPLATES_DIR / md_file
                if src.exists():
                    shutil.copy2(src, target)
                else:
                    target.write_text("", encoding="utf-8")

    def create(
        self,
        name: str,
        *,
        description: str = "",
        copy_from: str | None = None,
        tags: list[str] | None = None,
    ) -> WorkspaceProfile:
        """Create a new workspace, optionally copying from an existing one.

        Args:
            name: Unique workspace name (alphanumeric + dash/underscore)
            description: Human-readable description
            copy_from: Name of existing workspace to copy from
            tags: Optional categorization tags

        Returns:
            The created WorkspaceProfile
        """
        if name in self._index:
            raise ValueError(f"Workspace '{name}' already exists")

        ws_path = self.workspace_root / name
        self._init_workspace_dir(ws_path)

        if copy_from and copy_from in self._index:
            src = self._index[copy_from].path
            for subdir in ("profile", "memory", "skills"):
                src_dir = src / subdir
                if src_dir.exists():
                    dst_dir = ws_path / subdir
                    for item in src_dir.iterdir():
                        shutil.copy2(item, dst_dir / item.name)

        ws = WorkspaceProfile(
            name=name,
            path=ws_path,
            description=description,
            tags=tags or [],
        )
        self._index[name] = ws
        self._save_index()
        return ws

    def get(self, name: str) -> WorkspaceProfile:
        """Get workspace profile by name."""
        if name not in self._index:
            raise KeyError(f"Workspace '{name}' not found")
        return self._index[name]

    def list_all(self) -> list[WorkspaceProfile]:
        """List all workspaces, sorted by last_active descending."""
        return sorted(self._index.values(), key=lambda w: w.last_active, reverse=True)

    def switch_to(self, name: str) -> WorkspaceProfile:
        """Mark a workspace as active and return its profile.

        This updates last_active timestamp and can be used as a
        signal for context switching.
        """
        ws = self.get(name)
        ws.last_active = datetime.now().timestamp()
        self._save_index()
        return ws

    def delete(self, name: str, *, archive_first: bool = True) -> None:
        """Delete a workspace.

        Args:
            name: Workspace name
            archive_first: If True, archive before deleting
        """
        if name == "default":
            raise ValueError("Cannot delete the default workspace")
        if name not in self._index:
            raise KeyError(f"Workspace '{name}' not found")

        ws = self._index[name]

        if archive_first:
            from workspace.snapshot import WorkspaceSnapshot
            snapshot = WorkspaceSnapshot(self)
            snapshot.create(name, reason="pre-delete")

        shutil.rmtree(ws.path)
        del self._index[name]
        self._save_index()

    def rename(self, old_name: str, new_name: str) -> WorkspaceProfile:
        """Rename a workspace."""
        if old_name not in self._index:
            raise KeyError(f"Workspace '{old_name}' not found")
        if new_name in self._index:
            raise ValueError(f"Workspace '{new_name}' already exists")
        if old_name == "default":
            raise ValueError("Cannot rename the default workspace")

        ws = self._index[old_name]
        old_path = ws.path
        new_path = self.workspace_root / new_name
        old_path.rename(new_path)
        ws.name = new_name
        ws.path = new_path
        self._index[new_name] = ws
        del self._index[old_name]
        self._save_index()
        return ws

    def add_tag(self, name: str, tag: str) -> None:
        """Add a tag to a workspace."""
        ws = self.get(name)
        if tag not in ws.tags:
            ws.tags.append(tag)
            self._save_index()

    def remove_tag(self, name: str, tag: str) -> None:
        """Remove a tag from a workspace."""
        ws = self.get(name)
        if tag in ws.tags:
            ws.tags.remove(tag)
            self._save_index()

    def search_by_tag(self, tag: str) -> list[WorkspaceProfile]:
        """Find all workspaces with a given tag."""
        return [ws for ws in self._index.values() if tag in ws.tags]
