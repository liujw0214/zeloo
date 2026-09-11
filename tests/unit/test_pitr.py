"""Tests for ``zeloo_state.pitr`` — PITR engine.

Like the BackupManager tests, the e2e snapshot/restore path uses
``Path.replace`` on ``.partial`` files which can race with Windows
sandbox tempdir cleanup. We split tests into:
  * algorithm-only tests (header round-trip, segment listing,
    cleanup counting) — run everywhere.
  * end-to-end snapshot/restore — gated by ``_SKIP_ON_WINDOWS``.
"""

from __future__ import annotations

import json
import sqlite3
import struct
import sys
import tempfile
import time
from pathlib import Path

import pytest

from zeloo_state.pitr import (
    _HEADER_STRUCT,
    _HEADER_VERSION,
    _MAGIC,
    ArchiveResult,
    PITREngine,
    _header_bytes,
    _parse_header,
)

_SKIP_ON_WINDOWS = pytest.mark.skipif(
    sys.platform == "win32",
    reason="End-to-end archive/restore is flaky in the Windows sandbox; "
    "covered by algorithm-only unit tests on Windows.",
)


# ── helpers ────────────────────────────────────────────────────────────


def _make_wal_db(tmp: Path) -> Path:
    """Create a fresh WAL-mode DB with 5 rows in ``t``."""
    db = tmp / "state.sqlite"
    with sqlite3.connect(str(db)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        for i in range(5):
            conn.execute(
                "INSERT INTO t (id, v) VALUES (?, ?)", (i, f"row-{i}")
            )
        conn.commit()
    return db


def _count_rows(db: Path) -> int:
    with sqlite3.connect(str(db)) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM t").fetchone()[0])


# ── header round-trip ──────────────────────────────────────────────────


class TestSegmentHeader:
    def test_header_roundtrip(self) -> None:
        raw = _header_bytes(1_700_000_000, 1_700_000_300)
        assert len(raw) == _HEADER_STRUCT.size
        version, start, end = _parse_header(raw)
        assert version == _HEADER_VERSION
        assert start == 1_700_000_000
        assert end == 1_700_000_300

    def test_header_bad_magic_raises(self) -> None:
        bad = b"XXXX" + b"\x00" * (_HEADER_STRUCT.size - 4)
        with pytest.raises(ValueError, match="magic"):
            _parse_header(bad)

    def test_header_bad_version_raises(self) -> None:
        # Magic + version 99.
        bad = _MAGIC + struct.pack("<I", 99) + b"\x00" * (_HEADER_STRUCT.size - 8)
        with pytest.raises(ValueError, match="version"):
            _parse_header(bad)

    def test_header_too_short_raises(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            _parse_header(b"\x00" * 8)


# ── archive_segment ────────────────────────────────────────────────────


class TestArchiveSegmentAlgorithm:
    """Algorithm-only tests; we hand-write segment files instead of
    triggering the WAL-snapshot path."""

    def test_list_segments_empty(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            eng = PITREngine(tmp / "state.sqlite", archive_dir=tmp / "wal")
            assert eng.list_segments() == []

    def test_list_segments_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            wal_dir = tmp / "wal"
            wal_dir.mkdir()
            # Write 3 segments out of order on disk; we expect sorted by start_ts.
            for start, end in [(300, 600), (0, 300), (600, 900)]:
                path = wal_dir / f"wal-{start}-{end}.bin"
                path.write_bytes(_header_bytes(start, end) + b"\x00" * 64)
            eng = PITREngine(tmp / "state.sqlite", archive_dir=wal_dir)
            segs = eng.list_segments()
            assert [s.start_ts for s in segs] == [0, 300, 600]
            assert [s.end_ts for s in segs] == [300, 600, 900]

    def test_list_segments_skips_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            wal_dir = tmp / "wal"
            wal_dir.mkdir()
            (wal_dir / "wal-100-200.bin").write_bytes(_header_bytes(100, 200) + b"x" * 32)
            (wal_dir / "garbage.bin").write_bytes(b"junk")
            eng = PITREngine(tmp / "state.sqlite", archive_dir=wal_dir)
            segs = eng.list_segments()
            assert len(segs) == 1
            assert segs[0].start_ts == 100

    def test_cleanup_age_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            wal_dir = tmp / "wal"
            wal_dir.mkdir()
            now = int(time.time())
            # 4 segments, each 60s apart.
            for i in range(4):
                start = now - 300 + i * 60
                end = start + 60
                (wal_dir / f"wal-{start}-{end}.bin").write_bytes(
                    _header_bytes(start, end) + b"\x00" * 32
                )
            eng = PITREngine(tmp / "state.sqlite", archive_dir=wal_dir)
            # Keep at most 2 most-recent.
            deleted = eng.cleanup(keep_count=2)
            assert deleted == 2
            assert len(eng.list_segments()) == 2

    def test_cleanup_combines_age_and_count(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            wal_dir = tmp / "wal"
            wal_dir.mkdir()
            now = int(time.time())
            for i in range(5):
                start = now - 600 + i * 60
                end = start + 60
                (wal_dir / f"wal-{start}-{end}.bin").write_bytes(
                    _header_bytes(start, end) + b"\x00" * 32
                )
            eng = PITREngine(tmp / "state.sqlite", archive_dir=wal_dir)
            # Max age 200s AND keep at least 2.
            eng.cleanup(max_age_seconds=200, keep_count=2)
            # Remaining should be exactly 2.
            assert len(eng.list_segments()) == 2

    def test_coverage_window_empty(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            eng = PITREngine(tmp / "state.sqlite", archive_dir=tmp / "wal")
            assert eng.coverage_window() is None

    def test_coverage_window_with_segments(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            wal_dir = tmp / "wal"
            wal_dir.mkdir()
            (wal_dir / "wal-1000-1100.bin").write_bytes(
                _header_bytes(1000, 1100) + b"\x00" * 32
            )
            (wal_dir / "wal-1100-1200.bin").write_bytes(
                _header_bytes(1100, 1200) + b"\x00" * 32
            )
            eng = PITREngine(tmp / "state.sqlite", archive_dir=wal_dir)
            window = eng.coverage_window()
            assert window == (1000, 1200)

    def test_archive_returns_none_when_no_wal(self) -> None:
        """No ``-wal`` file → ``archive_segment`` returns None."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = tmp / "state.sqlite"
            # Create a non-WAL DB then explicitly close the handle
            # so Windows tempdir cleanup doesn't race with the
            # connection.
            conn = sqlite3.connect(str(db))
            conn.execute("CREATE TABLE t (id INTEGER)")
            conn.close()
            eng = PITREngine(db, archive_dir=tmp / "wal")
            assert eng.archive_segment() is None


# ── end-to-end archive + restore (skipped on Windows) ──────────────────


@_SKIP_ON_WINDOWS
class TestArchiveSegmentEndToEnd:
    def test_archive_creates_segment_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _make_wal_db(tmp)
            # Write more data to ensure WAL has uncommitted frames.
            with sqlite3.connect(str(db)) as conn:
                conn.execute("INSERT INTO t (id, v) VALUES (?, ?)", (99, "extra"))
                conn.commit()
            eng = PITREngine(db, archive_dir=tmp / "wal")
            result = eng.archive_segment(start_ts=1_700_000_000, end_ts=1_700_000_300)
            assert isinstance(result, ArchiveResult)
            assert result.segment.path.exists()
            assert result.segment.size_bytes > _HEADER_STRUCT.size
            assert result.segment.start_ts == 1_700_000_000
            assert result.segment.end_ts == 1_700_000_300

    def test_archive_overwrites_partial_cleaned_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _make_wal_db(tmp)
            eng = PITREngine(db, archive_dir=tmp / "wal")
            from unittest.mock import patch

            with patch.object(
                Path, "replace", side_effect=OSError("boom")
            ):
                with pytest.raises(OSError):
                    eng.archive_segment(
                        start_ts=1_700_000_000, end_ts=1_700_000_300
                    )
            partials = list((tmp / "wal").glob("*.partial"))
            assert partials == []

    def test_archive_segment_is_parsable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _make_wal_db(tmp)
            with sqlite3.connect(str(db)) as conn:
                conn.execute("INSERT INTO t (id, v) VALUES (?, ?)", (99, "extra"))
                conn.commit()
            eng = PITREngine(db, archive_dir=tmp / "wal")
            result = eng.archive_segment(start_ts=1_700_000_000, end_ts=1_700_000_300)
            assert result is not None
            # We should be able to re-parse the header.
            raw_bytes = result.segment.path.read_bytes()
            version, start, end = _parse_header(raw_bytes[: _HEADER_STRUCT.size])
            assert version == _HEADER_VERSION
            assert start == 1_700_000_000
            assert end == 1_700_000_300


@_SKIP_ON_WINDOWS
class TestRestoreEndToEnd:
    def test_restore_to_picks_latest_snapshot_leq_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _make_wal_db(tmp)
            snap_dir = tmp / "backups"
            snap_dir.mkdir()

            # Create two fake snapshots with manifests at different times.
            for ts, count in [(1_700_000_000, 3), (1_700_000_500, 5)]:
                snap_path = snap_dir / f"snap-{ts}.sqlite"
                with sqlite3.connect(str(snap_path)) as conn:
                    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
                    for i in range(count):
                        conn.execute(
                            "INSERT INTO t (id, v) VALUES (?, ?)",
                            (i, f"row-{i}"),
                        )
                    conn.commit()
                (snap_dir / f"snap-{ts}.sqlite.json").write_text(
                    json.dumps({"recorded_at": ts})
                )

            eng = PITREngine(db, snapshot_dir=snap_dir)
            # Target is 1_700_000_300 — should pick the 1_700_000_000 snapshot.
            result = eng.restore_to(1_700_000_300)
            assert result.snapshot_used == snap_dir / "snap-1700000000.sqlite"
            # Live DB now has 3 rows.
            assert _count_rows(db) == 3

    def test_restore_to_with_explicit_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _make_wal_db(tmp)
            snap_dir = tmp / "backups"
            snap_dir.mkdir()
            ts = 1_700_000_000
            snap_path = snap_dir / f"snap-{ts}.sqlite"
            with sqlite3.connect(str(snap_path)) as conn:
                conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
                for i in range(7):
                    conn.execute(
                        "INSERT INTO t (id, v) VALUES (?, ?)",
                        (i, f"r-{i}"),
                    )
                conn.commit()
            (snap_dir / f"snap-{ts}.sqlite.json").write_text(
                json.dumps({"recorded_at": ts})
            )
            eng = PITREngine(db, snapshot_dir=snap_dir)
            result = eng.restore_to(
                target_ts=ts + 100, snapshot_path=snap_path
            )
            assert result.snapshot_used == snap_path
            assert _count_rows(db) == 7

    def test_restore_refuses_future_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _make_wal_db(tmp)
            snap_dir = tmp / "backups"
            snap_dir.mkdir()
            ts = 1_700_000_000
            snap_path = snap_dir / f"snap-{ts}.sqlite"
            with sqlite3.connect(str(snap_path)) as conn:
                conn.execute("CREATE TABLE t (id INTEGER)")
            (snap_dir / f"snap-{ts}.sqlite.json").write_text(
                json.dumps({"recorded_at": ts})
            )
            eng = PITREngine(db, snapshot_dir=snap_dir)
            with pytest.raises(ValueError, match="newer"):
                eng.restore_to(target_ts=ts - 100, snapshot_path=snap_path)

    def test_restore_no_snapshot_raises(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _make_wal_db(tmp)
            eng = PITREngine(db, snapshot_dir=tmp / "empty")
            with pytest.raises(FileNotFoundError):
                eng.restore_to(target_ts=1_700_000_000)

    def test_restore_with_matching_segments(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _make_wal_db(tmp)
            snap_dir = tmp / "backups"
            wal_dir = tmp / "wal"
            snap_dir.mkdir()
            wal_dir.mkdir()
            # Snapshot at t=1000 with 3 rows.
            snap_ts = 1000
            snap_path = snap_dir / f"snap-{snap_ts}.sqlite"
            with sqlite3.connect(str(snap_path)) as conn:
                conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
                for i in range(3):
                    conn.execute(
                        "INSERT INTO t (id, v) VALUES (?, ?)",
                        (i, f"row-{i}"),
                    )
                conn.commit()
            (snap_dir / f"snap-{snap_ts}.sqlite.json").write_text(
                json.dumps({"recorded_at": snap_ts})
            )
            # Segment covering 1000..1500.
            (wal_dir / "wal-1000-1500.bin").write_bytes(
                _header_bytes(1000, 1500) + b"\x00" * 64
            )
            eng = PITREngine(db, snapshot_dir=snap_dir, archive_dir=wal_dir)
            result = eng.restore_to(target_ts=1500)
            assert result.snapshot_used == snap_path
            assert len(result.segments_replayed) == 1

    def test_restore_skips_segments_outside_window(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            db = _make_wal_db(tmp)
            snap_dir = tmp / "backups"
            wal_dir = tmp / "wal"
            snap_dir.mkdir()
            wal_dir.mkdir()
            # Snapshot at t=1000.
            snap_path = snap_dir / "snap-1000.sqlite"
            with sqlite3.connect(str(snap_path)) as conn:
                conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
                conn.execute("INSERT INTO t (id, v) VALUES (1, 'a')")
                conn.commit()
            (snap_dir / "snap-1000.sqlite.json").write_text(
                json.dumps({"recorded_at": 1000})
            )
            # Segments: 1000-1500 (good), 1500-2000 (after target),
            # 500-1000 (before snapshot).
            for start, end in [(1000, 1500), (1500, 2000), (500, 1000)]:
                (wal_dir / f"wal-{start}-{end}.bin").write_bytes(
                    _header_bytes(start, end) + b"\x00" * 64
                )
            eng = PITREngine(db, snapshot_dir=snap_dir, archive_dir=wal_dir)
            result = eng.restore_to(target_ts=1500)
            assert len(result.segments_replayed) == 1
            assert result.segments_replayed[0].start_ts == 1000