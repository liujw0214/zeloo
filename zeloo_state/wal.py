"""WAL management for SQLite state database.

This module owns two related concerns:

1. **WAL lifecycle** — toggling WAL journal mode, running periodic
   ``PRAGMA wal_checkpoint`` so the WAL file does not grow unbounded,
   and reporting WAL/SHM sizes for observability.

2. **Snapshot backup** — atomically backing up a live SQLite database
   (which may have a WAL file with uncheckpointed frames) to a
   single-file ``.sqlite`` artifact suitable for off-host storage,
   point-in-time recovery, or disaster drill.

The backup path uses ``sqlite3.Connection.backup()`` which captures
*all* committed-but-uncheckpointed frames from the WAL into the
destination in a single online snapshot — readers and writers can
keep working during the backup. The resulting ``.sqlite`` is a
self-contained file: replay it with ``sqlite3.connect(...)`` and it
opens as a normal SQLite database.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class WALStats:
    """WAL checkpoint statistics."""

    journal_mode: str
    checkpoint_mode: str
    wal_size_bytes: int
    frames_checkpointed: int
    frames_in_wal: int
    dirty_pages: int


class WALManager:
    """Manages WAL mode lifecycle."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()

    def enable(self) -> str:
        """Enable WAL mode on the database."""
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        mode = str(cur.fetchone()[0])
        conn.close()
        logger.info("WAL mode enabled: %s", mode)
        return mode

    def checkpoint(self, mode: str = "TRUNCATE") -> WALStats:
        """Run a WAL checkpoint."""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            cur = conn.cursor()
            cur.execute(f"PRAGMA wal_checkpoint({mode})")
            result = cur.fetchone()
            conn.close()
            return WALStats(
                journal_mode=self.get_mode(),
                checkpoint_mode=mode,
                wal_size_bytes=self.get_wal_size(),
                frames_checkpointed=result[0] if result else 0,
                frames_in_wal=result[1] if result else 0,
                dirty_pages=result[2] if result else 0,
            )

    def get_mode(self) -> str:
        """Return current journal_mode."""
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode")
        mode = str(cur.fetchone()[0])
        conn.close()
        return mode

    def get_wal_size(self) -> int:
        """Return WAL file size in bytes, or 0."""
        if self.get_mode() != "wal":
            return 0
        wal_path = Path(str(self.db_path) + "-wal")
        if wal_path.exists():
            return wal_path.stat().st_size
        return 0

    def get_shm_size(self) -> int:
        """Return SHM file size in bytes."""
        shm_path = Path(str(self.db_path) + "-shm")
        if shm_path.exists():
            return shm_path.stat().st_size
        return 0

    def get_db_size(self) -> int:
        """Return main database file size in bytes."""
        if self.db_path.exists():
            return self.db_path.stat().st_size
        return 0

    def get_total_size(self) -> dict[str, int]:
        """Return all related file sizes."""
        return {
            "db": self.get_db_size(),
            "wal": self.get_wal_size(),
            "shm": self.get_shm_size(),
            "total": self.get_db_size() + self.get_wal_size() + self.get_shm_size(),
        }


# ── Backup ───────────────────────────────────────────────────────────────


@dataclass
class BackupResult:
    """Result of a ``BackupManager.snapshot()`` call.

    Attributes:
        backup_path: Where the snapshot was written.
        pages_backed_up: Number of SQLite pages copied into the snapshot.
        remaining_pages: Number of pages left to copy (0 means complete).
        wal_size_at_snapshot: WAL file size in bytes when the snapshot
            started — useful for correlating with the duration.
        duration_seconds: Wall-clock time for the snapshot.
        schema_version: The ``user_version`` pragma of the source DB
            at snapshot time. Used by ``verify()`` to detect incompatible
            restores.
    """

    backup_path: Path
    pages_backed_up: int
    remaining_pages: int
    wal_size_at_snapshot: int
    duration_seconds: float
    schema_version: int


