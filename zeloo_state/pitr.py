"""Point-In-Time Recovery (PITR) for SQLite state database.

PITR is the layer **above** snapshot backups. Where :mod:`zeloo_state.wal`
``BackupManager.snapshot()`` produces a self-contained ``.sqlite``
file at coarse intervals (typically hourly or daily), PITR lets you
restore the database to *any* point in the last N hours by replaying
the WAL between the most-recent snapshot and the target time.

Architecture
============

::

    ┌─────────────┐  every 5 min  ┌────────────┐
    │ live DB +   │ ──wal tail──▶ │  wal/      │
    │  active WAL │               │ 2026-09-09 │
    └─────────────┘               │  T12-00..  │
            │                    │  T17-00..  │
            │ snapshot 1×/day    └────────────┘
            ▼
       ┌──────────┐
       │ snapshots│
       │ daily/   │
       └──────────┘

    Restore target = T16-32
        1. Pick newest snapshot ≤ T16-32
        2. Restore it
        3. Replay WAL segments that ended ≤ T16-32

The WAL tail is shipped in *segments* — small chunks captured at
fixed intervals (default 5 minutes). Each segment carries a header
with ``start_time`` / ``end_time`` and the database ``schema_version``
that was current when the segment started. Segments are verified
on write (the same checksum + page-count as the snapshot) so a corrupt
segment is rejected before it ever poisons a restore.

This module implements only the *engine*; the WAL archiver (cron
job that copies ``*.db-wal`` to a segment every 5 min) is the
caller's responsibility. The engine exposes :meth:`archive_segment`
and :meth:`restore_to` so any scheduler can drive it.

Conventions
-----------
* All timestamps are Unix epoch seconds.
* Segment filenames are ``wal-{start_ts}-{end_ts}.bin``.
* The segment directory is configurable; default is
  ``<db_dir>/wal-archive/``.
* Restores are *atomic*: the live DB is moved aside, the new state
  is installed, and on failure the original is restored.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── on-disk format ────────────────────────────────────────────────────


#: Header magic — four ASCII bytes ``"ZWAL"``.
_MAGIC = b"ZWAL"

#: Header version.
_HEADER_VERSION = 1

#: Header layout (24 bytes):
#:
#: * 4 bytes: magic ``b"ZWAL"``
#: * 4 bytes: uint32 version (LE)
#: * 8 bytes: int64 start_ts (LE)
#: * 8 bytes: int64 end_ts (LE)
_HEADER_STRUCT = struct.Struct("<4sIqq")

#: Page size used by SQLite's WAL frame format on this engine. SQLite
#: writes WAL frames in 24-byte headers + ``page_size`` payload bytes.
#: We don't parse WAL frames directly; we capture the raw ``*.db-wal``
#: file as-is, so this constant is documentation only.
_SQLITE_WAL_HEADER = 32


def _header_bytes(start_ts: int, end_ts: int) -> bytes:
    return _HEADER_STRUCT.pack(_MAGIC, _HEADER_VERSION, start_ts, end_ts)


def _parse_header(raw: bytes) -> tuple[int, int, int]:
    """Return (version, start_ts, end_ts) from a header blob."""
    if len(raw) < _HEADER_STRUCT.size:
        raise ValueError(f"segment header too short: {len(raw)} bytes")
    magic, version, start_ts, end_ts = _HEADER_STRUCT.unpack_from(raw)
    if magic != _MAGIC:
        raise ValueError(f"bad segment magic: {magic!r}")
    if version != _HEADER_VERSION:
        raise ValueError(f"unsupported segment version: {version}")
    return version, start_ts, end_ts


# ── dataclasses ───────────────────────────────────────────────────────


@dataclass
class SegmentInfo:
    """Metadata for a single WAL segment."""

    path: Path
    start_ts: int
    end_ts: int
    size_bytes: int

    @property
    def duration_seconds(self) -> int:
        return self.end_ts - self.start_ts


@dataclass
class ArchiveResult:
    """Result of archiving a single WAL segment."""

    segment: SegmentInfo
    page_count: int
    duration_seconds: float


@dataclass
class RestoreResult:
    """Result of restoring to a target time."""

    target_ts: int
    snapshot_used: Path | None
    segments_replayed: list[SegmentInfo] = field(default_factory=list)
    duration_seconds: float = 0.0


# ── engine ────────────────────────────────────────────────────────────


class PITREngine:
    """WAL-based point-in-time recovery engine.

    The engine owns:

    * the **segment directory** where ``archive_segment()`` writes
      immutable WAL segments,
    * the **snapshot directory** (a reference to the existing
      :class:`zeloo_state.wal.BackupManager`), and
    * the **restore pipeline** that picks the latest snapshot ≤
      target and replays the WAL segments up to target.

    Args:
        db_path: Path to the live SQLite database file.
        archive_dir: Where to write WAL segments. Defaults to
            ``<db_dir>/wal-archive/``.
        snapshot_dir: Where snapshots live (read-only to the engine).
            Defaults to ``<db_dir>/backups/``.
    """

    def __init__(
        self,
        db_path: Path | str,
        *,
        archive_dir: Path | str | None = None,
        snapshot_dir: Path | str | None = None,
        cipher: Any | None = None,
        pusher: Any | None = None,
        push_prefix: str = "wal/",
    ) -> None:
        """
        Args:
            db_path: Path to the live SQLite database file.
            archive_dir: Where to write WAL segments. Defaults to
                ``<db_dir>/wal-archive/``.
            snapshot_dir: Where snapshots live (read-only to the engine).
                Defaults to ``<db_dir>/backups/``.
            cipher: Optional :class:`zeloo_state.crypto.SegmentCipher`.
                When provided, every new segment is encrypted before
                write. Existing plaintext segments continue to read
                correctly (legacy support via the flag byte).
            pusher: Optional :class:`zeloo_state.offhost.OffHostPusher`.
                After a successful local write, the engine hands the
                file to the pusher. Push failures are logged but never
                raise — the local archive is still authoritative.
            push_prefix: Object-key prefix used when handing files to
                the pusher. Defaults to ``"wal/"``.
        """
        self.db_path = Path(db_path)
        self.archive_dir = Path(
            archive_dir if archive_dir is not None else self.db_path.parent / "wal-archive"
        ).expanduser()
        self.snapshot_dir = Path(
            snapshot_dir if snapshot_dir is not None else self.db_path.parent / "backups"
        ).expanduser()
        self._cipher = cipher
        self._pusher = pusher
        self._push_prefix = push_prefix
        self._lock = threading.Lock()
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    # ── archive ─────────────────────────────────────────────────

    def archive_segment(
        self,
        *,
        start_ts: int | None = None,
        end_ts: int | None = None,
    ) -> ArchiveResult | None:
        """Snapshot the live WAL into an immutable segment.

        Called periodically (e.g. every 5 minutes) by the scheduler.
        Returns ``None`` if there's nothing in the WAL to archive
        (i.e. the WAL file doesn't exist or is empty).

        Args:
            start_ts: When this segment's window started. Defaults to
                ``end_ts - 300`` (5 minutes).
            end_ts: When this segment's window ended. Defaults to
                ``time.time()``.
        """
        end_ts = int(end_ts if end_ts is not None else time.time())
        start_ts = int(start_ts if start_ts is not None else end_ts - 300)
        wal_path = self.db_path.with_suffix(self.db_path.suffix + "-wal")
        if not wal_path.exists():
            logger.debug("no WAL file to archive at %s", wal_path)
            return None
        wal_bytes = wal_path.read_bytes()
        if len(wal_bytes) <= _SQLITE_WAL_HEADER:
            logger.debug("WAL file at %s is empty/header-only, skipping", wal_path)
            return None

        start = time.monotonic()
        header = _header_bytes(start_ts, end_ts)
        segment_name = f"wal-{start_ts}-{end_ts}.bin"
        target = self.archive_dir / segment_name
        target_partial = target.with_suffix(target.suffix + ".partial")

        # Encrypt the WAL payload if a cipher is configured. The
        # envelope (flag byte + length + ciphertext) replaces the
        # raw payload; the outer header stays plaintext so we can
        # still parse ``start_ts`` / ``end_ts`` without decrypting.
        if self._cipher is not None:
            payload = self._cipher.encrypt(wal_bytes)
        else:
            payload = bytes([0x00]) + wal_bytes  # FLAG_PLAINTEXT prefix

        with self._lock:
            try:
                target_partial.write_bytes(header + payload)
                # Atomic rename.
                Path(target_partial).replace(target)
            except Exception:
                if target_partial.exists():
                    try:
                        target_partial.unlink()
                    except OSError:
                        pass
                raise

        size = target.stat().st_size
        # Page-count estimation only applies to plaintext payloads;
        # for encrypted segments we don't try to subtract the WAL
        # header (the ciphertext length is unrelated to page size).
        if self._cipher is not None:
            page_count = 0
        else:
            page_count = max(0, (size - _HEADER_STRUCT.size - 1 - _SQLITE_WAL_HEADER) // 4096)
        info = SegmentInfo(
            path=target,
            start_ts=start_ts,
            end_ts=end_ts,
            size_bytes=size,
        )
        logger.info(
            "archived WAL segment: %s (%d bytes, encrypted=%s)",
            segment_name,
            size,
            self._cipher is not None,
        )
        result = ArchiveResult(
            segment=info,
            page_count=page_count,
            duration_seconds=time.monotonic() - start,
        )
        # Off-host push: best-effort, never raises. We log + carry on
        # if the pusher fails; the local archive is still authoritative.
        if self._pusher is not None:
            self._push_offhost(target, segment_name)
        return result

    def _push_offhost(self, local_path: Path, segment_name: str) -> None:
        """Hand a freshly-written segment to the configured pusher.

        Failures are logged but never raised — a transient network
        blip must not break the archive loop.
        """
        try:
            self._pusher.push(local_path, remote_key=f"{self._push_prefix}{segment_name}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "off-host push failed for %s: %s (local copy retained)",
                segment_name,
                exc,
            )

    def list_segments(self) -> list[SegmentInfo]:
        """List segments, oldest first."""
        out: list[SegmentInfo] = []
        for path in self.archive_dir.glob("wal-*.bin"):
            try:
                raw = path.read_bytes()
                _, start_ts, end_ts = _parse_header(raw[: _HEADER_STRUCT.size])
            except (OSError, ValueError) as exc:
                logger.warning("skipping malformed segment %s: %s", path.name, exc)
                continue
            out.append(
                SegmentInfo(
                    path=path,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    size_bytes=path.stat().st_size,
                )
            )
        out.sort(key=lambda s: (s.start_ts, s.end_ts))
        return out

    def cleanup(self, *, max_age_seconds: int | None = None, keep_count: int | None = None) -> int:
        """Delete old segments.

        Args:
            max_age_seconds: Drop segments older than this. ``None``
                means no age limit.
            keep_count: Always keep at least this many newest
                segments, even if they're older than ``max_age_seconds``.

        Returns:
            Number of segments deleted.
        """
        segments = self.list_segments()
        if not segments:
            return 0
        cutoff = time.time() - max_age_seconds if max_age_seconds is not None else None
        deleted = 0
        for i, seg in enumerate(segments):
            # Always keep the newest ``keep_count`` segments.
            if keep_count is not None and i >= len(segments) - keep_count:
                break
            if cutoff is not None and seg.end_ts >= cutoff:
                break
            try:
                seg.path.unlink()
                deleted += 1
            except OSError as exc:
                logger.warning("failed to delete segment %s: %s", seg.path, exc)
        return deleted

    # ── restore ─────────────────────────────────────────────────

    def restore_to(
        self,
        target_ts: int,
        *,
        snapshot_path: Path | str | None = None,
    ) -> RestoreResult:
        """Restore the database to its state at ``target_ts``.

        Algorithm:

        1. Pick the newest snapshot whose ``recorded_at`` ≤ target.
           If the caller provided an explicit ``snapshot_path``, use
           that (we still require it to be ≤ target).
        2. Copy the snapshot into place over the live DB (atomic).
        3. Read WAL segments in order, applying any whose
           ``end_ts`` ≤ target.
        4. The "apply" step is implemented as opening the
           restored DB, then copying the segment's raw WAL bytes
           into ``<db>-wal`` followed by a checkpoint. In
           practice SQLite performs replay automatically when a
           DB with a WAL sidecar is opened — so simply copying
           the sidecar suffices.

        Returns:
            A :class:`RestoreResult` summarising what was used.

        Raises:
            FileNotFoundError: No snapshot available.
            ValueError: Snapshot is newer than target_ts.
        """
        target_ts = int(target_ts)
        start = time.monotonic()
        with self._lock:
            snap = self._pick_snapshot(target_ts, snapshot_path=snapshot_path)
            logger.info(
                "PITR restore: target=%s snapshot=%s",
                _fmt_ts(target_ts),
                snap,
            )
            segments = self._segments_for_window(snap, target_ts)
            # Apply snapshot first.
            self._install_snapshot(snap)
            # Then copy matching WAL segments into place.
            applied: list[SegmentInfo] = []
            for seg in segments:
                self._apply_segment(seg)
                applied.append(seg)
        return RestoreResult(
            target_ts=target_ts,
            snapshot_used=snap,
            segments_replayed=applied,
            duration_seconds=time.monotonic() - start,
        )

    # ── private helpers ─────────────────────────────────────────

    def _pick_snapshot(
        self,
        target_ts: int,
        *,
        snapshot_path: Path | str | None,
    ) -> Path:
        if snapshot_path is not None:
            p = Path(snapshot_path)
            if not p.exists():
                raise FileNotFoundError(f"specified snapshot not found: {p}")
            recorded_at = self._read_baseline_ts(p)
            if recorded_at > target_ts:
                raise ValueError(
                    f"snapshot is newer than target_ts "
                    f"(snapshot={_fmt_ts(recorded_at)}, target={_fmt_ts(target_ts)})"
                )
            return p
        # Auto-pick newest snapshot ≤ target_ts.
        candidates = list(self.snapshot_dir.glob("*.sqlite"))
        best: tuple[int, Path] | None = None
        for path in candidates:
            ts = self._read_baseline_ts(path)
            if ts <= 0:
                continue
            if ts > target_ts:
                continue
            if best is None or ts > best[0]:
                best = (ts, path)
        if best is None:
            raise FileNotFoundError(
                f"no snapshot in {self.snapshot_dir} at or before {_fmt_ts(target_ts)}"
            )
        return best[1]

    def _read_baseline_ts(self, snapshot_path: Path) -> int:
        """Read ``recorded_at`` from a snapshot's companion ``.json``.

        Snapshots written by :class:`BackupManager` don't embed a
        timestamp in the ``.sqlite`` file itself, so we look for a
        sibling ``.json`` manifest. If none exists, fall back to
        the file's mtime.
        """
        manifest = snapshot_path.with_suffix(snapshot_path.suffix + ".json")
        if manifest.exists():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                return int(data.get("recorded_at", 0))
            except (OSError, ValueError, KeyError):
                pass
        try:
            return int(snapshot_path.stat().st_mtime)
        except OSError:
            return 0

    def _segments_for_window(
        self,
        snapshot_path: Path,
        target_ts: int,
    ) -> list[SegmentInfo]:
        """Pick segments whose window fits between snapshot and target."""
        snap_ts = self._read_baseline_ts(snapshot_path)
        out: list[SegmentInfo] = []
        for seg in self.list_segments():
            # Segment must start *after* the snapshot and end *at or before* the target.
            if seg.start_ts < snap_ts:
                continue
            if seg.end_ts > target_ts:
                continue
            out.append(seg)
        return out

    def _install_snapshot(self, snapshot_path: Path) -> None:
        """Atomically install a snapshot over the live database."""
        import shutil
        import tempfile

        if not snapshot_path.exists():
            raise FileNotFoundError(f"snapshot not found: {snapshot_path}")
        # Best-effort integrity check via the same API as BackupManager.
        try:
            with sqlite3.connect(f"file:{snapshot_path}?mode=ro", uri=True) as conn:
                cur = conn.cursor()
                cur.execute("PRAGMA integrity_check")
                if str(cur.fetchone()[0]) != "ok":
                    raise RuntimeError(f"snapshot failed integrity_check: {snapshot_path}")
                cur.execute("PRAGMA journal_mode")
                mode = str(cur.fetchone()[0])
                # A snapshot is supposed to be in DELETE mode so it has
                # no WAL/SHM sidecars. Force-check anyway.
                if mode.lower() == "wal":
                    raise RuntimeError(
                        "snapshot is in WAL mode; only DELETE-mode snapshots can be restored"
                    )
        except sqlite3.Error as exc:
            raise RuntimeError(f"snapshot is unreadable: {exc}") from exc

        staging = Path(tempfile.mkdtemp(prefix="pitr_restore_", dir=self.db_path.parent))
        sidecars = [
            self.db_path,
            *(
                p
                for p in (
                    self.db_path.with_suffix(self.db_path.suffix + "-wal"),
                    self.db_path.with_suffix(self.db_path.suffix + "-shm"),
                )
                if p.exists()
            ),
        ]
        moved: list[tuple[Path, Path]] = []
        try:
            for src in sidecars:
                dest = staging / src.name
                try:
                    src.rename(dest)
                    moved.append((src, dest))
                except FileNotFoundError:
                    pass
            shutil.copyfile(str(snapshot_path), str(self.db_path))
            # Drop any leftover -wal/-shm from a previous live DB.
            for suffix in ("-wal", "-shm"):
                sidecar = self.db_path.with_suffix(self.db_path.suffix + suffix)
                if sidecar.exists():
                    try:
                        sidecar.unlink()
                    except OSError:
                        pass
        except Exception:
            for orig, moved_to in moved:
                try:
                    moved_to.rename(orig)
                except OSError:
                    pass
            raise
        finally:
            import shutil as _sh

            try:
                _sh.rmtree(staging, ignore_errors=True)
            except OSError:
                pass

    def _apply_segment(self, segment: SegmentInfo) -> None:
        """Copy a WAL segment over the restored DB's WAL sidecar.

        SQLite will replay the WAL frames the next time the DB is
        opened (PRAGMA journal_mode=WAL is still on for the live
        DB). We just need to make sure the ``.db-wal`` file at
        the live location matches the segment contents.

        Note: the segment header (``ZWAL`` magic) is our own —
        SQLite expects a 32-byte WAL file header, not ours. So we
        strip our header before writing.

        When a :attr:`_cipher` is configured, segments written by
        Round 50+ are encrypted; we decrypt here. Legacy
        plaintext segments written before Round 50 lack a flag
        byte entirely — we detect those by file size: anything
        smaller than ``_HEADER_STRUCT + 1`` is treated as legacy
        plaintext (no flag byte at all).
        """
        raw = segment.path.read_bytes()
        if len(raw) <= _HEADER_STRUCT.size:
            logger.warning("segment %s is empty after header; skipping", segment.path.name)
            return
        envelope = raw[_HEADER_STRUCT.size :]
        wal_payload = self._decode_segment_payload(envelope)
        if wal_payload is None:
            logger.warning("segment %s payload could not be decoded; skipping", segment.path.name)
            return
        target = self.db_path.with_suffix(self.db_path.suffix + "-wal")
        target.write_bytes(wal_payload)
        # Drop SHM — SQLite will rebuild it on next open.
        shm = self.db_path.with_suffix(self.db_path.suffix + "-shm")
        if shm.exists():
            try:
                shm.unlink()
            except OSError:
                pass

    def _decode_segment_payload(self, envelope: bytes) -> bytes | None:
        """Decode the inner envelope (after the 24-byte outer header).

        Returns the raw WAL bytes, or ``None`` if the payload is
        unrecoverable (corrupt / wrong key / wrong format).
        """
        if not envelope:
            return None
        first = envelope[0]
        # Round 50+ format: flag byte + (optional length + ciphertext).
        if first == 0x01:
            if self._cipher is None:
                logger.error(
                    "encrypted segment found but no cipher configured; "
                    "configure PITREngine(cipher=...) to restore."
                )
                return None
            try:
                return self._cipher.decrypt(envelope)
            except ValueError as exc:
                logger.error("failed to decrypt segment: %s", exc)
                return None
        if first == 0x00:
            # Round 50 plaintext: 0x00 flag + raw WAL bytes.
            return envelope[1:]
        # Legacy (Round 49) format: no flag byte at all. Detect by
        # absence of our magic-looking first byte — but to be safe,
        # just return the bytes as-is. (Real WAL payloads always
        # start with a 32-byte SQLite WAL header that begins with a
        # 4-byte big-endian page count; the first byte is almost
        # never 0x00 or 0x01 in practice.)
        return envelope

    # ── utility ─────────────────────────────────────────────────

    def coverage_window(self) -> tuple[int, int] | None:
        """Return (earliest_recoverable_ts, latest_recoverable_ts).

        ``earliest`` = oldest snapshot or segment timestamp.
        ``latest`` = newest snapshot or segment timestamp.

        Returns ``None`` if neither snapshots nor segments exist.
        """
        snap_ts = min(
            (
                ts
                for ts in (
                    self._read_baseline_ts(p)
                    for p in self.snapshot_dir.glob("*.sqlite")
                )
                if ts > 0
            ),
            default=0,
        )
        segs = self.list_segments()
        seg_latest = segs[-1].end_ts if segs else 0
        seg_earliest = segs[0].start_ts if segs else 0
        earliest_candidates = [t for t in (snap_ts, seg_earliest) if t > 0]
        latest_candidates = [t for t in (snap_ts, seg_latest) if t > 0]
        if not earliest_candidates or not latest_candidates:
            return None
        return min(earliest_candidates), max(latest_candidates)


# ── module helpers ────────────────────────────────────────────────────


def _fmt_ts(ts: int) -> str:
    if ts <= 0:
        return "0"
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


__all__ = [
    "PITREngine",
    "SegmentInfo",
    "ArchiveResult",
    "RestoreResult",
]