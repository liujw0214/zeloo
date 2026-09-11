"""Tests for agent/audit_log.py — append-only, hash-chained audit log."""

from __future__ import annotations

import contextlib
import json
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, ".")


# ── Construction and basic record ────────────────────────────────


def test_record_writes_jsonl_with_chain():
    from agent.audit_log import GENESIS_HASH

    with _tmp_log() as log:
        ev = log.record("test_event", actor="alice", resource="/x", detail={"k": 1})
        assert ev.seq == 1
        assert ev.prev_hash == GENESIS_HASH
        assert ev.hash.startswith("sha256:")
        assert ev.hash != GENESIS_HASH
        # File on disk
        lines = log.path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["kind"] == "test_event"
        assert parsed["actor"] == "alice"


def test_record_chains_prev_hash():

    with _tmp_log() as log:
        a = log.record("e1")
        b = log.record("e2")
        c = log.record("e3")
        assert b.prev_hash == a.hash
        assert c.prev_hash == b.hash
        assert c.seq == 3


def test_record_default_outcome_is_ok():

    with _tmp_log() as log:
        ev = log.record("e")
        assert ev.outcome == "ok"
        assert ev.ts  # ISO timestamp


def test_record_persists_detail_payload():

    with _tmp_log() as log:
        log.record("x", detail={"foo": [1, 2, 3], "nested": {"k": "v"}})
        for ev in log.iter_events():
            assert ev.detail == {"foo": [1, 2, 3], "nested": {"k": "v"}}
            break


# ── Reopen / tail continuity ────────────────────────────────────


def test_tails_continue_across_instances():
    from agent.audit_log import AuditLog

    with _tmp_log() as log:
        path = log.path
        log1 = AuditLog(path=path)
        a = log1.record("first")
        # Fresh instance — must continue the chain.
        log2 = AuditLog(path=path)
        b = log2.record("second")
        assert b.seq == 2
        assert b.prev_hash == a.hash
        assert log2.last_seq() == 2


def test_audit_log_survives_corrupt_tail_line():
    """A malformed line in the middle is skipped when loading the tail."""
    from agent.audit_log import AuditLog

    with _tmp_log() as log:
        path = log.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json\n", encoding="utf-8")
        log2 = AuditLog(path=path)
        # Tail must be GENESIS_HASH (no valid records).
        assert log2.last_seq() == 0


# ── Verification ────────────────────────────────────────────────


def test_verify_clean_log_returns_count():

    with _tmp_log() as log:
        for i in range(5):
            log.record(f"e{i}")
        assert log.verify() == 5


