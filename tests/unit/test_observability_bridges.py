"""Tests for error_tracker / error_observability / cost_tracker integrations."""

from __future__ import annotations

import sys

sys.path.insert(0, ".")


# ── ErrorTracker observer fan-out ────────────────────────────────


def test_error_tracker_invokes_observer(tmp_path):
    from agent.error_tracker import ErrorTracker

    tracker = ErrorTracker(db_path=tmp_path / "e.db")
    received: list = []
    tracker.attach_observer(received.append)
    tracker.record("boom", "msg", severity="error")
    tracker.record("boom2", "msg2", severity="warning")
    assert [e.category for e in received] == ["boom", "boom2"]


def test_error_tracker_observer_dedup(tmp_path):
    from agent.error_tracker import ErrorTracker

    tracker = ErrorTracker(db_path=tmp_path / "e.db")
    received: list = []
    tracker.attach_observer(received.append)
    tracker.record("dup", "same message")
    tracker.record("dup", "same message")
    # Both record calls fire (the second one increments occurrence_count).
    assert len(received) == 2
    assert received[1].occurrence_count == 2


def test_error_tracker_observer_exception_does_not_break_record(tmp_path):
    from agent.error_tracker import ErrorTracker

    tracker = ErrorTracker(db_path=tmp_path / "e.db")

    def boom(_e):
        raise RuntimeError("kaboom")

    tracker.attach_observer(boom)
    event = tracker.record("survives", "still records")
    assert event.category == "survives"
    # Row persisted.
    rows = tracker.query()
    assert rows[0].message == "still records"


def test_error_tracker_detach_returns_false_when_unknown(tmp_path):
    from agent.error_tracker import ErrorTracker

    tracker = ErrorTracker(db_path=tmp_path / "e.db")
    assert tracker.detach_observer(lambda _e: None) is False


# ── ErrorObserver and payload mapping ───────────────────────────


def test_error_payload_mapping_severities():
    from agent.error_observability import event_to_span_payload
    from agent.error_tracker import ErrorEvent

    cases = {
        "fatal": ("ERROR", "ERROR"),
        "error": ("ERROR", "ERROR"),
        "warning": ("WARNING", "SUCCESS"),
        "info": ("DEFAULT", "SUCCESS"),
    }
    for severity, (level, status) in cases.items():
        ev = ErrorEvent(
            fingerprint="abc",
            category="rate_limit",
            severity=severity,
            message="m",
            timestamp=0.0,
            first_seen=0.0,
            last_seen=0.0,
            occurrence_count=1,
            stack_trace="trace",
            session_id="s",
            provider="openai",
            model="gpt-4o",
            context={"k": "v"},
        )
        p = event_to_span_payload(ev)
        assert p["level"] == level, severity
        assert p["status"] == status, severity
        assert p["name"] == "error:rate_limit"
        assert p["metadata"]["occurrence_count"] == 1


def test_error_payload_unknown_severity_treated_as_error():
    from agent.error_observability import event_to_span_payload
    from agent.error_tracker import ErrorEvent

    ev = ErrorEvent(
        fingerprint="x",
        category="unknown_cat",
        severity="weird",
        message="m",
        timestamp=0.0,
        first_seen=0.0,
        last_seen=0.0,
        occurrence_count=1,
    )
    p = event_to_span_payload(ev)
    assert p["level"] == "ERROR"


# ── ErrorObserver end-to-end with fake tracer ────────────────────


class _FakeTracer:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.traces: list = []
        self.log_tool_calls: list = []
        self.log_llm_calls: list = []

    def trace(self, name, metadata=None):  # noqa: A002
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            obj = type("_C", (), {"trace_id": f"trace-{len(self.traces)}"})()
            self.traces.append({"name": name, "metadata": metadata})
            yield obj

        return _ctx()

    def log_tool_call(self, **kwargs):
        self.log_tool_calls.append(kwargs)

    def log_llm_call(self, **kwargs):
        # Return a generation id so callers can chain.
        gen_id = f"gen-{len(self.log_llm_calls)}"
        kwargs["generation_id"] = gen_id
        self.log_llm_calls.append(kwargs)
        return gen_id


def test_error_observer_forwards_error_to_tracer():
    from agent.error_observability import ErrorObserver
    from agent.error_tracker import ErrorEvent

    tracer = _FakeTracer()
    observer = ErrorObserver(tracer=tracer)
    ev = ErrorEvent(
        fingerprint="abc123",
        category="auth",
        severity="error",
        message="bad token",
        timestamp=1.0,
        first_seen=1.0,
        last_seen=1.0,
        occurrence_count=3,
        stack_trace="Traceback...\n  File 'x.py', line 1\n",
    )
    observer(ev)
    assert len(tracer.log_tool_calls) == 1
    call = tracer.log_tool_calls[0]
    assert call["tool_name"] == "error:auth"
    assert call["level"] == "ERROR"
    assert call["success"] is False
    assert call["metadata"]["error_fingerprint"] == "abc123"
    assert call["metadata"]["occurrence_count"] == 3
    # Stack preview truncated, not full.
    assert "stack_trace_preview" in call["metadata"]
    assert call["metadata"]["has_stack_trace"] is True


