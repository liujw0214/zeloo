"""Concurrent performance tests for the API server and provider router.

These tests verify that the server handles concurrent requests correctly
and that rate limiting works under load. They use a fake agent that
returns immediately, so they don't require a real LLM API key.
"""

# ruff: noqa: E402
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

import os

import pytest

os.environ.setdefault("zeloo_HOME", tempfile.mkdtemp())


def _make_fake_agent_factory():
    """Create an agent factory that returns a fake agent (no LLM calls)."""
    calls = {"count": 0}
    lock = threading.Lock()

    def factory(**kwargs):
        class FakeAgent:
            session_id = "fake-session"

            def run_conversation(self, msg, **kw):
                with lock:
                    calls["count"] += 1
                return f"echo: {msg}"

            def close(self):
                pass

        return FakeAgent()

    return factory, calls


@pytest.mark.slow
def test_api_server_concurrent_requests():
    """The API server should handle 20 concurrent requests without errors."""
    from gateway.api_server import APIServer

    factory, calls = _make_fake_agent_factory()
    server = APIServer(
        agent_factory=factory,
        host="127.0.0.1",
        port=8791,
        rate_limit_capacity=100,
        rate_limit_rate=100.0,
    )
    server.start()
    time.sleep(0.5)

    def _make_request(i):
        body = json.dumps({"messages": [{"role": "user", "content": f"msg-{i}"}]}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8791/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read())

    n = 20
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_make_request, i) for i in range(n)]
        results = [f.result() for f in as_completed(futures)]

    server.stop()

    assert len(results) == n
    for r in results:
        assert "choices" in r
        assert r["choices"][0]["message"]["content"].startswith("echo:")
    assert calls["count"] == n


@pytest.mark.slow
def test_rate_limiter_blocks_excess_requests():
    """Requests beyond the rate limit should return 429."""
    from gateway.api_server import APIServer

    factory, _ = _make_fake_agent_factory()
    server = APIServer(
        agent_factory=factory,
        host="127.0.0.1",
        port=8792,
        rate_limit_capacity=3,
        rate_limit_rate=0.0,
    )
    server.start()
    time.sleep(0.5)

    statuses = []
    for _ in range(5):
        body = json.dumps({"messages": [{"role": "user", "content": "x"}]}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8792/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            statuses.append(resp.status)
        except urllib.error.HTTPError as e:
            statuses.append(e.code)

    server.stop()

    # First 3 should be 200, next 2 should be 429
    assert statuses[:3] == [200, 200, 200]
    assert 429 in statuses[3:]


def test_concurrent_session_isolation():
    """Concurrent agents must not share session state."""
    from gateway.session import SessionManager

    class FakeDB:
        def __init__(self):
            self.lock = threading.Lock()
            self.sessions = []

        def create_session(self, sid, user_id="", platform="cli"):
            with self.lock:
                self.sessions.append((sid, user_id, platform))

        def get_active_session(self, uid, plat):
            return None

    mgr = SessionManager(FakeDB())

    def _make_agent(session_id, platform, user_id=""):
        class A:
            def __init__(self):
                self.session_id = session_id

            def close(self):
                pass
        return A()

    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [
            ex.submit(mgr.get_or_create_agent, f"u{i}", "cli", _make_agent)
            for i in range(16)
        ]
        for f in as_completed(futures):
            results.append(f.result())

    session_ids = {r.session_id for r in results}
    assert len(session_ids) == 16  # all unique
    assert mgr.get_active_count() == 16


if __name__ == "__main__":
    test_api_server_concurrent_requests()
    test_rate_limiter_blocks_excess_requests()
    test_concurrent_session_isolation()
    print("All concurrent tests passed!")