def test_verify_detects_tampering_hash_mismatch():
    from agent.audit_log import AuditChainError

    with _tmp_log() as log:
        log.record("a")
        log.record("b")
        log.record("c")
        # Tamper with the second record's payload by mutating _canonical.
        text = log.path.read_text(encoding="utf-8")
        lines = text.splitlines()
        rec = json.loads(lines[1])
        rec["detail"]["injected"] = True
        # Re-compute _canonical so the writer's stored hash no longer matches.
        rec["_canonical"] = json.dumps(
            {k: v for k, v in rec.items() if k not in ("hash", "_canonical")},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        lines[1] = json.dumps(rec)
        log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        try:
            log.verify()
        except AuditChainError as exc:
            assert exc.line_no == 2
            return
        raise AssertionError("expected AuditChainError")


def test_verify_detects_prev_hash_break():
    from agent.audit_log import AuditChainError

    with _tmp_log() as log:
        log.record("a")
        log.record("b")
        # Insert a record with the wrong prev_hash.
        text = log.path.read_text(encoding="utf-8")
        lines = text.splitlines()
        rec = json.loads(lines[1])
        rec["prev_hash"] = "sha256:" + "f" * 64
        lines[1] = json.dumps(rec)
        log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        try:
            log.verify()
        except AuditChainError:
            return
        raise AssertionError("expected AuditChainError")


def test_verify_detects_seq_gap():
    from agent.audit_log import AuditChainError

    with _tmp_log() as log:
        log.record("a")
        log.record("b")
        log.record("c")
        # Mutate seq on line 3 from 3 to 5.
        text = log.path.read_text(encoding="utf-8")
        lines = text.splitlines()
        rec = json.loads(lines[2])
        rec["seq"] = 5
        lines[2] = json.dumps(rec)
        log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        try:
            log.verify()
        except AuditChainError:
            return
        raise AssertionError("expected AuditChainError")


def test_verify_raises_on_invalid_json():
    from agent.audit_log import AuditChainError

    with _tmp_log() as log:
        log.record("a")
        log.path.write_text("definitely not json\n", encoding="utf-8")
        try:
            log.verify()
        except AuditChainError:
            return
        raise AssertionError("expected AuditChainError")


# ── Querying ────────────────────────────────────────────────────


def test_query_filters_by_kind():

    with _tmp_log() as log:
        log.record("alpha")
        log.record("beta")
        log.record("alpha")
        r = log.query(kind="alpha")
        assert r.total == 2
        assert all(e.kind == "alpha" for e in r.events)


def test_query_filters_by_outcome():

    with _tmp_log() as log:
        log.record("a", outcome="ok")
        log.record("a", outcome="error")
        log.record("a", outcome="ok")
        r = log.query(outcome="error")
        assert r.total == 1
        assert r.events[0].outcome == "error"


def test_query_filters_by_actor():

    with _tmp_log() as log:
        log.record("x", actor="alice")
        log.record("x", actor="bob")
        log.record("x", actor="alice")
        r = log.query(actor="alice")
        assert r.total == 2


def test_query_since_seq():

    with _tmp_log() as log:
        for i in range(5):
            log.record(f"e{i}")
        r = log.query(since_seq=3)
        assert r.total == 2
        assert [e.seq for e in r.events] == [4, 5]


def test_query_limit_and_reverse():

    with _tmp_log() as log:
        for i in range(10):
            log.record(f"e{i}")
        r = log.query(limit=3, reverse=True)
        assert [e.seq for e in r.events] == [10, 9, 8]


# ── Rotation ────────────────────────────────────────────────────


def test_rotate_starts_new_chain():
    from agent.audit_log import GENESIS_HASH

    with _tmp_log() as log:
        log.record("a")
        log.record("b")
        rotated = log.rotate()
        assert rotated is not None
        assert rotated.exists()
        assert "audit" in rotated.name

        # Chain resets.
        assert log.last_seq() == 0
        assert log.last_hash() == GENESIS_HASH

        # New records start from seq=1.
        ev = log.record("c")
        assert ev.seq == 1
        assert ev.prev_hash == GENESIS_HASH


def test_rotate_no_file_returns_none():

    with _tmp_log() as log:
        # Path doesn't exist yet.
        log.path.unlink(missing_ok=True)
        assert log.rotate() is None


# ── Stats ───────────────────────────────────────────────────────


def test_stats_returns_breakdown():

    with _tmp_log() as log:
        log.record("a")
        log.record("a")
        log.record("b")
        s = log.stats()
        assert s["total"] == 3
        assert s["by_kind"] == {"a": 2, "b": 1}
        assert s["oldest_seq"] == 1
        assert s["newest_seq"] == 3


# ── Concurrency ──────────────────────────────────────────────────


def test_record_is_thread_safe():

    with _tmp_log() as log:
        errors: list = []

        def worker(n: int) -> None:
            try:
                for _ in range(50):
                    log.record("worker", actor=f"w{n}")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        # Verify the resulting chain.
        assert log.verify() == 200


# ── Module-level helper ─────────────────────────────────────────


def test_audit_event_helper(monkeypatch):
    from agent import audit_log

    audit_log.reset_default_audit_log()
    try:
        log = audit_log.get_default_audit_log()
        monkeypatch.setattr(log, "_write_line", lambda *a, **kw: None)
        ev = audit_log.audit_event("hello", actor="tester", resource="r")
        assert ev is not None
        assert ev.kind == "hello"
    finally:
        audit_log.reset_default_audit_log()


def test_audit_event_does_not_raise_on_failure(monkeypatch):
    """Helper must never raise even if the underlying write fails."""
    from agent import audit_log

    audit_log.reset_default_audit_log()
    try:
        # Force the underlying record() to blow up.
        def boom(*_a, **_kw):
            raise RuntimeError("disk full")

        monkeypatch.setattr(audit_log.get_default_audit_log(), "record", boom)
        # Should swallow.
        assert audit_log.audit_event("any") is None
    finally:
        audit_log.reset_default_audit_log()


# ── Integration: estop triggers audit ───────────────────────────


def test_estop_trigger_writes_audit_event():
    from agent import audit_log, estop

    audit_log.reset_default_audit_log()
    with _tmp_log() as log:
        audit_log._default = audit_log.AuditLog(path=log.path)  # noqa: SLF001
        try:
            estop.estop.reset()
            estop.estop.trigger("audit-test", by="alice")
            events = list(audit_log.get_default_audit_log().iter_events())
            assert any(e.kind == "estop_triggered" for e in events)
        finally:
            estop.estop.reset()
            audit_log.reset_default_audit_log()


# ── Helpers ─────────────────────────────────────────────────────


@contextlib.contextmanager
def _tmp_log():
    """Context manager: yield an AuditLog backed by a temp file."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "audit.log"
        from agent.audit_log import AuditLog

        log = AuditLog(path=path)
        yield log
        # Note: don't auto-verify() — tests that tamper with the file
        # intentionally break the chain.