def test_error_observer_drops_when_tracer_disabled():
    from agent.error_observability import ErrorObserver
    from agent.error_tracker import ErrorEvent

    tracer = _FakeTracer(enabled=False)
    observer = ErrorObserver(tracer=tracer)
    observer(
        ErrorEvent(
            fingerprint="x",
            category="k",
            severity="error",
            message="m",
            timestamp=0.0,
            first_seen=0.0,
            last_seen=0.0,
            occurrence_count=1,
        )
    )
    assert tracer.log_tool_calls == []


def test_error_observer_sampling():
    from agent.error_observability import ErrorObserver
    from agent.error_tracker import ErrorEvent

    tracer = _FakeTracer()
    observer = ErrorObserver(tracer=tracer, sample_rate=0.0)
    for i in range(20):
        observer(
            ErrorEvent(
                fingerprint=f"x{i}",
                category="k",
                severity="error",
                message="m",
                timestamp=0.0,
                first_seen=0.0,
                last_seen=0.0,
                occurrence_count=1,
            )
        )
    assert tracer.log_tool_calls == []
    assert observer.stats()["dropped_sampled"] == 20


def test_error_observer_survives_tracer_failure():
    from agent.error_observability import ErrorObserver
    from agent.error_tracker import ErrorEvent

    class _Bad:
        enabled = True

        def trace(self, *a, **kw):
            raise RuntimeError("net down")

    observer = ErrorObserver(tracer=_Bad())
    observer(
        ErrorEvent(
            fingerprint="x",
            category="k",
            severity="error",
            message="m",
            timestamp=0.0,
            first_seen=0.0,
            last_seen=0.0,
            occurrence_count=1,
        )
    )
    assert observer.stats()["tracer_errors"] == 1


def test_error_observer_set_tracer_at_runtime():
    from agent.error_observability import ErrorObserver
    from agent.error_tracker import ErrorEvent

    a = _FakeTracer()
    b = _FakeTracer()
    observer = ErrorObserver(tracer=a)
    observer.set_tracer(b)
    observer(
        ErrorEvent(
            fingerprint="x",
            category="k",
            severity="error",
            message="m",
            timestamp=0.0,
            first_seen=0.0,
            last_seen=0.0,
            occurrence_count=1,
        )
    )
    assert a.log_tool_calls == []
    assert len(b.log_tool_calls) == 1


def test_error_observer_invalid_sample_rate_raises():
    from agent.error_observability import ErrorObserver

    for bad in (-0.1, 1.1, 5.0):
        try:
            ErrorObserver(sample_rate=bad)
        except ValueError:
            return
    raise AssertionError("expected ValueError")


def test_install_default_observer_attaches_to_default_tracker(tmp_path):
    from agent import error_observability, error_tracker

    error_observability.uninstall_default_observer()
    try:
        fake_tracer = _FakeTracer()
        fresh = error_tracker.ErrorTracker(db_path=tmp_path / "e.db")
        original = error_observability._get_default_error_tracker
        error_observability._get_default_error_tracker = lambda: fresh
        try:
            observer = error_observability.install_default_observer(tracer=fake_tracer)
            assert observer is not None
            assert fresh.observer_count() == 1
            fresh.record("test_kind", "test_msg")
            assert observer.stats()["events"] >= 1
        finally:
            error_observability._get_default_error_tracker = original
            error_observability.uninstall_default_observer()
    finally:
        error_observability.uninstall_default_observer()


def test_uninstall_returns_false_when_not_installed():
    from agent import error_observability

    error_observability.uninstall_default_observer()
    assert error_observability.uninstall_default_observer() is False


# ── CostTracker subscriber / push_to_tracer ─────────────────────


class _MockUsage:
    """Minimal stand-in for an OpenAI usage object."""

    def __init__(self, prompt=0, completion=0, cached=0) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        if cached:
            self.prompt_tokens_details = type("_D", (), {"cached_tokens": cached})()
        else:
            self.prompt_tokens_details = None


