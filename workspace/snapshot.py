"""Workspace snapshot/archival system — frozen, restorable snapshots."""

from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workspace.manager import WorkspaceManager


@dataclass
class ArchiveMetadata:
    workspace_name: str
    archive_name: str
    created_at: float
    reason: str
    size_bytes: int
    version: int = field(default=1)

    def to_dict(self) -> dict:
        return {
            "workspace_name": self.workspace_name,
            "archive_name": self.archive_name,
            "created_at": self.created_at,
            "reason": self.reason,
            "size_bytes": self.size_bytes,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ArchiveMetadata:
        return cls(**data)


class WorkspaceSnapshot:
    """Create and restore compressed archives of workspaces.

    Archives are stored as compressed tarballs (.tar.zst) under:
        ~/.Zeloo/archive/<workspace-name>/<archive-name>.tar.zst

    Metadata about all archives is stored in:
        ~/.Zeloo/archive/archive.json
    """

    METADATA_FILE = "archive.json"
    ARCHIVE_DIR = "archive"

    def __init__(self, manager: WorkspaceManager | None = None):
        if manager is None:
            from workspace.manager import WorkspaceManager

            manager = WorkspaceManager()
        self.manager = manager
        from agent.zeloo_constants import get_zeloo_home

        self.archive_root = get_zeloo_home() / self.ARCHIVE_DIR
        self.archive_root.mkdir(parents=True, exist_ok=True)
        self._metadata: dict[str, ArchiveMetadata] = {}
        self._load_metadata()

    def _metadata_path(self) -> Path:
        return self.archive_root / self.METADATA_FILE

    def _workspace_archive_dir(self, ws_name: str) -> Path:
        return self.archive_root / ws_name

    def _load_metadata(self) -> None:
        mp = self._metadata_path()
        if mp.exists():
            with open(mp, encoding="utf-8") as f:
                raw = json.load(f)
            self._metadata = {
                key: ArchiveMetadata.from_dict(info) for key, info in raw.items()
            }

    def _save_metadata(self) -> None:
        data = {key: meta.to_dict() for key, meta in self._metadata.items()}
        with open(self._metadata_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _make_key(self, ws_name: str, archive_name: str) -> str:
        return f"{ws_name}/{archive_name}"

    def create(
        self,
        workspace_name: str,
        *,
        reason: str = "",
        archive_name: str | None = None,
    ) -> ArchiveMetadata:
        """Create a snapshot of a workspace.

        Args:
            workspace_name: Name of workspace to archive
            reason: Why this archive was created (e.g. "pre-delete", "milestone")
            archive_name: Optional custom name; defaults to YYYYMMDD_HHMMSS

        Returns:
            ArchiveMetadata describing the created archive
        """
        ws = self.manager.get(workspace_name)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = archive_name or f"snap_{ts}"
        key = self._make_key(workspace_name, name)
        if key in self._metadata:
            name = f"{name}_1"
            key = self._make_key(workspace_name, name)

        arc_dir = self._workspace_archive_dir(workspace_name)
        arc_dir.mkdir(parents=True, exist_ok=True)
        arc_path = arc_dir / f"{name}.tar.zst"

        meta = ArchiveMetadata(
            workspace_name=workspace_name,
            archive_name=name,
            created_at=datetime.now().timestamp(),
            reason=reason,
            size_bytes=0,
        )

        try:
            import zstandard as Zstd  # type: ignore

            with open(arc_path, "wb") as fh:
                cctx = Zstd.ZstdCompressor()
                with cctx.stream_writer(fh) as compressor:
                    with tarfile.open(fileobj=compressor, mode="w") as tf:
                        tf.add(ws.path, arcname=workspace_name)
            meta.size_bytes = arc_path.stat().st_size
        except ImportError:
            with tarfile.open(arc_path, "w:gz") as tf:
                tf.add(ws.path, arcname=workspace_name)
            meta.size_bytes = arc_path.stat().st_size

        self._metadata[key] = meta
        self._save_metadata()
        return meta

    def list_archives(
        self, workspace_name: str | None = None
    ) -> list[ArchiveMetadata]:
        """List archives, optionally filtered by workspace."""
        if workspace_name:
            return [
                m for key, m in self._metadata.items()
                if key.startswith(f"{workspace_name}/")
            ]
        return list(self._metadata.values())

    def restore(
        self,
        workspace_name: str,
        archive_name: str,
        *,
        target_name: str | None = None,
    ) -> str:
        """Restore an archive to a workspace.

        Args:
            workspace_name: Name of the archived workspace
            archive_name: Name of the archive to restore
            target_name: Optional new workspace name for the restored copy

        Returns:
            The workspace name that was restored to
        """
        key = self._make_key(workspace_name, archive_name)
        if key not in self._metadata:
            raise KeyError(f"Archive '{workspace_name}/{archive_name}' not found")

        arc_path = self._workspace_archive_dir(workspace_name) / f"{archive_name}.tar.zst"
        if not arc_path.exists():
            raise FileNotFoundError(f"Archive file not found: {arc_path}")

        restored_name = target_name or workspace_name
        if restored_name in self.manager._index and target_name is None:
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            restored_name = f"{workspace_name}_restored_{ts}"

        restored_path = self.manager.workspace_root / restored_name
        restored_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            if arc_path.suffix == ".zst":
                try:
                    import zstandard as Zstd  # type: ignore

                    with open(arc_path, "rb") as fh:
                        dctx = Zstd.ZstdDecompressor()
                        with dctx.stream_reader(fh) as decompressor:
                            with tarfile.open(fileobj=decompressor, mode="r") as tf:
                                tf.extractall(tmp_path)
                except ImportError as err:
                    raise ImportError(
                        "zstandard required for .zst: pip install zstandard"
                    ) from err
            else:
                with tarfile.open(arc_path, "r:gz") as tf:
                    tf.extractall(tmp_path)

            extracted = tmp_path / workspace_name
            if not extracted.exists():
                extracted = tmp_path
            shutil.copytree(extracted, restored_path, dirs_exist_ok=True)

        self.manager.create(
            restored_name, description=f"Restored from archive '{archive_name}'"
        )
        return restored_name

    def delete(self, workspace_name: str, archive_name: str) -> None:
        """Delete an archive file and metadata."""
        key = self._make_key(workspace_name, archive_name)
        if key not in self._metadata:
            raise KeyError(f"Archive '{workspace_name}/{archive_name}' not found")

        arc_path = self._workspace_archive_dir(workspace_name) / f"{archive_name}.tar.zst"
        if arc_path.exists():
            arc_path.unlink()
        del self._metadata[key]
        self._save_metadata()

    def prune_old(
        self, workspace_name: str | None = None, keep: int = 5
    ) -> list[str]:
        """Delete old archives, keeping the most recent N per workspace.

        Args:
            workspace_name: Optional filter by workspace
            keep: Number of recent archives to keep per workspace

        Returns:
            List of deleted archive keys
        """
        deleted = []
        archives = self.list_archives(workspace_name)
        archives.sort(key=lambda a: a.created_at, reverse=True)

        seen: dict[str, int] = {}
        for arc in archives:
            ws = arc.workspace_name
            seen[ws] = seen.get(ws, 0) + 1
            if seen[ws] > keep:
                try:
                    self.delete(ws, arc.archive_name)
                    deleted.append(f"{ws}/{arc.archive_name}")
                except (KeyError, FileNotFoundError):
                    pass
        return deleted
