"""Write guards: prevent accidental overwrites, require confirmation for dangerous writes."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any


class WriteGuard:
    """Guard against dangerous file writes.

    Provides checks for dangerous file patterns, binary overwrites,
    and requires confirmation for potentially harmful operations.
    """

    DANGEROUS_PATTERNS = [
        "**/password*.py",
        "**/secrets*.py",
        "**/.env",
        "**/id_rsa*",
        "**/credentials*.json",
        "**/api_key*.py",
        "**/token*.py",
        "**/.aws/credentials",
        "**/~/.ssh/id_*",
        "**/wallet.dat",
        "**/.pki/**",
        "**/etc/shadow",
        "**/etc/sudoers",
        "**/SAM",
        "**/SYSTEM",
    ]

    BINARY_EXTENSIONS = {
        ".exe", ".dll", ".so", ".dylib", ".bin", ".dat",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico",
        ".pdf", ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
        ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flac",
        ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".o", ".obj", ".a", ".lib", ".pyc", ".pyo",
        ".class", ".jar", ".war", ".ear",
        ".wasm", ".webp",
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the write guard.

        Args:
            config: Optional configuration dictionary.
        """
        self._config = config or {}
        self._blocked_patterns: list[str] = list(self.DANGEROUS_PATTERNS)
        self._binary_extensions: set[str] = set(self.BINARY_EXTENSIONS)
        self._allow_binary = self._config.get("allow_binary", False)
        self._dangerous_confirm_count = 0

    def is_dangerous(self, path: Path) -> tuple[bool, str]:
        """Check if writing to this path is considered dangerous.

        Args:
            path: Path to check.

        Returns:
            Tuple of (is_dangerous, reason).
        """
        normalized = str(path.resolve())

        for pattern in self._blocked_patterns:
            if self._matches_pattern(normalized, pattern):
                return True, f"Path matches dangerous pattern: {pattern}"

        if path.exists():
            if path.is_symlink():
                return True, "Path is a symbolic link"
            if self._is_hidden_on_windows(path):
                return True, "Path is a hidden file on Windows"

        return False, ""

    def _matches_pattern(self, path_str: str, pattern: str) -> bool:
        """Check if path matches a glob pattern.

        Args:
            path_str: Path as string.
            pattern: Glob pattern to match.

        Returns:
            True if matches, False otherwise.
        """
        path_str = path_str.replace('\\', '/')
        pattern = pattern.replace('\\', '/')
        return fnmatch.fnmatch(path_str, pattern)

    def _is_hidden_on_windows(self, path: Path) -> bool:
        """Check if file is hidden on Windows.

        Args:
            path: Path to check.

        Returns:
            True if hidden on Windows, False otherwise.
        """
        import sys
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            from ctypes import wintypes

            attrs = wintypes.DWORD()
            result = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if result == -1:
                return False
            return bool(result & 0x2)
        except Exception:
            return False

    def is_binary_overwrite(self, path: Path) -> bool:
        """Check if overwriting this file would replace binary content.

        Args:
            path: Path to check.

        Returns:
            True if file appears to be binary, False otherwise.
        """
        if not path.exists():
            return False
        if self._allow_binary:
            return False
        if path.suffix.lower() in self._binary_extensions:
            return True
        if path.suffix.lower() in {".py", ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}:
            return False
        try:
            with path.open("rb") as f:
                chunk = f.read(1024)
                if b"\0" in chunk:
                    return True
        except (OSError, PermissionError):
            pass
        return False

    def check_overwrite(self, path: Path, require_confirm: bool = True) -> bool:
        """Check if overwriting a file should be allowed.

        Args:
            path: Path to check.
            require_confirm: Whether to require explicit confirmation.

        Returns:
            True if write is allowed, False otherwise.
        """
        is_dangerous, reason = self.is_dangerous(path)
        if is_dangerous:
            self._dangerous_confirm_count += 1
            return False

        if path.exists() and self.is_binary_overwrite(path):
            return False

        return not require_confirm

    def check_write_allowed(self, path: Path) -> tuple[bool, str]:
        """Check if writing to path is allowed with detailed reason.

        Args:
            path: Path to check.

        Returns:
            Tuple of (allowed, reason).
        """
        if not path.exists():
            return True, "New file creation allowed"

        is_dangerous, dangerous_reason = self.is_dangerous(path)
        if is_dangerous:
            return False, dangerous_reason

        if self.is_binary_overwrite(path):
            return False, "Binary file overwrite not allowed"

        return True, "Write allowed"

    def add_blocked_pattern(self, pattern: str) -> None:
        """Add a pattern to the blocked list.

        Args:
            pattern: Glob pattern to block.
        """
        if pattern not in self._blocked_patterns:
            self._blocked_patterns.append(pattern)

    def remove_blocked_pattern(self, pattern: str) -> None:
        """Remove a pattern from the blocked list.

        Args:
            pattern: Glob pattern to remove.
        """
        if pattern in self._blocked_patterns:
            self._blocked_patterns.remove(pattern)

    def get_blocked_patterns(self) -> list[str]:
        """Get list of currently blocked patterns.

        Returns:
            List of blocked patterns.
        """
        return list(self._blocked_patterns)

    def get_dangerous_confirm_count(self) -> int:
        """Get number of times dangerous write was blocked.

        Returns:
            Count of blocked dangerous operations.
        """
        return self._dangerous_confirm_count

    def validate_path_components(self, path: Path) -> list[str]:
        """Validate individual path components for suspicious names.

        Args:
            path: Path to validate.

        Returns:
            List of warnings for suspicious components.
        """
        warnings: list[str] = []
        dangerous_components = {
            "..": "Parent directory reference",
            "~": "Home directory expansion",
            "$": "Environment variable",
            "`": "Command substitution",
            ";": "Command separator",
            "|": "Pipe",
            "&": "Background execution",
        }
        path_str = str(path)
        for component, meaning in dangerous_components.items():
            if component in path_str:
                warnings.append(f"Contains '{component}': {meaning}")
        return warnings