def test_cost_tracker_subscribe_fires_on_record_usage():
    from agent.cost_tracker import CostTracker

    t = CostTracker(model="gpt-4o")
    snapshots: list = []
    t.subscribe(snapshots.append)
    t.record_usage(_MockUsage(prompt=100, completion=200))
    t.record_usage(_MockUsage(prompt=50, completion=25, cached=10))
    assert len(snapshots) == 2
    s = snapshots[-1]
    assert s["input_tokens"] == 150
    assert s["output_tokens"] == 225
    assert s["cached_tokens"] == 10
    assert s["call_count"] == 2
    assert s["model"] == "gpt-4o"
    assert s["total_cost"] > 0


def test_cost_tracker_subscribe_dedup():
    from agent.cost_tracker import CostTracker

    t = CostTracker()
    cb = lambda _s: None  # noqa: E731
    t.subscribe(cb)
    t.subscribe(cb)
    assert t.subscriber_count() == 1
    t.unsubscribe(cb)
    assert t.subscriber_count() == 0


def test_cost_tracker_subscriber_exception_does_not_break_record():
    from agent.cost_tracker import CostTracker

    t = CostTracker()

    def boom(_s):
        raise RuntimeError("kapow")

    t.subscribe(boom)
    # Must not raise.
    t.record_usage(_MockUsage(prompt=10, completion=5))
    assert t.total_input_tokens == 10


def test_cost_tracker_snapshot_is_json_safe():
    import json

    from agent.cost_tracker import CostTracker

    t = CostTracker(model="gpt-4o")
    t.record_usage(_MockUsage(prompt=1000, completion=500))
    snap = t.snapshot()
    # Must round-trip through JSON.
    encoded = json.dumps(snap)
    decoded = json.loads(encoded)
    assert decoded["model"] == "gpt-4o"
    assert decoded["input_tokens"] == 1000
    assert decoded["total_cost"] > 0


def test_cost_tracker_push_to_tracer_uses_fake_tracer():
    from agent.cost_tracker import CostTracker

    tracer = _FakeTracer()
    t = CostTracker(model="gpt-4o")
    t.record_usage(_MockUsage(prompt=1000, completion=500))
    gen_id = t.push_to_tracer(tracer=tracer, trace_id="trace-abc")
    assert gen_id is not None
    assert len(tracer.log_llm_calls) == 1
    call = tracer.log_llm_calls[0]
    assert call["generation_id"] == gen_id
    assert call["model"] == "gpt-4o"
    assert call["input_tokens"] == 1000
    assert call["output_tokens"] == 500
    assert call["cost"] > 0
    assert call["metadata"]["call_count"] == 1


def test_cost_tracker_push_returns_none_when_tracer_disabled():
    from agent.cost_tracker import CostTracker

    tracer = _FakeTracer(enabled=False)
    t = CostTracker(model="gpt-4o")
    t.record_usage(_MockUsage(prompt=10, completion=5))
    assert t.push_to_tracer(tracer=tracer) is None


def test_cost_tracker_push_returns_none_when_no_tracer():
    from agent.cost_tracker import CostTracker

    t = CostTracker(model="gpt-4o")
    t.record_usage(_MockUsage(prompt=10, completion=5))
    # Without env vars, default tracer is enabled=False → returns None
    # without raising.
    assert t.push_to_tracer(tracer=None) is None


def test_cost_tracker_subscription_after_record_still_works():
    """A late subscriber should receive the NEXT snapshot, not history."""
    from agent.cost_tracker import CostTracker

    t = CostTracker(model="gpt-4o")
    t.record_usage(_MockUsage(prompt=100, completion=200))
    captured: list = []
    t.subscribe(captured.append)
    t.record_usage(_MockUsage(prompt=50, completion=50))
    assert len(captured) == 1
    assert captured[0]["input_tokens"] == 150




def test_conversation_loop_pushes_cost_after_tool_execution(monkeypatch):
    """Each tool execution forwards the cost snapshot to the tracer.

    Tools themselves don't add token usage, but a snapshot at the end
    of each tool call guarantees any in-tool cost accumulation reaches
    the remote observability backend without depending on the next LLM
    response.
    """
    from agent.conversation_loop import ConversationLoop

    loop = ConversationLoop.__new__(ConversationLoop)

    class _AgentStub:
        def __init__(self, tracer):
            from agent.cost_tracker import CostTracker
            self._cost_tracker = CostTracker(model="gpt-4o")
            self._cost_tracker.push_to_tracer = lambda **kw: tracer_called.append(tracer)

    tracer_called: list = []
    loop.agent = _AgentStub(tracer_called)
    # Use a real (disabled) tracer to avoid network. push_to_tracer
    # returns None when no tracer is enabled — here we monkey-patch
    # push_to_tracer itself, so the test doesn't depend on env state.
    loop.agent._cost_tracker.push_to_tracer = lambda **kw: tracer_called.append(kw)

    # Stub execute_tool to return a simple string.
    loop.agent.execute_tool = lambda name, args: f"result-of-{name}"

    result = loop._execute_single_tool(
        {
            "id": "call_1",
            "function": {
                "name": "fake_tool",
                "arguments": "{}",
            },
        }
    )

    assert result["role"] == "tool"
    assert result["name"] == "fake_tool"
    # The safety-net push was called.
    assert tracer_called, "expected cost_tracker.push_to_tracer() to be called"


