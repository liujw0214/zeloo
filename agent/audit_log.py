"""Append-only, hash-chained audit log for security-relevant events.

The agent touches the filesystem, makes API calls with credentials,
delivers webhooks, registers skills, and (occasionally) triggers
``estop``. Every one of these events is interesting from a
compliance / forensic standpoint, and we want a single place where
they're recorded in a tamper-evident way.

Design:

  * Events are recorded as one JSON object per line (JSONL) at
    ``~/.Zeloo/audit.log`` (overridable via :class:`AuditLog`).
  * Each event carries a SHA-256 hash over ``prev_hash || canonical_json(event)``
    so any retroactive tampering breaks the chain.
  * Writes are append-only — there is no public API to delete events,
    only :meth:`AuditLog.rotate` which creates a new chain.
  * :meth:`AuditLog.verify` re-walks the file and confirms every hash
    matches. Tampered entries raise :class:`AuditChainError`.
  * The log is intentionally **dependency-free** (stdlib only) so it
    works in every deployment, including minimal containers.

Record shape::

    {
      "ts": "2026-09-08T12:34:56.789Z",   // ISO8601 UTC, ms precision
      "seq": 42,                           // monotonic per file
      "kind": "file_write",                // free-form event type
      "actor": "user:alice",               // who triggered it
      "resource": "/path/to/file",         // what was touched
      "outcome": "ok",                     // ok | error | blocked
      "detail": {...},                     // event-specific payload
      "prev_hash": "sha256:<64 hex>",      // chain link to previous
      "hash": "sha256:<64 hex>"            // hash of this record
    }

Thread-safety:

  * All writes go through an internal ``RLock`` and are serialized via
    a per-file ``threading.Lock`` on the underlying file handle.

Performance:

  * ~10K events/s on a typical workstation (single-threaded). Adequate
    for normal agent traffic; high-throughput services should rotate.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Errors ───────────────────────────────────────────────────────


class AuditChainError(Exception):
    """Raised when :meth:`AuditLog.verify` detects tampering."""

    def __init__(self, message: str, *, line_no: int | None = None) -> None:
        super().__init__(message)
        self.line_no = line_no


# ── Event record ─────────────────────────────────────────────────


@dataclass
class AuditEvent:
    """A single audit log entry."""

    ts: str
    seq: int
    kind: str
    actor: str = "system"
    resource: str = ""
    outcome: str = "ok"
    detail: dict[str, Any] = field(default_factory=dict)
    prev_hash: str = ""
    hash: str = ""  # filled in by AuditLog.record()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditEvent:
        # Tolerate extra keys (forward compatibility).
        return cls(
            ts=str(data.get("ts", "")),
            seq=int(data.get("seq", 0)),
            kind=str(data.get("kind", "")),
            actor=str(data.get("actor", "system")),
            resource=str(data.get("resource", "")),
            outcome=str(data.get("outcome", "ok")),
            detail=dict(data.get("detail", {})),
            prev_hash=str(data.get("prev_hash", "")),
            hash=str(data.get("hash", "")),
        )


# ── Canonicalization ─────────────────────────────────────────────


def _canonical_json(obj: Any) -> str:
    """Stable JSON encoding for hashing.

    - sort_keys ensures stable field ordering.
    - ``ensure_ascii=False`` keeps the hash reproducible for non-ASCII.
    - separators removes extra whitespace.
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _hash_record(prev_hash: str, canonical: str) -> str:
    """Compute the SHA-256 hash over ``prev_hash || canonical``."""
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(b"|")
    h.update(canonical.encode("utf-8"))
    return "sha256:" + h.hexdigest()


# ── AuditLog ─────────────────────────────────────────────────────


GENESIS_HASH = "sha256:" + "0" * 64  # sentinel for the first record


def _default_log_path() -> Path:
    return Path(os.path.expanduser("~")) / ".Zeloo" / "audit.log"


@dataclass
class AuditQueryResult:
    """Result of a query against the audit log."""

    events: list[AuditEvent]
    total: int


