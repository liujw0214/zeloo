"""Common file operation utilities shared by all file tools."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
from pathlib import Path
from typing import Any


def normalize_path(path: str | Path) -> Path:
    """Normalize a path to an absolute Path object.

    Args:
        path: Input path as string or Path object.

    Returns:
        Normalized absolute Path object.
    """
    if isinstance(path, str):
        path = Path(path)
    return path.expanduser().resolve()


def resolve_home(path: str | Path) -> Path:
    """Resolve ~ in path to user's home directory.

    Args:
        path: Input path potentially containing ~.

    Returns:
        Path with ~ resolved to home directory.
    """
    if isinstance(path, str):
        path = Path(path)
    return path.expanduser().resolve()


def safe_read(path: Path, encoding: str = "utf-8") -> str:
    """Safely read file contents with error handling.

    Args:
        path: Path to the file to read.
        encoding: Text encoding to use (default: utf-8).

    Returns:
        File contents as string.

    Raises:
        FileNotFoundError: If file does not exist.
        PermissionError: If file cannot be read.
        UnicodeDecodeError: If file cannot be decoded with specified encoding.
    """
    return path.read_text(encoding=encoding, errors="replace")


def safe_write(path: Path, content: str, encoding: str = "utf-8", atomic: bool = True) -> None:
    """Safely write content to file with optional atomic write.

    Args:
        path: Target file path.
        content: Content to write.
        encoding: Text encoding to use (default: utf-8).
        atomic: If True, use atomic write (write to temp then rename).
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if atomic:
        dirname = path.parent
        fd, tmp_path = tempfile.mkstemp(dir=dirname, prefix=".tmp_", suffix=path.name)
        try:
            with os.fdopen(fd, "w", encoding=encoding) as f:
                f.write(content)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    else:
        path.write_text(content, encoding=encoding)


def compute_hash(path: Path, algorithm: str = "sha256") -> str:
    """Compute hash of file contents.

    Args:
        path: Path to the file.
        algorithm: Hash algorithm to use (sha256, md5, sha1, sha512).

    Returns:
        Hexadecimal hash string of the file contents.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If algorithm is not supported.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Not a file: {path}")

    hash_func = getattr(hashlib, algorithm, None)
    if hash_func is None:
        raise ValueError(f"Unsupported hash algorithm: {algorithm}")

    digest = hash_func()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_file_info(path: Path) -> dict[str, Any]:
    """Get comprehensive file information.

    Args:
        path: Path to the file.

    Returns:
        Dictionary containing file metadata:
        - size: File size in bytes
        - created: Creation timestamp
        - modified: Last modification timestamp
        - accessed: Last access timestamp
        - is_dir: Whether path is a directory
        - is_file: Whether path is a regular file
        - is_symlink: Whether path is a symlink
        - permissions: Permission string (octal)
    """
    stat = path.stat()
    return {
        "size": stat.st_size,
        "created": stat.st_ctime,
        "modified": stat.st_mtime,
        "accessed": stat.st_atime,
        "is_dir": path.is_dir(),
        "is_file": path.is_file(),
        "is_symlink": path.is_symlink(),
        "permissions": oct(stat.st_mode)[-3:],
        "name": path.name,
        "suffix": path.suffix,
        "stem": path.stem,
        "parent": str(path.parent),
    }


def is_binary(path: Path) -> bool:
    """Check if a file appears to be binary.

    Args:
        path: Path to the file to check.

    Returns:
        True if file appears to be binary, False otherwise.
    """
    if not path.is_file():
        return False

    try:
        with path.open("rb") as f:
            chunk = f.read(1024)
            if not chunk:
                return False
            return b"\0" in chunk
    except (OSError, PermissionError):
        return True


def guess_mime_type(path: Path) -> str:
    """Guess MIME type based on file extension.

    Args:
        path: Path to the file.

    Returns:
        MIME type string, or 'application/octet-stream' if unknown.
    """
    mime_type, _ = mimetypes.guess_type(str(path))
    return mime_type or "application/octet-stream"
