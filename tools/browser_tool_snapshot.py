"""Browser state snapshot for debugging / replay.

Capture the full DOM, screenshot, network log, console log, cookies and
storage into a single immutable record. Snapshots can be persisted to
disk, reloaded, and diffed to produce human-readable change reports.

Example::

    mgr = SnapshotManager(max_per_session=20)
    snap = mgr.capture("sess-1")
    snap.save(Path("/tmp/snap.json"))
    loaded = BrowserSnapshot.load(Path("/tmp/snap.json"))
    diff = snap.diff(loaded)
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class BrowserSnapshot:
    """Snapshot of browser state at a point in time.

    All fields are mutable on purpose so callers can populate them
    incrementally. Use :meth:`freeze` to mark the snapshot as
    immutable once construction is complete.
    """

    session_id: str
    created_at: float = 0.0
    url: str = ""
    title: str = ""
    dom_html: str = ""
    screenshot_b64: str = ""
    cookies: list[dict[str, Any]] = field(default_factory=list)
    local_storage: dict[str, str] = field(default_factory=dict)
    session_storage: dict[str, str] = field(default_factory=dict)
    network_log: list[dict[str, Any]] = field(default_factory=list)
    console_log: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    _frozen: bool = field(default=False, repr=False, compare=False)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def blank(cls, session_id: str) -> "BrowserSnapshot":
        """Create an empty snapshot with the timestamp filled in."""
        return cls(session_id=session_id, created_at=_now())

    def freeze(self) -> None:
        """Mark the snapshot as immutable (best-effort enforcement)."""
        self._frozen = True

    def is_frozen(self) -> bool:
        return bool(self._frozen)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict (drops the ``_frozen`` flag)."""
        data = asdict(self)
        data.pop("_frozen", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BrowserSnapshot":
        """Inverse of :meth:`to_dict`.

        Unknown keys are ignored so older payloads keep loading even
        after the schema gains fields.
        """
        allowed = {f for f in cls.__dataclass_fields__.keys()}  # type: ignore[attr-defined]
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key not in allowed or key == "_frozen":
                continue
            kwargs[key] = value
        kwargs.setdefault("created_at", _now())
        kwargs.setdefault("session_id", "unknown")
        snap = cls(**kwargs)
        return snap

    def save(self, path: Path, *, compress: bool = False) -> Path:
        """Persist the snapshot to ``path`` (JSON or .json.gz).

        Args:
            path: Destination file path.
            compress: Force gzip even when the suffix doesn't end in .gz.

        Returns:
            The resolved path that was written.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        if compress or path.suffix == ".gz":
            if not path.suffix == ".gz":
                path = path.with_suffix(path.suffix + ".gz")
            with gzip.open(path, "wt", encoding="utf-8") as fh:
                fh.write(payload)
        else:
            with path.open("w", encoding="utf-8") as fh:
                fh.write(payload)
        logger.debug("snapshot_saved path=%s id=%s", path, self.snapshot_id)
        return path

    @classmethod
    def load(cls, path: Path) -> "BrowserSnapshot":
        """Load a snapshot from disk (auto-detects gzip)."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Snapshot not found: {path}")
        opener = gzip.open if path.suffix == ".gz" else _text_open
        with opener(path, "rt", encoding="utf-8") as fh:  # type: ignore[arg-type]
            data = json.load(fh)
        snap = cls.from_dict(data)
        return snap

    # ------------------------------------------------------------------
    # Diffing
    # ------------------------------------------------------------------

    def diff(self, other: "BrowserSnapshot") -> dict[str, Any]:
        """Produce a structured diff against ``other``.

        The diff covers the fields that matter for replay: URL, title,
        DOM HTML, cookies, storage and console log highlights.

        Returns:
            Dict with per-field ``changed`` flags and ``added`` /
            ``removed`` payloads. ``summary`` is a short human string.
        """
        url_changed = self.url != other.url
        title_changed = self.title != other.title
        dom_changed = self.dom_html != other.dom_html

        cookies_a = {json.dumps(c, sort_keys=True) for c in self.cookies}
        cookies_b = {json.dumps(c, sort_keys=True) for c in other.cookies}
        added_cookies = sorted(cookies_b - cookies_a)
        removed_cookies = sorted(cookies_a - cookies_b)

        local_added, local_removed = _dict_diff(
            self.local_storage, other.local_storage
        )
        session_added, session_removed = _dict_diff(
            self.session_storage, other.session_storage
        )

        console_added = _list_diff(self.console_log, other.console_log)
        network_added = _list_diff(self.network_log, other.network_log)

        return {
            "session_id": self.session_id,
            "from_id": self.snapshot_id,
            "to_id": other.snapshot_id,
            "url": {"from": self.url, "to": other.url, "changed": url_changed},
            "title": {"from": self.title, "to": other.title, "changed": title_changed},
            "dom_html": {"changed": dom_changed, "size_a": len(self.dom_html), "size_b": len(other.dom_html)},
            "cookies": {
                "added": [json.loads(x) for x in added_cookies],
                "removed": [json.loads(x) for x in removed_cookies],
                "changed": bool(added_cookies or removed_cookies),
            },
            "local_storage": {
                "added": local_added,
                "removed": local_removed,
                "changed": bool(local_added or local_removed),
            },
            "session_storage": {
                "added": session_added,
                "removed": session_removed,
                "changed": bool(session_added or session_removed),
            },
            "console_log": {
                "added_count": len(console_added),
                "added": console_added[:20],
                "changed": bool(console_added),
            },
            "network_log": {
                "added_count": len(network_added),
                "added": network_added[:20],
                "changed": bool(network_added),
            },
            "summary": _summarise_diff(
                url_changed, title_changed, dom_changed,
                bool(added_cookies or removed_cookies),
                bool(local_added or local_removed),
                bool(session_added or session_removed),
                bool(console_added),
                bool(network_added),
            ),
        }