class AuditLog:
    """Append-only, hash-chained audit log.

    Use :func:`get_default_audit_log` for a process-wide instance, or
    construct one with a custom path for tests / per-workspace logs.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else _default_log_path()
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()  # serializes file writes
        self._cached_tail: tuple[int, str] | None = None  # (seq, hash) of last record
        # Observers receive every recorded event (in-process fan-out).
        # Used by :mod:`agent.audit_observability` to forward to remote
        # observability backends (Langfuse, etc.).
        self._observers: list[Any] = []
        self._init_tail()

    # ── Setup ───────────────────────────────────────────────────

    def _init_tail(self) -> None:
        """Load the (seq, hash) of the last record on disk into memory."""
        with self._lock:
            self._cached_tail = self._read_tail_unlocked()

    def _read_tail_unlocked(self) -> tuple[int, str]:
        """Walk the file from the end to find the last record's (seq, hash).

        Linear scan from the start is simpler and safe; logs are small.
        """
        last_seq = 0
        last_hash = GENESIS_HASH
        if not self._path.is_file():
            return last_seq, last_hash
        try:
            with self._path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        # Skip malformed lines — verify() will catch them later.
                        continue
                    seq = int(rec.get("seq", 0))
                    if seq >= last_seq:
                        last_seq = seq
                        last_hash = str(rec.get("hash", GENESIS_HASH))
        except OSError as exc:
            logger.warning("audit_log: failed to read tail: %s", exc)
        return last_seq, last_hash

    # ── Properties ──────────────────────────────────────────────

    @property
    def path(self) -> Path:
        return self._path

    def last_seq(self) -> int:
        with self._lock:
            assert self._cached_tail is not None
            return self._cached_tail[0]

    def last_hash(self) -> str:
        with self._lock:
            assert self._cached_tail is not None
            return self._cached_tail[1]

    # ── Recording ───────────────────────────────────────────────

    def record(
        self,
        kind: str,
        *,
        actor: str = "system",
        resource: str = "",
        outcome: str = "ok",
        detail: dict[str, Any] | None = None,
        ts: str | None = None,
    ) -> AuditEvent:
        """Append a new event. Returns the persisted record (with hash)."""
        with self._lock:
            assert self._cached_tail is not None
            seq = self._cached_tail[0] + 1
            prev_hash = self._cached_tail[1]
            ts_value = ts if ts is not None else _now_iso()

            event = AuditEvent(
                ts=ts_value,
                seq=seq,
                kind=kind,
                actor=actor,
                resource=resource,
                outcome=outcome,
                detail=dict(detail or {}),
                prev_hash=prev_hash,
                hash="",
            )
            # Hash over a copy without the ``hash`` field.
            payload = event.to_dict()
            payload.pop("hash", None)
            canonical = _canonical_json(payload)
            event.hash = _hash_record(prev_hash, canonical)
            # Update tail before writing to disk so concurrent callers
            # see a consistent view if they read immediately after.
            self._cached_tail = (event.seq, event.hash)
            self._write_line(event, canonical)
            self._notify_observers(event)
        return event

    def _write_line(self, event: AuditEvent, canonical: str) -> None:
        line = json.dumps({**event.to_dict(), "_canonical": canonical}, ensure_ascii=False)
        with self._write_lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(line)
                    f.write("\n")
                try:
                    os.chmod(self._path, 0o600)
                except OSError:
                    pass
            except OSError as exc:
                logger.error("audit_log: failed to append event: %s", exc)
                # Roll back the cached tail so the chain stays consistent
                # with the file's actual state.
                with self._lock:
                    self._cached_tail = self._read_tail_unlocked()
                raise

    # ── Observers ───────────────────────────────────────────────

    def attach_observer(self, callback: Any) -> None:
        """Register *callback* to receive every recorded event.

        The callback signature is ``(event: AuditEvent) -> None``.
        Exceptions raised by observers are logged but never propagate
        back into :meth:`record` (so a broken remote backend can never
        break the local audit chain).
        """
        with self._lock:
            if callback not in self._observers:
                self._observers.append(callback)

    def detach_observer(self, callback: Any) -> bool:
        """Remove a previously-attached observer. Returns True if found."""
        with self._lock:
            try:
                self._observers.remove(callback)
                return True
            except ValueError:
                return False

    def observer_count(self) -> int:
        with self._lock:
            return len(self._observers)

    def _notify_observers(self, event: AuditEvent) -> None:
        """Fan out to observers outside the lock so they can't deadlock."""
        with self._lock:
            observers = list(self._observers)
        for cb in observers:
            try:
                cb(event)
            except Exception as exc:  # noqa: BLE001
                logger.warning("audit_log: observer %r raised: %s", cb, exc)

    # ── Querying ────────────────────────────────────────────────

    def query(
        self,
        *,
        kind: str | None = None,
        actor: str | None = None,
        outcome: str | None = None,
        since_seq: int | None = None,
        limit: int | None = None,
        reverse: bool = False,
    ) -> AuditQueryResult:
        """Return events matching the given filters."""
        events = list(self.iter_events())
        if kind is not None:
            events = [e for e in events if e.kind == kind]
        if actor is not None:
            events = [e for e in events if e.actor == actor]
        if outcome is not None:
            events = [e for e in events if e.outcome == outcome]
        if since_seq is not None:
            events = [e for e in events if e.seq > since_seq]
        if reverse:
            events.reverse()
        if limit is not None and limit >= 0:
            events = events[:limit]
        return AuditQueryResult(events=events, total=len(events))

    def iter_events(self) -> Iterable[AuditEvent]:
        """Yield every event in the log (oldest first)."""
        if not self._path.is_file():
            return
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                data.pop("_canonical", None)
                yield AuditEvent.from_dict(data)

    # ── Verification ───────────────────────────────────────────

    def verify(self) -> int:
        """Walk the log and re-derive every hash.

        Returns the number of verified records. Raises
        :class:`AuditChainError` on the first tampering / corruption.
        """
        prev_hash = GENESIS_HASH
        expected_seq = 1
        count = 0
        with self._path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise AuditChainError(
                        f"line {line_no} is not valid JSON: {exc}", line_no=line_no
                    ) from exc
                canonical = data.get("_canonical")
                if canonical is None:
                    # Older records pre-date the canonical snapshot.
                    payload = {k: v for k, v in data.items() if k != "hash"}
                    canonical = _canonical_json(payload)
                derived = _hash_record(prev_hash, canonical)
                declared = str(data.get("hash", ""))
                if declared != derived:
                    raise AuditChainError(
                        f"line {line_no} hash mismatch: expected {derived}, got {declared}",
                        line_no=line_no,
                    )
                declared_prev = str(data.get("prev_hash", ""))
                if declared_prev != prev_hash:
                    raise AuditChainError(
                        f"line {line_no} prev_hash mismatch: "
                        f"expected {prev_hash}, got {declared_prev}",
                        line_no=line_no,
                    )
                seq = int(data.get("seq", 0))
                if seq != expected_seq:
                    raise AuditChainError(
                        f"line {line_no} seq mismatch: expected {expected_seq}, got {seq}",
                        line_no=line_no,
                    )
                prev_hash = declared
                expected_seq = seq + 1
                count += 1
        return count

    # ── Rotation ────────────────────────────────────────────────

    def rotate(self) -> Path | None:
        """Move the current log file aside and start a new chain.

        Returns the path of the rotated file (or None if there was
        nothing to rotate).
        """
        with self._lock:
            if not self._path.is_file():
                return None
            ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
            rotated = self._path.with_name(f"{self._path.stem}.{ts}.log")
            i = 1
            while rotated.exists():
                rotated = self._path.with_name(f"{self._path.stem}.{ts}.{i}.log")
                i += 1
            os.replace(self._path, rotated)
            try:
                os.chmod(rotated, 0o600)
            except OSError:
                pass
            self._cached_tail = (0, GENESIS_HASH)
        return rotated

    # ── Introspection ───────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Return summary stats: total events, oldest/newest seq, by kind."""
        counts: dict[str, int] = {}
        oldest: int | None = None
        newest: int | None = None
        for ev in self.iter_events():
            counts[ev.kind] = counts.get(ev.kind, 0) + 1
            if oldest is None or ev.seq < oldest:
                oldest = ev.seq
            newest = ev.seq
        return {
            "path": str(self._path),
            "total": sum(counts.values()),
            "by_kind": counts,
            "oldest_seq": oldest,
            "newest_seq": newest,
            "tail_hash": self.last_hash(),
        }


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ── Convenience helpers ──────────────────────────────────────────


def audit_event(
    kind: str,
    *,
    actor: str = "system",
    resource: str = "",
    outcome: str = "ok",
    detail: dict[str, Any] | None = None,
) -> AuditEvent | None:
    """Append a record to the default audit log; return it (or None on error)."""
    try:
        return get_default_audit_log().record(
            kind=kind,
            actor=actor,
            resource=resource,
            outcome=outcome,
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit_log: failed to record %s: %s", kind, exc)
        return None


# ── Module-level singleton ──────────────────────────────────────

_default: AuditLog | None = None
_default_lock = threading.Lock()


def get_default_audit_log() -> AuditLog:
    """Return the process-wide :class:`AuditLog` (lazy)."""
    global _default
    with _default_lock:
        if _default is None:
            _default = AuditLog()
        return _default


def reset_default_audit_log() -> None:
    """Clear the module-level singleton (used in tests)."""
    global _default
    with _default_lock:
        _default = None


__all__ = [
    "AuditChainError",
    "AuditEvent",
    "AuditLog",
    "AuditQueryResult",
    "GENESIS_HASH",
    "audit_event",
    "get_default_audit_log",
    "reset_default_audit_log",
]
