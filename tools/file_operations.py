"""Complete file operations: read, write, copy, move, delete, diff, patch."""

from __future__ import annotations

import asyncio
import difflib
import os
import shutil
from pathlib import Path
from typing import Any

from tools.file_operations_common import (
    compute_hash,
    get_file_info,
    guess_mime_type,
    is_binary,
    normalize_path,
    safe_read,
    safe_write,
)


class FileOperations:
    """High-level file operations orchestrator.

    Provides async wrappers around common file operations with
    consistent error handling and return formats.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize file operations.

        Args:
            config: Optional configuration dictionary.
        """
        self._config = config or {}
        self._default_encoding = self._config.get("encoding", "utf-8")
        self._atomic_writes = self._config.get("atomic_writes", True)

    async def read(self, path: str | Path, **kwargs) -> dict[str, Any]:
        """Read file contents.

        Args:
            path: Path to the file to read.
            **kwargs: Additional arguments passed to read operation.

        Returns:
            Dictionary with success status and file contents.
        """
        try:
            normalized = normalize_path(path)
            if not normalized.exists():
                return {"success": False, "error": "File not found", "path": str(path)}

            if normalized.is_dir():
                return {"success": False, "error": "Path is a directory", "path": str(path)}

            encoding = kwargs.get("encoding", self._default_encoding)
            max_size = kwargs.get("max_size", 10 * 1024 * 1024)

            file_info = get_file_info(normalized)
            if file_info["size"] > max_size:
                return {
                    "success": False,
                    "error": f"File too large: {file_info['size']} bytes (max: {max_size})",
                    "path": str(path),
                }

            content = safe_read(normalized, encoding)
            lines = content.count("\n") + (1 if content else 0)

            return {
                "success": True,
                "path": str(normalized),
                "content": content,
                "size": file_info["size"],
                "lines": lines,
                "encoding": encoding,
                "is_binary": is_binary(normalized),
                "mime_type": guess_mime_type(normalized),
            }

        except Exception as e:
            return {"success": False, "error": str(e), "path": str(path)}

    async def write(
        self, path: str | Path, content: str, **kwargs
    ) -> dict[str, Any]:
        """Write content to a file.

        Args:
            path: Target file path.
            content: Content to write.
            **kwargs: Additional arguments (encoding, atomic).

        Returns:
            Dictionary with success status and details.
        """
        try:
            normalized = normalize_path(path)
            encoding = kwargs.get("encoding", self._default_encoding)
            atomic = kwargs.get("atomic", self._atomic_writes)

            normalized.parent.mkdir(parents=True, exist_ok=True)
            safe_write(normalized, content, encoding, atomic)

            file_info = get_file_info(normalized)
            return {
                "success": True,
                "path": str(normalized),
                "bytes_written": len(content.encode(encoding)),
                "size": file_info["size"],
            }

        except Exception as e:
            return {"success": False, "error": str(e), "path": str(path)}

    async def append(self, path: str | Path, content: str) -> dict[str, Any]:
        """Append content to a file.

        Args:
            path: Target file path.
            content: Content to append.

        Returns:
            Dictionary with success status and details.
        """
        try:
            normalized = normalize_path(path)
            encoding = self._default_encoding

            normalized.parent.mkdir(parents=True, exist_ok=True)

            with normalized.open("a", encoding=encoding) as f:
                f.write(content)

            file_info = get_file_info(normalized)
            return {
                "success": True,
                "path": str(normalized),
                "bytes_appended": len(content.encode(encoding)),
                "total_size": file_info["size"],
            }

        except Exception as e:
            return {"success": False, "error": str(e), "path": str(path)}

    async def copy(self, src: str | Path, dst: str | Path) -> dict[str, Any]:
        """Copy a file or directory.

        Args:
            src: Source path.
            dst: Destination path.

        Returns:
            Dictionary with success status and details.
        """
        try:
            src_path = normalize_path(src)
            dst_path = normalize_path(dst)

            if not src_path.exists():
                return {"success": False, "error": "Source not found", "source": str(src)}

            dst_path.parent.mkdir(parents=True, exist_ok=True)

            if src_path.is_dir():
                shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
            else:
                shutil.copy2(src_path, dst_path)

            file_info = get_file_info(dst_path)
            return {
                "success": True,
                "source": str(src_path),
                "destination": str(dst_path),
                "size": file_info["size"],
                "is_dir": file_info["is_dir"],
            }

        except Exception as e:
            return {"success": False, "error": str(e), "source": str(src), "destination": str(dst)}

    async def move(self, src: str | Path, dst: str | Path) -> dict[str, Any]:
        """Move a file or directory.

        Args:
            src: Source path.
            dst: Destination path.

        Returns:
            Dictionary with success status and details.
        """
        try:
            src_path = normalize_path(src)
            dst_path = normalize_path(dst)

            if not src_path.exists():
                return {"success": False, "error": "Source not found", "source": str(src)}

            dst_path.parent.mkdir(parents=True, exist_ok=True)
            src_path.rename(dst_path)

            return {
                "success": True,
                "source": str(src_path),
                "destination": str(dst_path),
            }

        except Exception as e:
            return {"success": False, "error": str(e), "source": str(src), "destination": str(dst)}

    async def delete(self, path: str | Path, **kwargs) -> dict[str, Any]:
        """Delete a file or directory.

        Args:
            path: Path to delete.
            **kwargs: Additional options (recursive, force).

        Returns:
            Dictionary with success status and details.
        """
        try:
            normalized = normalize_path(path)

            if not normalized.exists():
                return {"success": False, "error": "Path not found", "path": str(path)}

            recursive = kwargs.get("recursive", False)

            if normalized.is_dir():
                if recursive:
                    shutil.rmtree(normalized)
                else:
                    normalized.rmdir()
            else:
                normalized.unlink()

            return {
                "success": True,
                "path": str(normalized),
                "deleted": True,
            }

        except Exception as e:
            return {"success": False, "error": str(e), "path": str(path)}

    async def mkdir(self, path: str | Path, parents: bool = False) -> dict[str, Any]:
        """Create a directory.

        Args:
            path: Directory path to create.
            parents: Create parent directories if they don't exist.

        Returns:
            Dictionary with success status and details.
        """
        try:
            normalized = normalize_path(path)
            normalized.mkdir(parents=parents, exist_ok=True)

            return {
                "success": True,
                "path": str(normalized),
                "created": True,
            }

        except Exception as e:
            return {"success": False, "error": str(e), "path": str(path)}

    async def stat(self, path: str | Path) -> dict[str, Any]:
        """Get file/directory statistics.

        Args:
            path: Path to get stats for.

        Returns:
            Dictionary with file information.
        """
        try:
            normalized = normalize_path(path)

            if not normalized.exists():
                return {"success": False, "error": "Path not found", "path": str(path)}

            info = get_file_info(normalized)
            info["success"] = True
            info["path"] = str(normalized)
            return info

        except Exception as e:
            return {"success": False, "error": str(e), "path": str(path)}

    async def exists(self, path: str | Path) -> bool:
        """Check if path exists.

        Args:
            path: Path to check.

        Returns:
            True if path exists, False otherwise.
        """
        normalized = normalize_path(path)
        return normalized.exists()

    async def listdir(
        self, path: str | Path, pattern: str = "*"
    ) -> dict[str, Any]:
        """List directory contents.

        Args:
            path: Directory path to list.
            pattern: Optional glob pattern to filter results.

        Returns:
            Dictionary with directory listing.
        """
        try:
            normalized = normalize_path(path)

            if not normalized.exists():
                return {"success": False, "error": "Directory not found", "path": str(path)}

            if not normalized.is_dir():
                return {"success": False, "error": "Not a directory", "path": str(path)}

            from fnmatch import fnmatch

            entries = []
            for entry in normalized.iterdir():
                if fnmatch(entry.name, pattern):
                    info = get_file_info(entry)
                    entries.append({
                        "name": entry.name,
                        "path": str(entry),
                        "is_dir": info["is_dir"],
                        "is_file": info["is_file"],
                        "size": info["size"],
                    })

            return {
                "success": True,
                "path": str(normalized),
                "pattern": pattern,
                "entries": entries,
                "count": len(entries),
            }

        except Exception as e:
            return {"success": False, "error": str(e), "path": str(path)}

    async def diff(
        self, path1: str | Path, path2: str | Path
    ) -> dict[str, Any]:
        """Compute diff between two files.

        Args:
            path1: First file path.
            path2: Second file path.

        Returns:
            Dictionary with diff information.
        """
        try:
            p1 = normalize_path(path1)
            p2 = normalize_path(path2)

            if not p1.exists():
                return {"success": False, "error": f"File not found: {path1}"}
            if not p2.exists():
                return {"success": False, "error": f"File not found: {path2}"}

            content1 = safe_read(p1)
            content2 = safe_read(p2)

            if content1 == content2:
                return {
                    "success": True,
                    "identical": True,
                    "path1": str(p1),
                    "path2": str(p2),
                }

            lines1 = content1.splitlines(keepends=True)
            lines2 = content2.splitlines(keepends=True)

            differ = difflib.unified_diff(
                lines1, lines2,
                fromfile=str(p1),
                tofile=str(p2),
                lineterm=""
            )

            diff_lines = list(differ)

            return {
                "success": True,
                "identical": False,
                "path1": str(p1),
                "path2": str(p2),
                "diff": "".join(diff_lines),
                "diff_lines": len(diff_lines),
                "stats": difflib.SequenceMatcher(None, content1, content2).ratio(),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
