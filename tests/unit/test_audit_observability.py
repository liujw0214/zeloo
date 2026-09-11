"""Tests for agent/audit_observability.py — audit → Langfuse bridge."""

from __future__ import annotations

import sys

sys.path.insert(0, ".")


# ── Payload mapping ──────────────────────────────────────────────


def test_ok_outcome_yields_default_level():
    from agent.audit_log import AuditEvent
    from agent.audit_observability import event_to_span_payload

    event = AuditEvent(
        ts="2026-09-08T00:00:00Z",
        seq=1,
        kind="file_write",
        actor="tool:file",
        resource="/tmp/x.txt",
        outcome="ok",
        detail={"bytes": 42},
        prev_hash="",
        hash="sha256:abc",
    )
    payload = event_to_span_payload(event)
    assert payload["level"] == "DEFAULT"
    assert payload["status"] == "SUCCESS"
    assert payload["name"] == "audit:file_write"
    assert payload["metadata"]["audit_kind"] == "file_write"
    assert payload["metadata"]["audit_seq"] == 1
    assert payload["metadata"]["bytes"] == 42


def test_error_outcome_yields_error_level():
    from agent.audit_log import AuditEvent
    from agent.audit_observability import event_to_span_payload

    event = AuditEvent(
        ts="2026-09-08T00:00:00Z",
        seq=2,
        kind="file_read",
        outcome="error",
        detail={"reason": "boom"},
        prev_hash="",
        hash="",
    )
    payload = event_to_span_payload(event)
    assert payload["level"] == "ERROR"
    assert payload["status"] == "ERROR"


def test_blocked_outcome_yields_warning_level():
    from agent.audit_log import AuditEvent
    from agent.audit_observability import event_to_span_payload

    event = AuditEvent(
        ts="2026-09-08T00:00:00Z",
        seq=3,
        kind="file_read",
        outcome="blocked",
        detail={},
        prev_hash="",
        hash="",
    )
    payload = event_to_span_payload(event)
    assert payload["level"] == "WARNING"
    assert payload["status"] == "SUCCESS"


def test_high_impact_kind_always_error():
    from agent.audit_log import AuditEvent
    from agent.audit_observability import event_to_span_payload

    for kind in (
        "estop_triggered",
        "webhook_failed",
        "llm_output_secret_alert",
        "tool_output_secret_found",
    ):
        event = AuditEvent(
            ts="2026-09-08T00:00:00Z",
            seq=1,
            kind=kind,
            outcome="ok",
            detail={},
            prev_hash="",
            hash="",
        )
        payload = event_to_span_payload(event)
        assert payload["level"] == "ERROR", f"{kind} should map to ERROR"
        assert payload["status"] == "ERROR"


# ── AuditLog observer fan-out ─────────────────────────────────


def test_audit_log_invokes_observer_on_record(tmp_path):
    from agent.audit_log import AuditLog

    log = AuditLog(path=tmp_path / "a.log")
    received: list = []
    log.attach_observer(received.append)
    log.record("alpha", actor="alice")
    log.record("beta")
    assert [e.kind for e in received] == ["alpha", "beta"]


def test_observer_dedup_prevents_double_attach(tmp_path):
    from agent.audit_log import AuditLog

    log = AuditLog(path=tmp_path / "a.log")
    cb = lambda _e: None  # noqa: E731
    log.attach_observer(cb)
    log.attach_observer(cb)
    assert log.observer_count() == 1
    log.detach_observer(cb)
    assert log.observer_count() == 0


def test_observer_exception_does_not_break_record(tmp_path):
    from agent.audit_log import AuditLog

    log = AuditLog(path=tmp_path / "a.log")

    def boom(_e):
        raise RuntimeError("kaboom")

    log.attach_observer(boom)
    # Record must succeed despite observer raising.
    event = log.record("survives")
    assert event.kind == "survives"
    # Log file still contains the record.
    assert log.path.exists()


def test_observer_detach_returns_false_when_unknown(tmp_path):
    from agent.audit_log import AuditLog

    log = AuditLog(path=tmp_path / "a.log")
    assert log.detach_observer(lambda _e: None) is False


# ── AuditObserver end-to-end ─────────────────────────────────


