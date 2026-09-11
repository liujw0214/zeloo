"""Tests for agent/langfuse_integration.py."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from agent.langfuse_integration import (
    LangfuseClient,
    LangfuseTracer,
    TraceContext,
)


def test_trace_context_creation() -> None:
    """Test that TraceContext is properly initialized."""
    trace_id = str(uuid.uuid4())
    start_time = datetime.now(UTC)
    context = TraceContext(
        trace_id=trace_id,
        name="test_trace",
        start_time=start_time,
        metadata={"key": "value"},
    )

    assert context.trace_id == trace_id
    assert context.name == "test_trace"
    assert context.start_time == start_time
    assert context.metadata == {"key": "value"}
    assert context.end_time is None
    assert context.tags == []
    assert context.user_id is None


def test_tracer_disabled_without_credentials() -> None:
    """Test that tracer is disabled when credentials are missing."""
    with patch.dict("os.environ", {}, clear=True):
        tracer = LangfuseTracer(enabled=True)
        assert tracer.enabled is False
        assert tracer.client is None


def test_tracer_disabled_explicitly() -> None:
    """Test that tracer is disabled when explicitly set."""
    tracer = LangfuseTracer(
        public_key="pk_test",
        secret_key="sk_test",
        enabled=False,
    )
    assert tracer.enabled is False


def test_tracer_enabled_with_credentials() -> None:
    """Test that tracer is enabled with valid credentials."""
    tracer = LangfuseTracer(
        public_key="pk_test",
        secret_key="sk_test",
        enabled=True,
    )
    assert tracer.enabled is True
    assert tracer.client is not None
    tracer.flush()


@pytest.mark.slow
def test_log_llm_call_returns_generation_id() -> None:
    """Test that log_llm_call returns a generation ID."""
    tracer = LangfuseTracer(
        public_key="pk_test",
        secret_key="sk_test",
        enabled=True,
    )

    generation_id = tracer.log_llm_call(
        trace_id="trace_123",
        model="gpt-4",
        input_tokens=100,
        output_tokens=50,
        cost=0.01,
        latency_ms=500.0,
    )

    assert generation_id is not None
    assert isinstance(generation_id, str)
    tracer.flush()


@pytest.mark.slow
def test_log_tool_call_returns_span_id() -> None:
    """Test that log_tool_call returns a span ID."""
    tracer = LangfuseTracer(
        public_key="pk_test",
        secret_key="sk_test",
        enabled=True,
    )

    span_id = tracer.log_tool_call(
        trace_id="trace_123",
        tool_name="test_tool",
        duration_ms=200.0,
        success=True,
        metadata={"arg": "value"},
    )

    assert span_id is not None
    assert isinstance(span_id, str)
    tracer.flush()


def test_log_llm_call_disabled_tracer_returns_none() -> None:
    """Test that log_llm_call returns None when tracer is disabled."""
    tracer = LangfuseTracer(enabled=False)

    result = tracer.log_llm_call(
        trace_id="trace_123",
        model="gpt-4",
        input_tokens=100,
        output_tokens=50,
    )

    assert result is None


def test_log_tool_call_disabled_tracer_returns_none() -> None:
    """Test that log_tool_call returns None when tracer is disabled."""
    tracer = LangfuseTracer(enabled=False)

    result = tracer.log_tool_call(
        trace_id="trace_123",
        tool_name="test_tool",
        duration_ms=200.0,
    )

    assert result is None


@pytest.mark.slow
def test_trace_context_manager() -> None:
    """Test trace context manager creates and cleans up trace context."""
    tracer = LangfuseTracer(
        public_key="pk_test",
        secret_key="sk_test",
        enabled=True,
    )

    with tracer.trace("test_operation", metadata={"test": True}) as context:
        assert context.trace_id is not None
        assert context.name == "test_operation"
        assert context.metadata == {"test": True}
        assert context.end_time is None

    assert context.end_time is not None
    tracer.flush()


def test_langfuse_client_url_construction() -> None:
    """Test LangfuseClient URL construction."""
    client = LangfuseClient(
        public_key="pk_test",
        secret_key="sk_test",
        host="https://custom.langfuse.com",
    )

    assert (
        client._make_url("/traces") == "https://custom.langfuse.com/api/public/traces"
    )
    assert (
        client._make_url("/generations")
        == "https://custom.langfuse.com/api/public/generations"
    )


def test_langfuse_client_default_host() -> None:
    """Test LangfuseClient uses default host."""
    client = LangfuseClient(
        public_key="pk_test",
        secret_key="sk_test",
    )

    assert client.host == "https://cloud.langfuse.com"


def test_langfuse_client_host_trailing_slash() -> None:
    """Test LangfuseClient strips trailing slashes from host."""
    client = LangfuseClient(
        public_key="pk_test",
        secret_key="sk_test",
        host="https://custom.langfuse.com/",
    )

    assert client.host == "https://custom.langfuse.com"
