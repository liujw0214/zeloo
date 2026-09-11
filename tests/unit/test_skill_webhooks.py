"""Tests for skill_webhooks module — webhook registry, signing, dispatcher."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Queue

sys.path.insert(0, ".")


# ── HMAC signing ─────────────────────────────────────────────────


def test_sign_and_verify_round_trip():
    from agent.skill_webhooks import sign_payload, verify_signature

    body = b'{"hello":"world"}'
    secret = "shh"
    sig = sign_payload(secret, body)
    assert sig.startswith("sha256=")
    assert verify_signature(secret, body, sig) is True
    assert verify_signature("wrong", body, sig) is False
    assert verify_signature(secret, body, "") is False


def test_sign_empty_secret_returns_empty():
    from agent.skill_webhooks import sign_payload, verify_signature

    assert sign_payload("", b"x") == ""
    assert verify_signature("", b"x", "sha256=abc") is False


# ── Subscriber (de)serialization ────────────────────────────────


def test_subscriber_to_from_dict_round_trip():
    from agent.skill_webhooks import WebhookSubscriber

    s = WebhookSubscriber(
        name="n1",
        url="https://example.com/hook",
        secret="s3",
        headers={"X-Auth": "Bearer x"},
        events={"added", "modified"},
        max_retries=2,
    )
    d = s.to_dict()
    # Sets serialize as sorted lists
    assert sorted(d["events"]) == ["added", "modified"]
    s2 = WebhookSubscriber.from_dict(d)
    assert s2.name == "n1"
    assert s2.secret == "s3"
    assert s2.events == {"added", "modified"}
    assert s2.max_retries == 2


def test_subscriber_from_dict_minimal():
    from agent.skill_webhooks import WebhookSubscriber

    s = WebhookSubscriber.from_dict({"name": "x", "url": "http://a"})
    assert s.name == "x"
    assert s.enabled is True
    assert s.events is None
    assert s.max_retries == 3


# ── Registry persistence ─────────────────────────────────────────


def test_registry_persists_to_disk():
    from agent.skill_webhooks import WebhookRegistry, WebhookSubscriber

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "hooks.json"
        reg = WebhookRegistry(path=path)
        reg.add(WebhookSubscriber(name="a", url="http://a", secret="s"))
        reg.add(WebhookSubscriber(name="b", url="http://b"))
        assert path.is_file()

        # Fresh load
        reg2 = WebhookRegistry(path=path)
        names = {s.name for s in reg2.all()}
        assert names == {"a", "b"}


def test_registry_remove():
    from agent.skill_webhooks import WebhookRegistry, WebhookSubscriber

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "hooks.json"
        reg = WebhookRegistry(path=path)
        reg.add(WebhookSubscriber(name="x", url="http://x"))
        assert reg.remove("x") is True
        assert reg.remove("x") is False
        assert len(reg) == 0


def test_registry_enable_disable():
    from agent.skill_webhooks import WebhookRegistry, WebhookSubscriber

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "hooks.json"
        reg = WebhookRegistry(path=path)
        reg.add(WebhookSubscriber(name="e", url="http://e"))
        assert reg.enable("e", enabled=False) is True
        assert reg.get("e").enabled is False
        assert reg.enable("missing", enabled=False) is False
        assert reg.enabled_for("added") == []


def test_registry_enabled_for_filters_by_event_kind():
    from agent.skill_webhooks import WebhookRegistry, WebhookSubscriber

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "hooks.json"
        reg = WebhookRegistry(path=path)
        reg.add(WebhookSubscriber(name="only_added", url="http://a", events={"added"}))
        reg.add(WebhookSubscriber(name="all", url="http://b"))
        reg.add(WebhookSubscriber(name="disabled", url="http://c", enabled=False))

        added_subs = reg.enabled_for("added")
        assert {s.name for s in added_subs} == {"only_added", "all"}

        removed_subs = reg.enabled_for("removed")
        assert {s.name for s in removed_subs} == {"all"}


def test_registry_reload_corrupt_json_falls_back_to_empty():
    from agent.skill_webhooks import WebhookRegistry

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "hooks.json"
        path.write_text("not json {{{", encoding="utf-8")
        reg = WebhookRegistry(path=path)
        assert len(reg) == 0


# ── Dispatcher (in-memory) ──────────────────────────────────────


class _FakeChangeEvent:
    """Minimal stand-in for SkillChangeEvent for the dispatcher tests."""

    def __init__(self, kind: str, name: str = "alpha") -> None:
        self.kind = kind
        self.skill_name = name
        self.path = Path(f"/skills/{name}/SKILL.md")
        self.previous_mtime = None
        self.current_mtime = 1234567890


def test_dispatcher_enqueues_and_skips_when_full():
    from agent.skill_webhooks import WebhookDispatcher, WebhookRegistry

    with tempfile.TemporaryDirectory() as td:
        reg = WebhookRegistry(path=Path(td) / "h.json")
        d = WebhookDispatcher(reg, queue_maxsize=2)
        assert d.enqueue_event(_FakeChangeEvent("added")) is True
        assert d.enqueue_event(_FakeChangeEvent("modified")) is True
        assert d.enqueue_event(_FakeChangeEvent("removed")) is False  # dropped
        s = d.stats()
        assert s["enqueued"] == 2
        assert s["dropped"] == 1


def test_dispatcher_delivers_to_http_endpoint(tmp_path):
    """End-to-end: enqueue, deliver, verify body + signature."""
    from agent.skill_webhooks import (
        WebhookDispatcher,
        WebhookRegistry,
        WebhookSubscriber,
        verify_signature,
    )

    received: Queue = Queue()
    secret = "topsecret"

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            received.put(
                {
                    "body": body,
                    "event_id": self.headers.get("X-Zeloo-Event-Id"),
                    "kind": self.headers.get("X-Zeloo-Event-Kind"),
                    "signature": self.headers.get("X-Zeloo-Signature"),
                    "attempt": self.headers.get("X-Zeloo-Delivery-Attempt"),
                }
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_a, **_kw):  # silence
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        reg = WebhookRegistry(path=tmp_path / "h.json")
        reg.add(
            WebhookSubscriber(
                name="local",
                url=f"http://127.0.0.1:{port}/hook",
                secret=secret,
                timeout_s=2.0,
                max_retries=0,
            )
        )
        dispatcher = WebhookDispatcher(reg)
        dispatcher.enqueue_event(_FakeChangeEvent("added", "beta"))

        # Drive delivery synchronously (no background thread).
        dispatcher._deliver_to_all(  # noqa: SLF001
            {
                "event_id": "evt_test",
                "kind": "added",
                "skill_name": "beta",
                "path": "/x",
                "previous_mtime": None,
                "current_mtime": 1,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )

        msg = received.get(timeout=2.0)
        assert msg["event_id"] == "evt_test"
        assert msg["kind"] == "added"
        assert msg["attempt"] == "1"
        assert verify_signature(secret, msg["body"], msg["signature"])
        # The body is the same JSON we built.
        body = json.loads(msg["body"])
        assert body["skill_name"] == "beta"
        assert body["kind"] == "added"

        stats = dispatcher.stats()
        assert stats["delivered"] == 1
        assert stats["failed"] == 0
    finally:
        server.shutdown()
        server.server_close()


def test_dispatcher_retries_on_5xx_and_eventually_fails(tmp_path):
    """5xx → retry → give up; stats['failed'] increments."""
    from agent.skill_webhooks import (
        WebhookDispatcher,
        WebhookRegistry,
        WebhookSubscriber,
    )

    attempt_counter = {"n": 0}

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            attempt_counter["n"] += 1
            self.send_response(503)
            self.end_headers()

        def log_message(self, *_a, **_kw):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        reg = WebhookRegistry(path=tmp_path / "h.json")
        reg.add(
            WebhookSubscriber(
                name="flaky",
                url=f"http://127.0.0.1:{port}/",
                max_retries=2,
                backoff_base_s=0.01,
                timeout_s=1.0,
            )
        )
        dispatcher = WebhookDispatcher(reg)
        result = dispatcher._deliver_one(  # noqa: SLF001
            reg.get("flaky"),
            {"event_id": "e1", "kind": "added", "skill_name": "x", "path": "/x",
             "previous_mtime": None, "current_mtime": 1, "timestamp": "t"},
        )
        assert result.success is False
        assert result.attempts == 3  # 1 initial + 2 retries
        assert attempt_counter["n"] == 3
    finally:
        server.shutdown()
        server.server_close()


def test_dispatcher_does_not_retry_4xx(tmp_path):
    from agent.skill_webhooks import (
        WebhookDispatcher,
        WebhookRegistry,
        WebhookSubscriber,
    )

    attempts = {"n": 0}

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            attempts["n"] += 1
            self.send_response(404)
            self.end_headers()

        def log_message(self, *_a, **_kw):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        reg = WebhookRegistry(path=tmp_path / "h.json")
        reg.add(
            WebhookSubscriber(
                name="bad",
                url=f"http://127.0.0.1:{port}/",
                max_retries=5,
                backoff_base_s=0.01,
                timeout_s=1.0,
            )
        )
        dispatcher = WebhookDispatcher(reg)
        result = dispatcher._deliver_one(  # noqa: SLF001
            reg.get("bad"),
            {"event_id": "e2", "kind": "modified", "skill_name": "y", "path": "/y",
             "previous_mtime": 1, "current_mtime": 2, "timestamp": "t"},
        )
        assert result.success is False
        assert attempts["n"] == 1
    finally:
        server.shutdown()
        server.server_close()


def test_dispatcher_on_delivery_callback(tmp_path):
    """The optional on_delivery hook fires with DeliveryResult."""
    from agent.skill_webhooks import (
        WebhookDispatcher,
        WebhookRegistry,
        WebhookSubscriber,
    )

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_a, **_kw):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        reg = WebhookRegistry(path=tmp_path / "h.json")
        reg.add(WebhookSubscriber(name="ok", url=f"http://127.0.0.1:{port}/"))

        seen: list = []

        def on_delivery(result):
            seen.append(result)

        d = WebhookDispatcher(reg, on_delivery=on_delivery)
        d._deliver_to_all(  # noqa: SLF001
            {"event_id": "e3", "kind": "added", "skill_name": "z", "path": "/z",
             "previous_mtime": None, "current_mtime": 1, "timestamp": "t"}
        )
        assert len(seen) == 1
        assert seen[0].success is True
    finally:
        server.shutdown()
        server.server_close()


# ── Background worker ───────────────────────────────────────────


def test_dispatcher_start_stop_and_drains_queue(tmp_path):
    """Background thread should drain enqueued events."""
    from agent.skill_webhooks import (
        WebhookDispatcher,
        WebhookRegistry,
        WebhookSubscriber,
    )

    seen: Queue = Queue()

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            seen.put(json.loads(body))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_a, **_kw):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        reg = WebhookRegistry(path=tmp_path / "h.json")
        reg.add(WebhookSubscriber(name="bg", url=f"http://127.0.0.1:{port}/"))
        d = WebhookDispatcher(reg)
        d.start()
        try:
            d.enqueue_event(_FakeChangeEvent("added", "skillA"))
            d.enqueue_event(_FakeChangeEvent("modified", "skillB"))
            # Wait for both deliveries.
            for _ in range(40):
                if seen.qsize() >= 2:
                    break
                time.sleep(0.05)
            names = sorted(item["skill_name"] for item in list(seen.queue))
            assert names == ["skillA", "skillB"]
        finally:
            d.stop(timeout=2.0)
    finally:
        server.shutdown()
        server.server_close()


# ── Integration with SkillHotReloader ──────────────────────────


def test_attach_to_reloader_fires_webhook(tmp_path):
    """End-to-end: poll on the reloader → dispatcher delivers to endpoint."""
    from agent.skill_hot_reload import SkillHotReloader
    from agent.skill_webhooks import (
        WebhookRegistry,
        WebhookSubscriber,
        attach_to,
    )

    received: Queue = Queue()

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            received.put(json.loads(body))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_a, **_kw):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        reg = WebhookRegistry(path=tmp_path / "h.json")
        reg.add(WebhookSubscriber(name="plug", url=f"http://127.0.0.1:{port}/"))

        skills_root = tmp_path / "skills"
        skills_root.mkdir()
        reloader = SkillHotReloader(roots=[skills_root])
        dispatcher = attach_to(reloader, registry=reg, start=True)
        try:
            # Add a skill
            (skills_root / "alpha").mkdir()
            (skills_root / "alpha" / "SKILL.md").write_text("x", encoding="utf-8")
            reloader.poll()

            for _ in range(40):
                if not received.empty():
                    break
                time.sleep(0.05)
            assert not received.empty()
            payload = received.get(timeout=1.0)
            assert payload["kind"] == "added"
            assert payload["skill_name"] == "alpha"
        finally:
            dispatcher.stop(timeout=2.0)
    finally:
        server.shutdown()
        server.server_close()


# ── Module-level singleton ─────────────────────────────────────


def test_get_default_registry_singleton():
    from agent import skill_webhooks

    skill_webhooks.reset_default_registry()
    try:
        a = skill_webhooks.get_default_registry()
        b = skill_webhooks.get_default_registry()
        assert a is b
    finally:
        skill_webhooks.reset_default_registry()