# ---------------------------------------------------------------------------
# Snapshot manager
# ---------------------------------------------------------------------------


class SnapshotManager:
    """Manage browser snapshots per session.

    Snapshots are stored in-memory by default; passing ``persist_dir``
    also writes each captured snapshot to disk for later inspection.

    Concurrency:
        All mutations are guarded by a single asyncio lock so the
        manager is safe to share across async tasks in the same loop.
    """

    def __init__(
        self,
        max_per_session: int = 20,
        persist_dir: Path | None = None,
    ) -> None:
        """Initialize the manager.

        Args:
            max_per_session: Hard cap on stored snapshots per session
                (FIFO eviction).
            persist_dir: Optional directory to write JSON snapshots to.
        """
        if max_per_session <= 0:
            raise ValueError("max_per_session must be positive")
        self.max_per_session: int = int(max_per_session)
        self.persist_dir: Path | None = (
            Path(persist_dir).expanduser() if persist_dir else None
        )
        self._snapshots: dict[str, list[BrowserSnapshot]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    async def capture(
        self,
        session_id: str,
        *,
        url: str = "",
        title: str = "",
        dom_html: str = "",
        screenshot_bytes: bytes | None = None,
        cookies: list[dict[str, Any]] | None = None,
        local_storage: dict[str, str] | None = None,
        session_storage: dict[str, str] | None = None,
        network_log: list[dict[str, Any]] | None = None,
        console_log: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        freeze: bool = True,
    ) -> BrowserSnapshot:
        """Capture a new snapshot for ``session_id``.

        Args:
            session_id: Owning session.
            url: Current URL.
            title: Current document title.
            dom_html: Outer HTML of the page.
            screenshot_bytes: Raw image bytes (will be base64-encoded).
            cookies: Cookie list (Playwright-style dicts).
            local_storage: window.localStorage contents.
            session_storage: window.sessionStorage contents.
            network_log: Network request log entries.
            console_log: Console messages.
            metadata: Free-form metadata.
            freeze: If True, mark the snapshot immutable on capture.

        Returns:
            The newly captured snapshot.
        """
        snap = BrowserSnapshot(
            session_id=session_id,
            created_at=_now(),
            url=url,
            title=title,
            dom_html=dom_html,
            screenshot_b64=_encode_bytes(screenshot_bytes),
            cookies=list(cookies or []),
            local_storage=dict(local_storage or {}),
            session_storage=dict(session_storage or {}),
            network_log=list(network_log or []),
            console_log=list(console_log or []),
            metadata=dict(metadata or {}),
        )
        if freeze:
            snap.freeze()

        async with self._lock:
            bucket = self._snapshots.setdefault(session_id, [])
            bucket.append(snap)
            while len(bucket) > self.max_per_session:
                bucket.pop(0)

        if self.persist_dir is not None:
            try:
                fname = (
                    f"{session_id}_{int(snap.created_at * 1000)}_"
                    f"{snap.snapshot_id[:8]}.json"
                )
                snap.save(self.persist_dir / fname)
            except OSError as exc:  # pragma: no cover - disk errors
                logger.warning("snapshot_persist_failed err=%s", exc)

        logger.debug(
            "snapshot_captured session=%s id=%s url=%s",
            session_id,
            snap.snapshot_id,
            url,
        )
        return snap

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get(
        self,
        session_id: str,
        index: int = -1,
    ) -> BrowserSnapshot | None:
        """Return a snapshot by ordinal position.

        Args:
            session_id: Session identifier.
            index: 0-based index, or negative for ``-1`` (latest).

        Returns:
            The matching snapshot, or ``None`` if missing.
        """
        bucket = self._snapshots.get(session_id)
        if not bucket:
            return None
        if index < 0:
            index = len(bucket) + index
        if index < 0 or index >= len(bucket):
            return None
        return bucket[index]

    def list(self, session_id: str) -> list[BrowserSnapshot]:
        """Return every snapshot for ``session_id`` in chronological order."""
        return list(self._snapshots.get(session_id, ()))

    def latest(self, session_id: str) -> BrowserSnapshot | None:
        """Return the most recent snapshot for ``session_id``."""
        bucket = self._snapshots.get(session_id)
        if not bucket:
            return None
        return bucket[-1]

    def sessions(self) -> list[str]:
        """Return all known session IDs."""
        return list(self._snapshots.keys())

    def total(self) -> int:
        """Return the total number of snapshots across all sessions."""
        return sum(len(b) for b in self._snapshots.values())

    def diff_latest(self, session_id: str) -> dict[str, Any] | None:
        """Diff the two most recent snapshots for ``session_id``."""
        bucket = self._snapshots.get(session_id)
        if not bucket or len(bucket) < 2:
            return None
        return bucket[-2].diff(bucket[-1])

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def clear(self, session_id: str) -> int:
        """Drop every snapshot for ``session_id``.

        Returns:
            The number of snapshots removed.
        """
        bucket = self._snapshots.get(session_id)
        if not bucket:
            return 0
        removed = len(bucket)
        del self._snapshots[session_id]
        return removed

    def clear_all(self) -> int:
        """Drop every snapshot. Returns the number removed."""
        removed = sum(len(b) for b in self._snapshots.values())
        self._snapshots.clear()
        return removed

    def export(self, session_id: str) -> list[dict[str, Any]]:
        """Return plain-dict copies of every snapshot for ``session_id``."""
        return [s.to_dict() for s in self.list(session_id)]

    def prune_to(self, session_id: str, count: int) -> int:
        """Keep only the last ``count`` snapshots for ``session_id``.

        Returns:
            The number of snapshots removed.
        """
        bucket = self._snapshots.get(session_id)
        if not bucket:
            return 0
        if count <= 0:
            removed = len(bucket)
            del self._snapshots[session_id]
            return removed
        if len(bucket) <= count:
            return 0
        removed = len(bucket) - count
        self._snapshots[session_id] = bucket[-count:]
        return removed

    # ------------------------------------------------------------------
    # Disk helpers
    # ------------------------------------------------------------------

    def load_from_disk(self, path: Path) -> BrowserSnapshot:
        """Load a snapshot from disk and register it under its session."""
        snap = BrowserSnapshot.load(Path(path))
        bucket = self._snapshots.setdefault(snap.session_id, [])
        bucket.append(snap)
        return snap

    def export_dir(self, target_dir: Path) -> int:
        """Bulk-export every snapshot to ``target_dir``. Returns count."""
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for session_id, bucket in self._snapshots.items():
            for snap in bucket:
                fname = f"{session_id}_{int(snap.created_at * 1000)}_{snap.snapshot_id[:8]}.json"
                snap.save(target_dir / fname)
                count += 1
        return count


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _text_open(path: Path, mode: str, encoding: str):  # pragma: no cover - trivial
    return path.open(mode, encoding=encoding)


def _now() -> float:
    return time.time()


def _encode_bytes(data: bytes | None) -> str:
    if not data:
        return ""
    import base64

    return base64.b64encode(bytes(data)).decode("ascii")


def _decode_b64(text: str) -> bytes:
    if not text:
        return b""
    import base64

    return base64.b64decode(text.encode("ascii"))


def _dict_diff(
    a: dict[str, str], b: dict[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    added = {k: v for k, v in b.items() if k not in a or a[k] != v}
    removed = {k: a[k] for k in a if k not in b}
    return added, removed


def _list_diff(a: Iterable[dict[str, Any]], b: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return entries present in ``b`` but not in ``a`` (JSON-keyed)."""
    a_set = {json.dumps(x, sort_keys=True) for x in a}
    out: list[dict[str, Any]] = []
    for y in b:
        key = json.dumps(y, sort_keys=True)
        if key not in a_set:
            out.append(json.loads(key))
    return out


def _summarise_diff(
    url_changed: bool,
    title_changed: bool,
    dom_changed: bool,
    cookies_changed: bool,
    local_changed: bool,
    session_changed: bool,
    console_changed: bool,
    network_changed: bool,
) -> str:
    flags = []
    if url_changed:
        flags.append("URL")
    if title_changed:
        flags.append("title")
    if dom_changed:
        flags.append("DOM")
    if cookies_changed:
        flags.append("cookies")
    if local_changed:
        flags.append("localStorage")
    if session_changed:
        flags.append("sessionStorage")
    if console_changed:
        flags.append("console")
    if network_changed:
        flags.append("network")
    if not flags:
        return "no changes detected"
    return "changed: " + ", ".join(flags)