def test_conversation_loop_handles_missing_cost_tracker():
    """When the agent has no _cost_tracker attribute, the safety net is a no-op."""
    from agent.conversation_loop import ConversationLoop

    loop = ConversationLoop.__new__(ConversationLoop)

    class _AgentStub:
        def execute_tool(self, name, args):
            return "ok"

    loop.agent = _AgentStub()
    # Must not raise even though _cost_tracker is absent.
    result = loop._execute_single_tool(
        {"id": "call_1", "function": {"name": "t", "arguments": "{}"}}
    )
    assert result["role"] == "tool"


def test_conversation_loop_survives_push_failure():
    """If push_to_tracer raises, the tool result still gets returned."""
    from agent.conversation_loop import ConversationLoop

    loop = ConversationLoop.__new__(ConversationLoop)

    class _AgentStub:
        def __init__(self):
            from agent.cost_tracker import CostTracker
            self._cost_tracker = CostTracker(model="gpt-4o")

        def execute_tool(self, name, args):
            return "ok"

    loop.agent = _AgentStub()
    def _boom(**_kw):
        raise RuntimeError("net down")

    loop.agent._cost_tracker.push_to_tracer = _boom

    result = loop._execute_single_tool(
        {"id": "call_1", "function": {"name": "t", "arguments": "{}"}}
    )
    assert result["role"] == "tool"
    assert result["content"]  # sanitized result still present


# ── End-to-end: error_tracker → error_observability → Langfuse ──


def test_end_to_end_error_tracker_to_observer_to_tracer(tmp_path):
    from agent.error_observability import ErrorObserver
    from agent.error_tracker import ErrorTracker

    tracker = ErrorTracker(db_path=tmp_path / "e.db")
    tracer = _FakeTracer()
    observer = ErrorObserver(tracer=tracer)
    tracker.attach_observer(observer)

    tracker.record(
        "rate_limit",
        "429 too many requests",
        severity="warning",
        session_id="sess-x",
        provider="openai",
        model="gpt-4o",
    )

    assert len(tracer.log_tool_calls) == 1
    call = tracer.log_tool_calls[0]
    assert call["tool_name"] == "error:rate_limit"
    assert call["level"] == "WARNING"
    assert call["metadata"]["error_category"] == "rate_limit"
    assert call["metadata"]["session_id"] == "sess-x"
    assert call["metadata"]["provider"] == "openai"
    assert call["metadata"]["model"] == "gpt-4o"


def test_record_exception_pushes_stack_trace_preview_to_tracer(tmp_path):
    """record_exception(exc) -> observer -> Langfuse metadata.stack_trace_preview (<=1000 chars)."""
    from agent.error_observability import ErrorObserver
    from agent.error_tracker import ErrorTracker

    tracker = ErrorTracker(db_path=tmp_path / "e.db")
    tracer = _FakeTracer()
    observer = ErrorObserver(tracer=tracer)
    tracker.attach_observer(observer)

    # Build a fake long trace so we exercise the truncation logic.
    long_trace = "Traceback (most recent call last):\n" + ("x" * 1500)
    fake_exc = RuntimeError("boom")
    fake_exc.__traceback__ = None
    tracker.record_exception(
        fake_exc,
        severity="error",
        category="auth",
        context={"trace_override": long_trace},
    )
    # Manually attach a long stack via record() since record_exception uses
    # traceback.format_exception with the live exc.
    tracker.record(
        "auth",
        "boom (manually attached)",
        severity="error",
        stack_trace=long_trace,
    )

    assert len(tracer.log_tool_calls) >= 1
    # Inspect the second event (manually attached long trace).
    call = tracer.log_tool_calls[-1]
    preview = call["metadata"].get("stack_trace_preview")
    assert preview is not None, "expected stack_trace_preview in metadata"
    assert isinstance(preview, str)
    assert len(preview) <= 1000, f"preview too long: {len(preview)}"
    assert "x" * 1500 not in preview
    assert call["metadata"]["has_stack_trace"] is True
    # Full trace remains in the local SQLite store.
    rows = tracker.query(category="auth")
    full = next(r.stack_trace for r in rows if "x" * 1500 in r.stack_trace)
    assert "x" * 1500 in full
