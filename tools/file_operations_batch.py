"""Batch file operations for efficient processing."""

from __future__ import annotations

import asyncio
import concurrent.futures
import fnmatch
import os
import shutil
from pathlib import Path
from typing import Any

from tools.file_operations_common import (
    compute_hash,
    get_file_info,
    normalize_path,
    safe_read,
    safe_write,
)


class BatchFileOperations:
    """Efficient batch file processing.

    Provides methods for batch read, write, copy, delete operations
    with optional parallel execution.
    """

    def __init__(self, max_workers: int = 4) -> None:
        """Initialize batch operations.

        Args:
            max_workers: Maximum number of parallel workers.
        """
        self._max_workers = max_workers
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None

    def _get_executor(self) -> concurrent.futures.ThreadPoolExecutor:
        """Get or create the thread pool executor.

        Returns:
            ThreadPoolExecutor instance.
        """
        if self._executor is None:
            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=self._max_workers
            )
        return self._executor

    def _run_sync(self, func: callable, *args: Any, **kwargs: Any) -> Any:
        """Run a synchronous function in a thread pool.

        Args:
            func: Function to run.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Function result.
        """
        executor = self._get_executor()
        future = executor.submit(func, *args, **kwargs)
        return future.result()

    async def batch_read(
        self, paths: list[Path], parallel: bool = True
    ) -> list[dict[str, Any]]:
        """Read multiple files in batch.

        Args:
            paths: List of paths to read.
            parallel: Whether to read files in parallel.

        Returns:
            List of read results.
        """
        results: list[dict[str, Any]] = []

        if parallel:
            loop = asyncio.get_event_loop()
            futures = [
                loop.run_in_executor(None, self._read_single, path)
                for path in paths
            ]
            results = await asyncio.gather(*futures)
        else:
            for path in paths:
                results.append(self._read_single(path))

        return results

    def _read_single(self, path: Path) -> dict[str, Any]:
        """Read a single file.

        Args:
            path: Path to read.

        Returns:
            Dictionary with read result.
        """
        try:
            normalized = normalize_path(path)
            if not normalized.exists():
                return {"success": False, "error": "File not found", "path": str(path)}

            content = safe_read(normalized)
            info = get_file_info(normalized)

            return {
                "success": True,
                "path": str(normalized),
                "content": content,
                "size": info["size"],
                "lines": content.count("\n") + (1 if content else 0),
            }

        except Exception as e:
            return {"success": False, "error": str(e), "path": str(path)}

    async def batch_write(
        self, operations: list[tuple[Path, str]]
    ) -> list[dict[str, Any]]:
        """Write multiple files in batch.

        Args:
            operations: List of (path, content) tuples.

        Returns:
            List of write results.
        """
        results: list[dict[str, Any]] = []
        loop = asyncio.get_event_loop()

        futures = [
            loop.run_in_executor(None, self._write_single, path, content)
            for path, content in operations
        ]
        results = await asyncio.gather(*futures)

        return results

    def _write_single(self, path: Path, content: str) -> dict[str, Any]:
        """Write a single file.

        Args:
            path: Target path.
            content: Content to write.

        Returns:
            Dictionary with write result.
        """
        try:
            normalized = normalize_path(path)
            normalized.parent.mkdir(parents=True, exist_ok=True)
            safe_write(normalized, content)

            return {
                "success": True,
                "path": str(normalized),
                "bytes_written": len(content.encode("utf-8")),
            }

        except Exception as e:
            return {"success": False, "error": str(e), "path": str(path)}

    async def batch_copy(
        self, operations: list[tuple[Path, Path]]
    ) -> list[dict[str, Any]]:
        """Copy multiple files/directories in batch.

        Args:
            operations: List of (source, destination) tuples.

        Returns:
            List of copy results.
        """
        results: list[dict[str, Any]] = []
        loop = asyncio.get_event_loop()

        futures = [
            loop.run_in_executor(None, self._copy_single, src, dst)
            for src, dst in operations
        ]
        results = await asyncio.gather(*futures)

        return results

    def _copy_single(self, src: Path, dst: Path) -> dict[str, Any]:
        """Copy a single file or directory.

        Args:
            src: Source path.
            dst: Destination path.

        Returns:
            Dictionary with copy result.
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

            return {
                "success": True,
                "source": str(src_path),
                "destination": str(dst_path),
            }

        except Exception as e:
            return {"success": False, "error": str(e), "source": str(src), "destination": str(dst)}

    async def batch_delete(
        self, paths: list[Path], parallel: bool = True
    ) -> list[dict[str, Any]]:
        """Delete multiple files/directories in batch.

        Args:
            paths: List of paths to delete.
            parallel: Whether to delete in parallel.

        Returns:
            List of delete results.
        """
        results: list[dict[str, Any]] = []

        if parallel:
            loop = asyncio.get_event_loop()
            futures = [
                loop.run_in_executor(None, self._delete_single, path)
                for path in paths
            ]
            results = await asyncio.gather(*futures)
        else:
            for path in paths:
                results.append(self._delete_single(path))

        return results

    def _delete_single(self, path: Path) -> dict[str, Any]:
        """Delete a single file or directory.

        Args:
            path: Path to delete.

        Returns:
            Dictionary with delete result.
        """
        try:
            normalized = normalize_path(path)

            if not normalized.exists():
                return {"success": False, "error": "Path not found", "path": str(path)}

            if normalized.is_dir():
                shutil.rmtree(normalized)
            else:
                normalized.unlink()

            return {
                "success": True,
                "path": str(normalized),
                "deleted": True,
            }

        except Exception as e:
            return {"success": False, "error": str(e), "path": str(path)}

    async def glob_batch(
        self, patterns: list[str], root: Path | None = None
    ) -> dict[str, list[Path]]:
        """Glob multiple patterns in batch.

        Args:
            patterns: List of glob patterns.
            root: Root directory to search in.

        Returns:
            Dictionary mapping patterns to matching paths.
        """
        results: dict[str, list[Path]] = {}
        search_root = root or Path.cwd()

        loop = asyncio.get_event_loop()
        futures = {
            pattern: loop.run_in_executor(
                None, self._glob_single, pattern, search_root
            )
            for pattern in patterns
        }

        for pattern, future in futures.items():
            results[pattern] = await future

        return results

    def _glob_single(self, pattern: str, root: Path) -> list[Path]:
        """Glob a single pattern.

        Args:
            pattern: Glob pattern.
            root: Root directory.

        Returns:
            List of matching paths.
        """
        matches: list[Path] = []
        try:
            if "*" in pattern or "?" in pattern or "[" in pattern:
                for root_dir, _dirs, files in os.walk(root):
                    for filename in files:
                        if fnmatch.fnmatch(filename, pattern):
                            matches.append(Path(root_dir) / filename)
            else:
                direct = root / pattern
                if direct.exists():
                    matches.append(direct)
        except (OSError, PermissionError):
            pass
        return matches

    async def batch_hash(
        self, paths: list[Path], algorithm: str = "sha256"
    ) -> dict[str, Any]:
        """Compute hashes for multiple files in batch.

        Args:
            paths: List of paths to hash.
            algorithm: Hash algorithm to use.

        Returns:
            Dictionary mapping paths to hash results.
        """
        results: dict[str, Any] = {}
        loop = asyncio.get_event_loop()

        futures = [
            loop.run_in_executor(None, self._hash_single, path, algorithm)
            for path in paths
        ]
        hash_results = await asyncio.gather(*futures)

        for path, result in zip(paths, hash_results):
            results[str(path)] = result

        return results

    def _hash_single(self, path: Path, algorithm: str) -> dict[str, Any]:
        """Compute hash for a single file.

        Args:
            path: Path to hash.
            algorithm: Hash algorithm.

        Returns:
            Dictionary with hash result.
        """
        try:
            normalized = normalize_path(path)
            if not normalized.exists():
                return {"success": False, "error": "File not found"}

            hash_value = compute_hash(normalized, algorithm)
            return {
                "success": True,
                "hash": hash_value,
                "algorithm": algorithm,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def shutdown(self) -> None:
        """Shutdown the thread pool executor."""
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
