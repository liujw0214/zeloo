"""Tests for tools/output_scan.py and the shared tool-output scanner."""

from __future__ import annotations

import sys

sys.path.insert(0, ".")


# ── Core helper ────────────────────────────────────────────────────


def test_scan_tool_output_redacts_openai_key():
    from tools.output_scan import scan_tool_output

    out = scan_tool_output(
        "Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz1234567890",
        tool_name="t",
        source="example",
    )
    assert "sk-abcdef" not in out
    assert "[REDACTED]" in out
    assert "[Zeloo: redacted" in out


def test_scan_tool_output_passthrough_when_clean():
    from tools.output_scan import scan_tool_output

    text = "the quick brown fox jumps over the lazy dog"
    out = scan_tool_output(text, tool_name="t", source="example")
    assert out == text


def test_scan_tool_output_empty_returns_empty():
    from tools.output_scan import scan_tool_output

    assert scan_tool_output("", tool_name="t", source="") == ""


def test_scan_tool_output_disabled_returns_input():
    from tools.output_scan import scan_tool_output, set_output_scan_enabled

    set_output_scan_enabled(False)
    try:
        text = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
        out = scan_tool_output(text, tool_name="t", source="x")
        assert out == text
    finally:
        set_output_scan_enabled(True)


def test_low_severity_does_not_redact():
    """password=... is LOW severity with auto_redact=False — content kept verbatim."""
    from tools.output_scan import scan_tool_output

    text = "config:\n  password=hunter2hunter2abc\n"
    out = scan_tool_output(text, tool_name="t", source="cfg")
    assert out == text


def test_audit_event_written_on_redaction(tmp_path, monkeypatch):
    from agent import audit_log
    from tools.output_scan import scan_tool_output

    audit_log.reset_default_audit_log()
    monkeypatch.setattr(audit_log, "_default", audit_log.AuditLog(path=tmp_path / "a.log"))
    try:
        scan_tool_output(
            "sk-abcdefghijklmnopqrstuvwxyz1234567890",
            tool_name="mytool",
            source="src1",
        )
        events = list(audit_log.get_default_audit_log().iter_events())
        assert any(e.kind == "tool_output_secret_found" for e in events)
        # Tool name + source are preserved.
        match = next(e for e in events if e.kind == "tool_output_secret_found")
        assert match.detail["tool"] == "mytool"
        assert match.detail["source"] == "src1"
    finally:
        audit_log.reset_default_audit_log()


def test_scan_tool_output_does_not_raise_when_scanner_crashes(monkeypatch):
    """A scanner crash must return content unchanged, not raise."""
    from agent import secret_scanner
    from tools.output_scan import scan_tool_output

    class _Boom:
        def scan_and_redact(self, *_a, **_kw):
            raise RuntimeError("kapow")

    monkeypatch.setattr(secret_scanner, "SecretScanner", _Boom)
    text = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
    out = scan_tool_output(text, tool_name="t", source="x")
    assert out == text


# ── shell_tool integration ────────────────────────────────────────


def test_shell_redacts_openai_key_in_output(tmp_path, monkeypatch):
    """When a command prints a secret, the returned output is redacted."""
    from tools import shell_tool
    from tools.output_scan import set_output_scan_enabled

    set_output_scan_enabled(True)
    try:
        # Use the real local backend.
        from terminal.local import LocalBackend

        backend = LocalBackend()
        result = backend.execute(
            "echo sk-abcdefghijklmnopqrstuvwxyz1234567890",
            timeout=10,
        )
        out = shell_tool.scan_tool_output(
            result.stdout,
            tool_name="shell",
            source="echo …",
        )
        assert "sk-abcdef" not in out
        assert "[REDACTED]" in out
    finally:
        set_output_scan_enabled(True)


# ── web_fetch integration (mocked HTTP) ───────────────────────────


def test_web_fetch_redacts_secrets(monkeypatch):
    """web_fetch() should redact secrets returned from the page body."""
    import httpx

    from tools import web_tools

    class _FakeResp:
        status_code = 200

        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

    body = (
        "<html><body>"
        "API token: sk-abcdefghijklmnopqrstuvwxyz1234567890"
        "</body></html>"
    )

    def fake_get(url, timeout=15, follow_redirects=True):  # noqa: A001
        return _FakeResp(body)

    monkeypatch.setattr(httpx, "get", fake_get)

    out = web_tools.web_fetch("https://example.com/page")
    assert "sk-abcdef" not in out
    assert "[REDACTED]" in out


# ── system_prompt integration ────────────────────────────────────


def test_system_prompt_scrubs_memory_block():
    """Memory blocks with leaked credentials are scrubbed before injection."""
    from agent import system_prompt

    class _FakeMemoryStore:
        def format_for_system_prompt(self, kind: str) -> str:
            return f"## {kind.upper()}\nuser saved token: sk-abcdefghijklmnopqrstuvwxyz1234567890"

    class _FakeAgent:
        valid_tool_names: set[str] = set()
        available_toolsets: set[str] = set()
        platform = "cli"
        _memory_store = _FakeMemoryStore()
        _memory_enabled = True
        _user_profile_enabled = True
        load_soul_identity = False
        skip_context_files = True
        messages: list = []

    parts = system_prompt._memory_parts(_FakeAgent())
    joined = "\n".join(parts)
    assert "sk-abcdef" not in joined
    assert "[REDACTED]" in joined


