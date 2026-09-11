"""Checkpoint manager — save and restore agent state for resumable runs."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write *data* as JSON to *path* atomically.

    Writes to ``path.with_suffix(path.suffix + '.tmp')`` first, then
    renames over the destination. ``os.replace`` is atomic on POSIX and
    Windows (since Python 3.3) so a crash mid-write can never leave a
    half-written checkpoint on disk.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync may not be supported on some filesystems.
                pass
        os.replace(tmp, path)
    except Exception:
        # Best-effort cleanup of the tmp file on failure.
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


@dataclass
class Checkpoint:
    """Agent state checkpoint for resumable runs."""

    checkpoint_id: str
    session_id: str
    turn_id: int
    messages: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    pending_actions: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    token_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "messages": self.messages,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "pending_actions": self.pending_actions,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "token_count": self.token_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(
            checkpoint_id=data["checkpoint_id"],
            session_id=data["session_id"],
            turn_id=data["turn_id"],
            messages=data["messages"],
            tool_calls=data["tool_calls"],
            tool_results=data["tool_results"],
            pending_actions=data.get("pending_actions", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
            token_count=data.get("token_count", 0),
        )


class CheckpointManager:
    """Save and restore agent checkpoints.

    Persists agent state to disk so long-running tasks can be
    paused and resumed across process restarts.

    Writes go through :func:`_atomic_write_json` so a crash mid-write
    can never corrupt a checkpoint file. The in-memory ``_index`` cache
    lets :meth:`list_checkpoints` skip the per-file JSON parse on every
    call — a hot path when the agent resumes and inspects its history.
    """

    def __init__(self, checkpoint_dir: str | None = None) -> None:
        self.checkpoint_dir = Path(
            checkpoint_dir
            or os.environ.get("zeloo_CHECKPOINT_DIR", "~/.Zeloo/checkpoints")
        ).expanduser()
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        # In-memory cache: ckpt_id -> Checkpoint. Populated lazily by
        # ``list_checkpoints`` and refreshed by ``save`` / ``delete``.
        self._index: dict[str, Checkpoint] = {}
        self._lock = threading.Lock()

    def save(
        self,
        session_id: str,
        turn_id: int,
        messages: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Checkpoint:
        """Save a checkpoint of agent state.

        Uses atomic write (tmp + rename + fsync) so a crash mid-write
        cannot corrupt the file. The previous implementation used
        ``open(path, "w")`` directly, leaving a half-written file on
        crash that ``load()`` could not parse.
        """
        ckpt_id = self._generate_id(session_id, turn_id)
        checkpoint = Checkpoint(
            checkpoint_id=ckpt_id,
            session_id=session_id,
            turn_id=turn_id,
            messages=messages,
            tool_calls=tool_calls or [],
            tool_results=tool_results or [],
            metadata=metadata or {},
            token_count=sum(len(m.get("content", "")) for m in messages) // 4,
        )

        ckpt_path = self.checkpoint_dir / f"{ckpt_id}.json"
        try:
            _atomic_write_json(ckpt_path, checkpoint.to_dict())
            with self._lock:
                self._index[ckpt_id] = checkpoint
            logger.info("Saved checkpoint %s for session %s turn %d",
                        ckpt_id, session_id, turn_id)
            return checkpoint
        except Exception as e:
            logger.error("Failed to save checkpoint %s: %s", ckpt_id, e)
            raise

    def load(self, checkpoint_id: str) -> Checkpoint | None:
        """Load a checkpoint by ID."""
        with self._lock:
            cached = self._index.get(checkpoint_id)
        if cached is not None:
            return cached

        ckpt_path = self.checkpoint_dir / f"{checkpoint_id}.json"
        if not ckpt_path.exists():
            logger.warning("Checkpoint %s not found", checkpoint_id)
            return None
        try:
            with open(ckpt_path, encoding="utf-8") as f:
                data = json.load(f)
            ckpt = Checkpoint.from_dict(data)
            with self._lock:
                self._index[checkpoint_id] = ckpt
            return ckpt
        except Exception as e:
            logger.error("Failed to load checkpoint %s: %s", checkpoint_id, e)
            return None

    def load_latest(self, session_id: str) -> Checkpoint | None:
        """Load the most recent checkpoint for a session."""
        checkpoints = self.list_checkpoints(session_id)
        if not checkpoints:
            return None
        latest = sorted(checkpoints, key=lambda c: c.created_at, reverse=True)[0]
        return self.load(latest.checkpoint_id)

    def list_checkpoints(self, session_id: str | None = None) -> list[Checkpoint]:
        """List all checkpoints, optionally filtered by session.

        Lazy-loads the in-memory index from disk on the first call only.
        Subsequent calls return from the cache without touching disk,
        avoiding an O(n) JSON parse loop on every resume / inspect.
        """
        with self._lock:
            cached = bool(self._index)
        if not cached:
            self._refresh_index()

        with self._lock:
            all_ckpts = list(self._index.values())

        if session_id is not None:
            all_ckpts = [c for c in all_ckpts if c.session_id == session_id]
        return sorted(all_ckpts, key=lambda c: c.created_at, reverse=True)

    def delete(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint."""
        ckpt_path = self.checkpoint_dir / f"{checkpoint_id}.json"
        removed = False
        if ckpt_path.exists():
            ckpt_path.unlink()
            removed = True
        # Also clean up any stale .tmp file.
        tmp = ckpt_path.with_suffix(ckpt_path.suffix + ".tmp")
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        with self._lock:
            self._index.pop(checkpoint_id, None)
        return removed

    def cleanup_old(self, keep_latest: int = 5) -> int:
        """Remove old checkpoints, keeping only the N most recent per session."""
        all_ckpts = self.list_checkpoints()
        # Group by session, sort by created_at desc, drop all but keep_latest.
        by_session: dict[str, list[Checkpoint]] = {}
        for c in all_ckpts:
            by_session.setdefault(c.session_id, []).append(c)

        removed = 0
        for ckpts in by_session.values():
            ckpts.sort(key=lambda c: c.created_at, reverse=True)
            for old in ckpts[keep_latest:]:
                if self.delete(old.checkpoint_id):
                    removed += 1
                    logger.info("Removed old checkpoint %s", old.checkpoint_id)
        return removed

    def _refresh_index(self) -> None:
        """Rebuild the in-memory index from on-disk files."""
        loaded: dict[str, Checkpoint] = {}
        for path in self.checkpoint_dir.glob("*.json"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                ckpt = Checkpoint.from_dict(data)
                loaded[ckpt.checkpoint_id] = ckpt
            except Exception as e:
                logger.warning("Skipped corrupted checkpoint %s: %s", path.name, e)
        with self._lock:
            self._index = loaded

    def _generate_id(self, session_id: str, turn_id: int) -> str:
        timestamp = int(time.time() * 1000)
        content = f"{session_id}-{turn_id}-{timestamp}"
        return f"ckpt_{hashlib.md5(content.encode()).hexdigest()[:12]}"


__all__ = ["Checkpoint", "CheckpointManager"]