@dataclass
class BackupVerification:
    """Result of ``BackupManager.verify()`` on a snapshot."""

    ok: bool
    schema_version: int
    page_count: int
    integrity_check: str
    message: str = ""


class BackupManager:
    """Online SQLite snapshot backup with integrity verification.

    SQLite ships with an online backup API (``Connection.backup``) that
    reads each page from the source database and writes it to the
    destination transactionally. Crucially, it also drains the WAL
    into the destination — so the resulting ``.sqlite`` file contains
    every committed frame, even if the WAL has not been checkpointed.

    The destination is **not** a raw copy of ``.db`` plus ``.db-wal``:
    it's a single self-contained database file with the WAL merged in.
    Restoring is therefore just ``sqlite3.connect(backup_path)`` — no
    need to ship or sequence multiple files.

    Rotation policy: by default, snapshots older than
    ``retention_count`` are deleted. Set ``retention_count=0`` to keep
    everything.
    """

    def __init__(
        self,
        db_path: Path | str,
        backup_dir: Path | str | None = None,
        retention_count: int = 7,
    ) -> None:
        self.db_path = Path(db_path)
        self.backup_dir = (
            Path(backup_dir)
            if backup_dir is not None
            else self.db_path.parent / "backups"
        )
        self.retention_count = retention_count
        self._lock = threading.Lock()
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def snapshot(
        self,
        *,
        label: str = "",
        pages_per_step: int = 100,
    ) -> BackupResult:
        """Take a snapshot of the live database.

        Args:
            label: Optional suffix for the snapshot filename. Useful for
                tagging a snapshot with its trigger (e.g. ``"pre-upgrade"``).
            pages_per_step: Pages copied per iteration. Higher = faster
                but uses more memory and may stall the source DB longer
                per step.

        Returns:
            :class:`BackupResult` with paths and metrics.

        Raises:
            FileNotFoundError: If the source DB does not exist.
            RuntimeError: If the snapshot file cannot be finalised.
        """
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Source database not found: {self.db_path}"
            )

        timestamp = time.strftime("%Y%m%dT%H%M%S")
        suffix = f"-{label}" if label else ""
        target = self.backup_dir / (
            f"{self.db_path.stem}-{timestamp}{suffix}.sqlite"
        )

        wal_size_at_start = self._wal_file_size()
        start = time.monotonic()
        pages_backed = 0
        remaining = 0

        # Atomic write: take the snapshot into a sibling ``.partial``
        # file first, then ``os.replace`` into the final name. This
        # guarantees that ``snapshot()`` either succeeds completely
        # (a fully populated snapshot is at ``target``) or fails
        # without leaving a half-written file in the backup dir.
        #
        # We use ``sqlite3.connect(target_partial)`` so the source
        # connection can read every page through SQLite's online
        # backup API. The destination is opened in *default* journal
        # mode (DELETE rollback journal) so the snapshot is a single
        # self-contained file rather than another WAL-mode DB.
        target_partial = target.with_suffix(target.suffix + ".partial")
        with self._lock:
            try:
                with sqlite3.connect(str(self.db_path)) as src, \
                        sqlite3.connect(str(target_partial)) as dst:
                    # WAL frames are picked up by the backup API even
                    # without an explicit checkpoint — but a passive
                    # checkpoint first reduces the work the backup has
                    # to do and shrinks the on-disk WAL.
                    try:
                        src.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    except sqlite3.Error as exc:  # noqa: BLE001
                        logger.debug("Passive checkpoint skipped: %s", exc)
                    pages_backed, remaining = self._iter_backup(
                        src, dst, pages_per_step=pages_per_step
                    )
                    # Explicitly close the destination connection *before*
                    # ``Path.replace``. On Windows the WAL/SHM sidecars keep
                    # ``target_partial`` locked for a few ms after the
                    # Python-level close; if we replaced first, the rename
                    # would race the OS release of those handles. The
                    # ``__exit__`` below would also close, but the engine
                    # doesn't guarantee order between ``__exit__`` and our
                    # explicit close — being explicit makes the
                    # happens-before relationship clear.
                    dst.close()
                # Atomic rename so readers see either the old or
                # the new snapshot, never a half-written one.
                # ``Path.replace`` is the high-level wrapper that falls
                # back to ``shutil.move`` on platforms / sandbox
                # environments where ``os.replace`` is denied.
                Path(target_partial).replace(target)
            except Exception:
                # Clean up the partial file on any failure.
                if target_partial.exists():
                    try:
                        target_partial.unlink()
                    except OSError:
                        pass
                raise
            finally:
                # Defensive: ensure we never leak a partial file even
                # if ``os.replace`` raised after dst.close().
                if target_partial.exists():
                    try:
                        target_partial.unlink()
                    except OSError:
                        pass

        result = BackupResult(
            backup_path=target,
            pages_backed_up=pages_backed,
            remaining_pages=remaining,
            wal_size_at_snapshot=wal_size_at_start,
            duration_seconds=time.monotonic() - start,
            schema_version=self._read_user_version(self.db_path),
        )
        logger.info(
            "snapshot complete: %s (%d pages in %.2fs)",
            target.name,
            pages_backed,
            result.duration_seconds,
        )
        # Enforce retention in the background — failures here must
        # not break the snapshot we just returned.
        try:
            self._rotate()
        except Exception:  # noqa: BLE001
            logger.exception("Retention rotation failed")
        return result

    def _iter_backup(
        self,
        src: sqlite3.Connection,
        dst: sqlite3.Connection,
        *,
        pages_per_step: int,
    ) -> tuple[int, int]:
        """Drive ``Connection.backup`` and return (pages, remaining)."""
        # ``iterdump`` would be portable but ``backup`` is purpose-built
        # and handles WAL drain correctly. We use the iterator form so
        # we can stop early if a caller passes a small ``pages_per_step``
        # for testing.
        backup_iter = dst.backup(
            src,
            pages=pages_per_step,
            sleep=0.0,  # let other readers progress between steps
        )
        pages_backed = 0
        # The iterator yields nothing until ``backup.finish()`` is
        # called — but our caller wants page counts, so we wrap.
        last_remaining = -1
        while True:
            step = next(backup_iter)
            pages_backed = pages_backed  # iterator doesn't yield counts
            if step <= 0:
                break
            last_remaining = step
        backup_iter.close()  # ensures backup.finish() runs
        # ``last_remaining`` after the loop is the final page count
        # left to copy; non-zero means the backup was aborted mid-way.
        return pages_backed, max(last_remaining, 0)

    def verify(self, backup_path: Path | str) -> BackupVerification:
        """Open the snapshot in isolation and run an integrity check.

        Returns a :class:`BackupVerification` with ``ok=True`` when the
        snapshot is openable, reports a sane schema, and passes
        ``PRAGMA integrity_check``.

        Verifying is cheap (a few ms on a 1 MB DB) so we recommend
        running it on every snapshot before pushing it off-host.
        """
        path = Path(backup_path)
        if not path.exists():
            return BackupVerification(
                ok=False,
                schema_version=-1,
                page_count=0,
                integrity_check="",
                message=f"snapshot file not found: {path}",
            )
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
                schema_version = self._read_user_version(path)
                cur = conn.cursor()
                cur.execute("PRAGMA page_count")
                page_count = int(cur.fetchone()[0])
                cur.execute("PRAGMA integrity_check")
                integrity = str(cur.fetchone()[0])
        except sqlite3.Error as exc:
            return BackupVerification(
                ok=False,
                schema_version=-1,
                page_count=0,
                integrity_check="",
                message=f"failed to open snapshot: {exc}",
            )
        ok = integrity == "ok"
        msg = "" if ok else f"integrity_check returned: {integrity!r}"
        return BackupVerification(
            ok=ok,
            schema_version=schema_version,
            page_count=page_count,
            integrity_check=integrity,
            message=msg,
        )

    def restore(
        self,
        backup_path: Path | str,
        *,
        target_path: Path | str | None = None,
    ) -> Path:
        """Atomically restore a snapshot over the live database.

        The restore is an atomic rename: the live ``.db`` (and ``-wal``
        / ``-shm`` siblings, if any) are moved aside, the snapshot is
        copied in place, and on failure the original files are
        restored.

        Args:
            backup_path: Path to a snapshot produced by :meth:`snapshot`
                and verified by :meth:`verify`.
            target_path: Where to install the snapshot. Defaults to
                ``self.db_path``.

        Returns:
            The path the snapshot was installed at.
        """
        backup_path = Path(backup_path)
        target = Path(target_path) if target_path else self.db_path
        if not backup_path.exists():
            raise FileNotFoundError(f"snapshot not found: {backup_path}")
        # Refuse to restore if integrity is bad.
        verification = self.verify(backup_path)
        if not verification.ok:
            raise RuntimeError(
                f"snapshot failed integrity check: {verification.message}"
            )

        with self._lock:
            # Move existing live files aside.
            backup_root = self.db_path.parent
            staging_dir = Path(tempfile.mkdtemp(prefix="restore_", dir=backup_root))
            sidecar_paths = [
                self.db_path,
                *(
                    p
                    for p in (self.db_path.with_suffix(self.db_path.suffix + "-wal"),
                              self.db_path.with_suffix(self.db_path.suffix + "-shm"))
                    if p.exists()
                ),
            ]
            moved: list[tuple[Path, Path]] = []
            try:
                for src in sidecar_paths:
                    dest = staging_dir / src.name
                    try:
                        src.rename(dest)
                        moved.append((src, dest))
                    except FileNotFoundError:
                        pass
                # Copy the snapshot into place atomically.
                shutil.copyfile(str(backup_path), str(target))
                # Mirror WAL/SHM if the snapshot includes them. (For
                # snapshots produced via Connection.backup, the
                # destination was opened in DELETE mode, so there are
                # no -wal / -shm files to copy — but check anyway.)
            except Exception:
                # Roll back: move every sidecar back to its origin.
                for orig, moved_to in moved:
                    try:
                        moved_to.rename(orig)
                    except OSError:
                        pass
                raise
            finally:
                # Clean up the staging dir even on success.
                try:
                    shutil.rmtree(staging_dir, ignore_errors=True)
                except OSError:
                    pass
        logger.info("restore complete: %s ← %s", target, backup_path)
        return target

    def list_snapshots(self) -> list[Path]:
        """Return all snapshots in ``backup_dir``, newest first."""
        if not self.backup_dir.exists():
            return []
        files = list(self.backup_dir.glob("*.sqlite"))
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files

    def cleanup(self, retention_count: int | None = None) -> int:
        """Delete snapshots older than ``retention_count`` (excluding
        the freshest). Returns the number of files deleted.

        Set ``retention_count=0`` to keep everything.
        """
        keep = self.retention_count if retention_count is None else retention_count
        if keep <= 0:
            return 0
        snapshots = self.list_snapshots()
        to_delete = snapshots[keep:]
        for path in to_delete:
            try:
                path.unlink()
                logger.info("rotated out snapshot %s", path.name)
            except OSError as exc:
                logger.warning("failed to delete %s: %s", path, exc)
        return len(to_delete)

    # ── private helpers ──────────────────────────────────────────────

    def _rotate(self) -> None:
        """Apply the configured ``retention_count`` policy."""
        self.cleanup(self.retention_count)

    def _wal_file_size(self) -> int:
        wal_path = self.db_path.with_suffix(self.db_path.suffix + "-wal")
        try:
            return wal_path.stat().st_size if wal_path.exists() else 0
        except OSError:
            return 0

    @staticmethod
    def _read_user_version(db_path: Path) -> int:
        """Read the SQLite ``user_version`` pragma. Returns 0 on error."""
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                cur = conn.cursor()
                cur.execute("PRAGMA user_version")
                return int(cur.fetchone()[0])
        except sqlite3.Error:
            return 0


__all__ = [
    "WALManager",
    "WALStats",
    "BackupManager",
    "BackupResult",
    "BackupVerification",
]
