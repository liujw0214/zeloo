"""Workspace import/export — share workspace profiles across machines.

A :class:`WorkspaceBundle` is a portable JSON document containing:

* Workspace metadata (name, description, tags, memory_backend)
* Profile settings (``config.yaml``, ``.env`` — with secrets redacted)
* Memory snapshot (``MEMORY.md``, ``USER.md``)
* Skills index (filenames only — actual skills live in their own repos)
* Created-at + version info

Use :func:`export_workspace` to create a bundle from a
:class:`WorkspaceManager` and :func:`import_workspace` to recreate one.
By default secrets in ``.env`` are redacted to ``"<redacted>"`` — pass
``include_secrets=True`` to embed them (only safe for encrypted storage).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "WorkspaceBundle",
    "export_workspace",
    "import_workspace",
    "list_bundle_files",
]

_BUNDLE_VERSION = 1
_SECRET_PATTERN = re.compile(
    r"^(?:[A-Z_][A-Z0-9_]*API_KEY|[A-Z_][A-Z0-9_]*SECRET|[A-Z_][A-Z0-9_]*TOKEN|[A-Z_][A-Z0-9_]*PASSWORD)\s*=\s*(.+)$",
    re.IGNORECASE,
)


def _is_secret_key(key: str) -> bool:
    """Heuristic: return True if the key looks like a credential."""
    upper = key.upper()
    return any(
        marker in upper
        for marker in ("API_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD")
    )


@dataclass
class WorkspaceBundle:
    """A portable, JSON-serializable workspace export."""

    version: int = _BUNDLE_VERSION
    name: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    memory_backend: str = "localfile"
    created_at: float = field(default_factory=time.time)
    files: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self, indent: int = 2) -> str:
        """Serialize the bundle to a JSON string."""
        return json.dumps(
            {
                "version": self.version,
                "name": self.name,
                "description": self.description,
                "tags": self.tags,
                "memory_backend": self.memory_backend,
                "created_at": self.created_at,
                "files": self.files,
                "metadata": self.metadata,
            },
            indent=indent,
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> WorkspaceBundle:
        """Parse a JSON bundle."""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        return cls(
            version=int(data.get("version", _BUNDLE_VERSION)),
            name=data.get("name", ""),
            description=data.get("description", ""),
            tags=list(data.get("tags", [])),
            memory_backend=data.get("memory_backend", "localfile"),
            created_at=float(data.get("created_at", 0.0)),
            files=dict(data.get("files", {})),
            metadata=dict(data.get("metadata", {})),
        )


def _safe_read_text(path: Path, max_bytes: int = 256_000) -> str | None:
    """Read a UTF-8 text file, truncating large files. Returns None on failure."""
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
        if size > max_bytes:
            content = path.read_bytes()[:max_bytes].decode("utf-8", errors="ignore")
            return content + f"\n\n# [truncated, original size: {size} bytes]\n"
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.debug("Skipping unreadable file %s: %s", path, exc)
        return None


def _redact_env(content: str) -> tuple[str, int]:
    """Replace secret-like values in an env file with ``"<redacted>"``.

    Returns the redacted content and the number of values redacted.
    """
    redacted = 0
    out_lines: list[str] = []
    for line in content.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            out_lines.append(line)
            continue
        key, _, _value = line.partition("=")
        if _is_secret_key(key):
            out_lines.append(f"{key}=<redacted>")
            redacted += 1
        else:
            out_lines.append(line)
    return "\n".join(out_lines) + ("\n" if content.endswith("\n") else ""), redacted


def export_workspace(
    workspace_root: Path,
    workspace_name: str,
    *,
    include_secrets: bool = False,
    include_skills_index: bool = True,
) -> WorkspaceBundle:
    """Build a :class:`WorkspaceBundle` from an on-disk workspace.

    Args:
        workspace_root: Root containing workspace subdirs
            (e.g. ``~/.Zeloo/workspace``).
        workspace_name: The workspace to export (must be a subdir).
        include_secrets: If False (default), values for keys matching
            ``API_KEY/SECRET/TOKEN/PASSWORD`` are redacted in ``.env``.
        include_skills_index: If True, list local SKILL.md names (not
            their contents) under ``metadata.skills_index``.

    Returns:
        A populated :class:`WorkspaceBundle`.

    Raises:
        FileNotFoundError: if the workspace dir does not exist.
    """
    ws_path = workspace_root / workspace_name
    if not ws_path.is_dir():
        raise FileNotFoundError(f"Workspace not found: {ws_path}")

    metadata_path = ws_path / "metadata.json"
    metadata: dict[str, Any] = {}
    if metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            metadata = {}

    bundle = WorkspaceBundle(
        name=workspace_name,
        description=str(metadata.get("description", "")),
        tags=list(metadata.get("tags", [])),
        memory_backend=str(metadata.get("memory_backend", "localfile")),
        metadata=metadata,
    )

    # Profile files (config.yaml + .env)
    profile_dir = ws_path / "profile"
    for candidate in ("config.yaml", "config.yml"):
        text = _safe_read_text(profile_dir / candidate)
        if text is not None:
            bundle.files[f"profile/{candidate}"] = text

    env_path = profile_dir / ".env"
    env_text = _safe_read_text(env_path)
    if env_text is not None:
        if include_secrets:
            bundle.files["profile/.env"] = env_text
        else:
            redacted, count = _redact_env(env_text)
            bundle.files["profile/.env"] = redacted
            bundle.metadata.setdefault("redacted_secrets", count)

    # Memory files
    memory_dir = ws_path / "memory"
    for candidate in ("MEMORY.md", "USER.md", "SOUL.md"):
        text = _safe_read_text(memory_dir / candidate)
        if text is not None:
            bundle.files[f"memory/{candidate}"] = text

    # Skills index (filenames only)
    if include_skills_index:
        skills_dir = ws_path / "skills"
        if skills_dir.is_dir():
            bundle.metadata["skills_index"] = sorted(
                p.relative_to(skills_dir).as_posix()
                for p in skills_dir.rglob("SKILL.md")
            )

    return bundle


def import_workspace(
    bundle: WorkspaceBundle,
    target_root: Path,
    *,
    overwrite: bool = False,
    secrets: dict[str, str] | None = None,
) -> Path:
    """Recreate a workspace from a :class:`WorkspaceBundle`.

    Args:
        bundle: The bundle to import.
        target_root: Where to create the workspace subdir (e.g.
            ``~/.Zeloo/workspace``).
        overwrite: If True, replace an existing workspace of the same
            name. If False and the workspace exists, raises ``FileExistsError``.
        secrets: Optional mapping of env-var names to plaintext values
            that should replace ``<redacted>`` placeholders in
            ``profile/.env``.

    Returns:
        The path to the recreated workspace dir.
    """
    target = target_root / bundle.name
    if target.exists():
        if not overwrite:
            raise FileExistsError(
                f"Workspace '{bundle.name}' already exists at {target}"
            )
        shutil.rmtree(target)

    target.mkdir(parents=True, exist_ok=True)

    # Restore files
    for rel_path, content in bundle.files.items():
        dst = target / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)

        if (
            rel_path == "profile/.env"
            and secrets
            and "<redacted>" in content
        ):
            content = _apply_secrets(content, secrets)

        dst.write_text(content, encoding="utf-8")

    # Restore metadata.json
    if bundle.metadata or bundle.name:
        metadata = dict(bundle.metadata)
        metadata.setdefault("description", bundle.description)
        metadata.setdefault("tags", bundle.tags)
        metadata.setdefault("memory_backend", bundle.memory_backend)
        metadata["imported_at"] = time.time()
        (target / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return target


def _apply_secrets(env_content: str, secrets: dict[str, str]) -> str:
    """Replace ``<redacted>`` placeholders with values from *secrets*."""
    out: list[str] = []
    for line in env_content.splitlines():
        if not line or "=" not in line:
            out.append(line)
            continue
        key, _, value = line.partition("=")
        if value.strip() == "<redacted>" and key in secrets:
            out.append(f"{key}={secrets[key]}")
        else:
            out.append(line)
    return "\n".join(out)


def list_bundle_files(bundle: WorkspaceBundle) -> list[str]:
    """Return the list of file paths in a bundle, sorted."""
    return sorted(bundle.files.keys())


def export_workspace_to_archive(
    workspace_root: Path,
    workspace_name: str,
    archive_path: str | Path,
    **kwargs: Any,
) -> Path:
    """Export a workspace and bundle it as a ``.tar.zst`` archive.

    Returns the path to the archive.
    """
    bundle = export_workspace(workspace_root, workspace_name, **kwargs)
    archive_path = Path(archive_path)

    with tempfile.NamedTemporaryFile(
        "wb", suffix=".tar", delete=False, dir=tempfile.gettempdir()
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        with tarfile.open(tmp_path, "w") as tar:
            data = bundle.to_json().encode("utf-8")
            info = tarfile.TarInfo(name="workspace.bundle.json")
            info.size = len(data)
            tar.addfile(info, __import__("io").BytesIO(data))
        shutil.move(str(tmp_path), str(archive_path))
        return archive_path
    finally:
        tmp_path.unlink(missing_ok=True)