class _FakeTracer:
    """Records all tracer calls without touching the network."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.log_tool_calls: list[dict] = []
        self.traces: list[dict] = []

    def trace(self, name: str, metadata=None):  # noqa: A002
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            ctx_obj = type(
                "_C", (), {"trace_id": f"trace-{len(self.traces)}"}
            )()
            self.traces.append({"name": name, "metadata": metadata})
            try:
                yield ctx_obj
            finally:
                pass

        return _ctx()

    def log_tool_call(self, **kwargs):
        self.log_tool_calls.append(kwargs)


def test_audit_observer_forwards_to_tracer():
    from agent.audit_log import AuditEvent
    from agent.audit_observability import AuditObserver

    tracer = _FakeTracer()
    observer = AuditObserver(tracer=tracer)
    event = AuditEvent(
        ts="2026-09-08T00:00:00Z",
        seq=7,
        kind="webhook_failed",
        outcome="ok",  # high-impact kind overrides outcome
        detail={"attempts": 4},
        prev_hash="",
        hash="",
    )
    observer(event)
    assert len(tracer.log_tool_calls) == 1
    call = tracer.log_tool_calls[0]
    assert call["tool_name"] == "audit:webhook_failed"
    assert call["level"] == "ERROR"
    assert call["success"] is False  # ERROR → success=False
    assert call["metadata"]["audit_kind"] == "webhook_failed"
    assert call["metadata"]["attempts"] == 4


def test_audit_observer_drops_when_tracer_disabled():
    from agent.audit_log import AuditEvent
    from agent.audit_observability import AuditObserver

    tracer = _FakeTracer(enabled=False)
    observer = AuditObserver(tracer=tracer)
    observer(
        AuditEvent(
            ts="t", seq=1, kind="k", outcome="ok", detail={}, prev_hash="", hash=""
        )
    )
    assert tracer.log_tool_calls == []
    s = observer.stats()
    assert s["dropped_no_tracer"] == 1


def test_audit_observer_sampling():
    from agent.audit_log import AuditEvent
    from agent.audit_observability import AuditObserver

    tracer = _FakeTracer()
    observer = AuditObserver(tracer=tracer, sample_rate=0.0)
    for i in range(50):
        observer(
            AuditEvent(
                ts="t",
                seq=i,
                kind="k",
                outcome="ok",
                detail={},
                prev_hash="",
                hash="",
            )
        )
    assert tracer.log_tool_calls == []
    s = observer.stats()
    assert s["events"] == 50
    assert s["dropped_sampled"] == 50


def test_audit_observer_invalid_sample_rate():
    from agent.audit_observability import AuditObserver

    for bad in (-0.1, 1.1, 2.0):
        try:
            AuditObserver(sample_rate=bad)
        except ValueError:
            return
    raise AssertionError("expected ValueError")


def test_audit_observer_swallows_tracer_errors():
    from agent.audit_log import AuditEvent
    from agent.audit_observability import AuditObserver

    class _BadTracer:
        enabled = True

        def trace(self, *a, **kw):
            raise RuntimeError("tracer down")

    observer = AuditObserver(tracer=_BadTracer())
    # Must not raise.
    observer(
        AuditEvent(
            ts="t", seq=1, kind="k", outcome="ok", detail={}, prev_hash="", hash=""
        )
    )
    s = observer.stats()
    assert s["tracer_errors"] == 1


def test_audit_observer_switches_tracer_at_runtime():
    from agent.audit_log import AuditEvent
    from agent.audit_observability import AuditObserver

    a = _FakeTracer()
    b = _FakeTracer()
    observer = AuditObserver(tracer=a)
    observer.set_tracer(b)
    observer(
        AuditEvent(
            ts="t", seq=1, kind="k", outcome="ok", detail={}, prev_hash="", hash=""
        )
    )
    assert a.log_tool_calls == []
    assert len(b.log_tool_calls) == 1


# ── install / uninstall ───────────────────────────────────────


def test_install_default_observer_attaches_to_default_log(monkeypatch):
    from agent import audit_log, audit_observability

    audit_log.reset_default_audit_log()
    audit_observability.uninstall_default_observer()
    log = audit_log.get_default_audit_log()
    monkeypatch.setattr(log, "_write_line", lambda *a, **kw: None)

    fake_tracer = _FakeTracer()
    monkeypatch.setattr(audit_observability, "_auto_tracer", lambda: fake_tracer)
    try:
        observer = audit_observability.install_default_observer()
        assert audit_log.get_default_audit_log().observer_count() == 1
        audit_log.audit_event("file_write", resource="/x")
        # The default audit_log singleton writes to ~/.Zeloo/audit.log
        # in real environments; here we just verify that the observer
        # received the event.
        assert observer.stats()["events"] >= 1
    finally:
        audit_observability.uninstall_default_observer()
        audit_log.reset_default_audit_log()


def test_install_default_observer_is_idempotent():
    from agent import audit_observability

    audit_observability.uninstall_default_observer()
    try:
        a = audit_observability.install_default_observer(tracer=_FakeTracer())
        b = audit_observability.install_default_observer(tracer=_FakeTracer())
        assert a is b
        # Only one observer attached.
        from agent.audit_log import get_default_audit_log

        assert get_default_audit_log().observer_count() == 1
    finally:
        audit_observability.uninstall_default_observer()


def test_uninstall_returns_false_when_not_installed():
    from agent import audit_observability

    audit_observability.uninstall_default_observer()
    assert audit_observability.uninstall_default_observer() is False


def test_get_installed_observer_returns_current():
    from agent import audit_observability

    audit_observability.uninstall_default_observer()
    try:
        assert audit_observability.get_installed_observer() is None
        observer = audit_observability.install_default_observer(tracer=_FakeTracer())
        assert audit_observability.get_installed_observer() is observer
    finally:
        audit_observability.uninstall_default_observer()


# ── Langfuse singleton ─────────────────────────────────────────


def test_get_tracer_returns_disabled_when_env_missing(monkeypatch):
    from agent import langfuse_integration

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
    langfuse_integration.set_tracer(None)
    tracer = langfuse_integration.get_tracer()
    assert tracer is not None
    assert tracer.enabled is False


def test_get_tracer_returns_disabled_when_explicit_flag(monkeypatch):
    from agent import langfuse_integration

    monkeypatch.setenv("LANGFUSE_ENABLED", "0")
    langfuse_integration.set_tracer(None)
    tracer = langfuse_integration.get_tracer()
    assert tracer is not None
    assert tracer.enabled is False


def test_set_tracer_replaces_singleton(monkeypatch):
    from agent import langfuse_integration

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    langfuse_integration.set_tracer(None)

    custom = langfuse_integration.LangfuseTracer(enabled=False)
    langfuse_integration.set_tracer(custom)
    assert langfuse_integration.get_tracer() is custom
    langfuse_integration.set_tracer(None)


def test_set_tracer_flushes_existing(monkeypatch):
    from agent import langfuse_integration

    class _FlushTracker:
        def __init__(self) -> None:
            self.flushed = False
            self.enabled = False

        def flush(self) -> None:
            self.flushed = True

    old = _FlushTracker()
    langfuse_integration.set_tracer(old)  # type: ignore[arg-type]
    langfuse_integration.set_tracer(None)
    assert old.flushed is True


# ── End-to-end: audit event → span payload ──────────────────────


def test_end_to_end_audit_event_arrives_at_tracer(tmp_path):
    """AuditEvent recorded via AuditLog ends up in the tracer."""
    from agent.audit_log import AuditLog
    from agent.audit_observability import AuditObserver

    log = AuditLog(path=tmp_path / "a.log")
    tracer = _FakeTracer()
    observer = AuditObserver(tracer=tracer)
    log.attach_observer(observer)

    log.record(
        "tool_output_secret_found",
        actor="tool:file_read",
        resource="/etc/leaked.txt",
        detail={"finding_count": 1, "categories": ["openai_api_key"]},
    )

    assert len(tracer.log_tool_calls) == 1
    call = tracer.log_tool_calls[0]
    assert call["tool_name"] == "audit:tool_output_secret_found"
    assert call["level"] == "ERROR"
    assert call["metadata"]["audit_kind"] == "tool_output_secret_found"
    assert call["metadata"]["categories"] == ["openai_api_key"]
