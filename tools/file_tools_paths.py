"""Path manipulation utilities."""

from __future__ import annotations

from pathlib import Path


def common_prefix(paths: list[Path]) -> Path | None:
    """Find the longest common prefix of a list of paths.

    Args:
        paths: List of Path objects to analyze.

    Returns:
        The common prefix path, or None if no common prefix exists.
    """
    if not paths:
        return None
    if len(paths) == 1:
        return paths[0]

    str_paths = [str(p) for p in paths]
    first = str_paths[0]

    common = ""
    for i, char in enumerate(first):
        if all(p[i:i+1] == char for p in str_paths if i < len(p)):
            common += char
        else:
            break

    if not common:
        return None

    result = Path(common)
    if not result.is_dir() and any(p.is_dir() for p in paths):
        parts = result.parts
        if len(parts) > 1:
            result = Path(*parts[:-1])
        else:
            return None

    return result


def relativize(path: Path, base: Path) -> Path:
    """Make path relative to base.

    Args:
        path: The path to make relative.
        base: The base path to relativize against.

    Returns:
        Path relative to base.
    """
    try:
        return path.relative_to(base)
    except ValueError:
        path_str = str(path)
        base_str = str(base)
        if path_str.startswith(base_str):
            rel = path_str[len(base_str):]
            if rel.startswith(('\\', '/')):
                rel = rel[1:]
            return Path(rel)
        raise


def is_subpath(path: Path, base: Path) -> bool:
    """Check if path is a subpath of base.

    Args:
        path: The potential subpath to check.
        base: The base path to check against.

    Returns:
        True if path is under base, False otherwise.
    """
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def shortest_path(path: Path, base: Path) -> Path:
    """Get the shortest representation of path relative to base.

    Args:
        path: The path to represent.
        base: The base path for relative calculation.

    Returns:
        Either the relative path (if shorter) or absolute path.
    """
    try:
        rel = path.relative_to(base)
        rel_str = str(rel)
        abs_str = str(path)
        if len(rel_str) < len(abs_str):
            return rel
        return path
    except ValueError:
        return path


def split_all(path: Path) -> list[str]:
    """Split a path into all its components.

    Args:
        path: The path to split.

    Returns:
        List of path components.
    """
    parts = []
    current = Path(path)
    while current != current.parent:
        parts.insert(0, current.name)
        current = current.parent
    if current.name:
        parts.insert(0, current.name)
    return parts


def join_relative(base: Path, relative: str) -> Path:
    """Join a base path with a relative path.

    Args:
        base: The base path.
        relative: The relative path string.

    Returns:
        Joined absolute path.
    """
    if Path(relative).is_absolute():
        return Path(relative)
    parts = relative.replace('\\', '/').split('/')
    result = base
    for part in parts:
        if part == '..':
            result = result.parent
        elif part and part != '.':
            result = result / part
    return result.resolve()