def test_system_prompt_history_snapshot_redacts_secrets():
    """The history snapshot scans recent messages before injecting them."""
    from agent import system_prompt

    class _Agent:
        _history_snapshot_turns = 2
        messages = [
            {"role": "user", "content": "what is my token?"},
            {
                "role": "assistant",
                "content": (
                    "It is sk-abcdefghijklmnopqrstuvwxyz1234567890"
                ),
            },
            {"role": "user", "content": "thanks"},
            {"role": "assistant", "content": "welcome"},
        ]

    snap = system_prompt._history_snapshot(_Agent())
    assert "Recent Conversation" in snap
    assert "sk-abcdef" not in snap
    assert "[REDACTED]" in snap


def test_system_prompt_history_snapshot_disabled_when_zero_turns():
    from agent import system_prompt

    class _Agent:
        _history_snapshot_turns = 0
        messages = [{"role": "user", "content": "sk-abcdefghijklmnopqrstuvwxyz1234567890"}]

    assert system_prompt._history_snapshot(_Agent()) == ""


def test_system_prompt_history_snapshot_empty_when_no_messages():
    from agent import system_prompt

    class _Agent:
        _history_snapshot_turns = 2
        messages = []

    assert system_prompt._history_snapshot(_Agent()) == ""


def test_system_prompt_history_snapshot_truncates_long_messages():
    from agent import system_prompt

    class _Agent:
        _history_snapshot_turns = 1
        messages = [
            {"role": "user", "content": "x" * 5000},
            {"role": "assistant", "content": "ok"},
        ]

    snap = system_prompt._history_snapshot(_Agent())
    assert "truncated" in snap
    # Original giant content is gone.
    assert "x" * 1500 in snap
    assert "x" * 5000 not in snap


def test_system_prompt_audit_event_on_secret_in_history(tmp_path, monkeypatch):
    """A secret in the history snapshot triggers a system_prompt audit event."""
    from agent import audit_log, system_prompt

    audit_log.reset_default_audit_log()
    monkeypatch.setattr(audit_log, "_default", audit_log.AuditLog(path=tmp_path / "a.log"))
    try:
        class _Agent:
            _history_snapshot_turns = 1
            messages = [
                {"role": "user", "content": "k"},
                {
                    "role": "assistant",
                    "content": "sk-abcdefghijklmnopqrstuvwxyz1234567890",
                },
            ]

        system_prompt._history_snapshot(_Agent())
        events = list(audit_log.get_default_audit_log().iter_events())
        assert any(e.kind == "system_prompt_secret_found" for e in events)
    finally:
        audit_log.reset_default_audit_log()


# ── conversation_loop unified tool_result scan ────────────────────


def test_sanitize_result_redacts_secrets_through_conversation_loop():
    """Every tool_result flowing through the loop gets scanned, regardless of tool."""
    from agent.conversation_loop import ConversationLoop

    loop = ConversationLoop.__new__(ConversationLoop)
    # No agent attribute needed — _sanitize_result only uses it for execute_tool.
    text = loop._sanitize_result(
        "api key: sk-abcdefghijklmnopqrstuvwxyz1234567890",
        tool_name="file_read",
    )
    assert "sk-abcdef" not in text
    assert "[REDACTED]" in text
    assert "[Zeloo: redacted" in text


def test_sanitize_result_uses_tool_name_in_audit(tmp_path, monkeypatch):
    from agent import audit_log
    from agent.conversation_loop import ConversationLoop

    audit_log.reset_default_audit_log()
    monkeypatch.setattr(audit_log, "_default", audit_log.AuditLog(path=tmp_path / "a.log"))
    try:
        loop = ConversationLoop.__new__(ConversationLoop)
        loop._sanitize_result(
            "AKIAIOSFODNN7EXAMPLE",
            tool_name="my_custom_tool",
        )
        events = list(audit_log.get_default_audit_log().iter_events())
        match = [e for e in events if e.kind == "tool_output_secret_found"]
        assert match
        assert match[0].detail["tool"] == "my_custom_tool"
    finally:
        audit_log.reset_default_audit_log()


def test_sanitize_result_truncates_long_output(monkeypatch):
    """Truncation still applies after scanning."""
    from agent.conversation_loop import ConversationLoop

    loop = ConversationLoop.__new__(ConversationLoop)
    long_text = "x" * 50000
    out = loop._sanitize_result(long_text, tool_name="file_read")
    assert "[truncated]" in out
    assert len(out) < 50000


def test_sanitize_result_passthrough_for_clean_content():
    from agent.conversation_loop import ConversationLoop

    loop = ConversationLoop.__new__(ConversationLoop)
    out = loop._sanitize_result("just plain text", tool_name="file_read")
    assert out == "just plain text"


def test_sanitize_result_survives_scanner_crash(monkeypatch):
    """A scanner crash must return content (possibly unredacted) — never raise."""
    from agent import secret_scanner
    from agent.conversation_loop import ConversationLoop

    class _Boom:
        def scan_and_redact(self, *_a, **_kw):
            raise RuntimeError("scanner down")

    monkeypatch.setattr(secret_scanner, "SecretScanner", _Boom)
    loop = ConversationLoop.__new__(ConversationLoop)
    out = loop._sanitize_result("plain text", tool_name="file_read")
    assert out == "plain text"
