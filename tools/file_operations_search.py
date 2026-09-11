"""Advanced file search with pattern matching, content search, and filters."""

from __future__ import annotations

import fnmatch
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any


class FileSearch:
    """Advanced file search engine.

    Provides various search methods including name matching,
    content grep, size filtering, and date-based search.
    """

    def __init__(self, root: Path | None = None, max_results: int = 1000) -> None:
        """Initialize file search.

        Args:
            root: Root directory to search in. Uses cwd if None.
            max_results: Maximum number of results to return.
        """
        self._root = root or Path.cwd()
        self._max_results = max_results
        self._lock = threading.RLock()

    def _get_all_files(self) -> list[Path]:
        """Get all files under root directory.

        Returns:
            List of all file paths.
        """
        files: list[Path] = []
        try:
            for root, _dirs, filenames in os.walk(self._root):
                for filename in filenames:
                    path = Path(root) / filename
                    files.append(path)
                    if len(files) >= self._max_results:
                        break
                if len(files) >= self._max_results:
                    break
        except (OSError, PermissionError):
            pass
        return files

    def _matches_regex(self, text: str, pattern: str) -> bool:
        """Check if text matches regex pattern.

        Args:
            text: Text to search in.
            pattern: Regex pattern.

        Returns:
            True if pattern matches, False otherwise.
        """
        try:
            return bool(re.search(pattern, text))
        except re.error:
            return False

    def _matches_glob(self, text: str, pattern: str) -> bool:
        """Check if text matches glob pattern.

        Args:
            text: Text to search in.
            pattern: Glob pattern.

        Returns:
            True if pattern matches, False otherwise.
        """
        return fnmatch.fnmatch(text, pattern)

    def _get_file_info_dict(self, path: Path) -> dict[str, Any]:
        """Get file information as dictionary.

        Args:
            path: Path to file.

        Returns:
            Dictionary with file information.
        """
        try:
            stat = path.stat()
            return {
                "path": str(path),
                "name": path.name,
                "stem": path.stem,
                "suffix": path.suffix,
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "modified_str": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "created": stat.st_ctime,
                "parent": str(path.parent),
            }
        except (OSError, PermissionError):
            return {
                "path": str(path),
                "name": path.name,
                "error": "Cannot stat file",
            }

    async def search_by_name(
        self, pattern: str, regex: bool = False
    ) -> list[dict[str, Any]]:
        """Search files by name pattern.

        Args:
            pattern: Pattern to match against file names.
            regex: If True, treat pattern as regex; otherwise as glob.

        Returns:
            List of matching file information dictionaries.
        """
        with self._lock:
            results: list[dict[str, Any]] = []
            files = self._get_all_files()

            for path in files:
                matches = False
                if regex:
                    matches = self._matches_regex(path.name, pattern)
                else:
                    matches = self._matches_glob(path.name, pattern)

                if matches:
                    results.append(self._get_file_info_dict(path))
                    if len(results) >= self._max_results:
                        break

            return results

    async def search_by_content(
        self,
        query: str,
        extensions: list[str] | None = None,
        regex: bool = False,
    ) -> list[dict[str, Any]]:
        """Search files by content.

        Args:
            query: Search query string.
            extensions: Optional list of file extensions to search.
            regex: If True, treat query as regex; otherwise as literal.

        Returns:
            List of matching file information with line numbers.
        """
        with self._lock:
            results: list[dict[str, Any]] = []
            files = self._get_all_files()

            for path in files:
                if extensions and path.suffix not in extensions:
                    continue

                try:
                    if not path.is_file():
                        continue
                    content = path.read_text(encoding="utf-8", errors="replace")
                except (OSError, PermissionError):
                    continue

                matches: list[dict[str, Any]] = []
                lines = content.split("\n")

                for i, line in enumerate(lines, 1):
                    if regex:
                        found = self._matches_regex(line, query)
                    else:
                        found = query in line

                    if found:
                        matches.append({
                            "line_number": i,
                            "line": line[:200],
                        })

                if matches:
                    result = self._get_file_info_dict(path)
                    result["matches"] = matches
                    result["match_count"] = len(matches)
                    results.append(result)

                    if len(results) >= self._max_results:
                        break

            return results

    async def search_by_size(
        self,
        min_bytes: int = 0,
        max_bytes: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search files by size.

        Args:
            min_bytes: Minimum file size in bytes.
            max_bytes: Maximum file size in bytes (inclusive).

        Returns:
            List of files matching size criteria.
        """
        with self._lock:
            results: list[dict[str, Any]] = []
            files = self._get_all_files()

            for path in files:
                try:
                    size = path.stat().st_size
                except (OSError, PermissionError):
                    continue

                if size >= min_bytes:
                    if max_bytes is None or size <= max_bytes:
                        result = self._get_file_info_dict(path)
                        results.append(result)

                        if len(results) >= self._max_results:
                            break

            return sorted(results, key=lambda x: x["size"])

    async def search_by_date(
        self,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Search files by modification date.

        Args:
            after: Only include files modified after this date.
            before: Only include files modified before this date.

        Returns:
            List of files matching date criteria.
        """
        with self._lock:
            results: list[dict[str, Any]] = []
            files = self._get_all_files()

            after_ts = after.timestamp() if after else 0
            before_ts = before.timestamp() if before else float("inf")

            for path in files:
                try:
                    mtime = path.stat().st_mtime
                except (OSError, PermissionError):
                    continue

                if after_ts <= mtime <= before_ts:
                    result = self._get_file_info_dict(path)
                    results.append(result)

                    if len(results) >= self._max_results:
                        break

            return sorted(results, key=lambda x: x["modified"], reverse=True)

    async def grep(
        self,
        pattern: str,
        path: Path | None = None,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """Grep-like search across files.

        Args:
            pattern: Search pattern (supports regex if regex=True).
            path: Optional specific path to search.
            **kwargs: Additional options (extensions, case_sensitive, line_numbers).

        Returns:
            List of matches with file and line information.
        """
        extensions = kwargs.get("extensions")
        case_sensitive = kwargs.get("case_sensitive", True)
        line_numbers = kwargs.get("line_numbers", True)
        regex = kwargs.get("regex", False)

        if path:
            search_root = path
        else:
            search_root = self._root

        with self._lock:
            results: list[dict[str, Any]] = []

            try:
                for root, _dirs, filenames in os.walk(search_root):
                    for filename in filenames:
                        file_path = Path(root) / filename

                        if extensions and file_path.suffix not in extensions:
                            continue

                        try:
                            content = file_path.read_text(encoding="utf-8", errors="replace")
                        except (OSError, PermissionError):
                            continue

                        search_content = content if case_sensitive else content.lower()
                        search_pattern = pattern if case_sensitive else pattern.lower()

                        matches: list[dict[str, Any]] = []
                        lines = content.split("\n")
                        search_lines = search_content.split("\n")

                        for i, (line, search_line) in enumerate(zip(lines, search_lines), 1):
                            found = False
                            if regex:
                                try:
                                    flags = 0 if case_sensitive else re.IGNORECASE
                                    found = bool(re.search(pattern, line, flags))
                                except re.error:
                                    continue
                            else:
                                found = search_pattern in search_line

                            if found:
                                match_info: dict[str, Any] = {"line": line[:200]}
                                if line_numbers:
                                    match_info["line_number"] = i
                                matches.append(match_info)

                        if matches:
                            result = self._get_file_info_dict(file_path)
                            result["matches"] = matches
                            result["match_count"] = len(matches)
                            results.append(result)

                            if len(results) >= self._max_results:
                                return results

            except (OSError, PermissionError):
                pass

            return results

    async def find_duplicates(
        self, by_content: bool = True
    ) -> list[list[Path]]:
        """Find duplicate files.

        Args:
            by_content: If True, compare by content hash; otherwise by name.

        Returns:
            List of groups of duplicate files.
        """
        with self._lock:
            files = self._get_all_files()
            groups: dict[str, list[Path]] = {}

            for path in files:
                try:
                    if by_content:
                        from tools.file_operations_common import compute_hash

                        key = compute_hash(path)
                    else:
                        key = path.name

                    if key not in groups:
                        groups[key] = []
                    groups[key].append(path)

                except (OSError, PermissionError):
                    continue

            duplicates = [paths for paths in groups.values() if len(paths) > 1]
            return duplicates

    def set_root(self, root: Path) -> None:
        """Set the search root directory.

        Args:
            root: New root directory.
        """
        with self._lock:
            self._root = root

    def get_root(self) -> Path:
        """Get current search root directory.

        Returns:
            Current root path.
        """
        return self._root
