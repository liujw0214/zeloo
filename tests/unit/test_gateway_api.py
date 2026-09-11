"""Unit tests for the OpenAI-compatible gateway API (H1-H4)."""

# ruff: noqa: E402
from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import time
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

import os

os.environ.setdefault("zeloo_HOME", tempfile.mkdtemp())

import pytest

from gateway.api_server import APIServer


# ────────────────────────────────────────────────────────────────────
# Fakes
# ────────────────────────────────────────────────────────────────────


class FakeAgent:
    """Records calls and returns canned responses for tests."""

    def __init__(
        self,
        *,
        text: str = "ok",
        tool_calls: list[dict] | None = None,
        tokens: list[str] | None = None,
    ) -> None:
        self.session_id = "sess-test"
        self._text = text
        self._tool_calls = tool_calls or []
        self._tokens = tokens
        self.platform = "api"
        self.run_calls: list[str] = []
        self.stream_calls: list[tuple[list[dict], object | None]] = []

    def run_conversation(self, user_message: str) -> str:
        self.run_calls.append(user_message)
        return self._text

    def call_llm_stream(self, messages, on_token=None):
        self.stream_calls.append((list(messages), on_token))
        if self._tokens is not None:
            for token in self._tokens:
                if on_token is not None:
                    on_token(token)
        result: dict = {"content": "".join(self._tokens) if self._tokens else self._text}
        if self._tool_calls:
            result["tool_calls"] = self._tool_calls
        return result


def _make_agent_factory(agent):
    return lambda **kwargs: agent


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _LiveServer:
    """Spin up an APIServer on a free port and tear it down after the test."""

    def __init__(self, agent: FakeAgent, **server_kwargs) -> None:
        self.agent = agent
        self.port = _free_port()
        self.server = APIServer(
            agent_factory=_make_agent_factory(agent),
            host="127.0.0.1",
            port=self.port,
            **server_kwargs,
        )
        self.server.start()
        # Give the thread a moment to bind.
        time.sleep(0.05)

    def request(self, method: str, path: str, body: dict | None = None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, dict(resp.getheaders()), raw

    def close(self) -> None:
        self.server.stop()


# ────────────────────────────────────────────────────────────────────
# H4 — dynamic model list
# ────────────────────────────────────────────────────────────────────


class TestGatewayModels:
    def test_list_models_returns_openai_format(self):
        """Without providers, /v1/models returns the configured model_name."""
        server = APIServer(
            agent_factory=lambda **k: MagicMock(), model_name="test-model"
        )
        with patch(
            "gateway.api_server._get_provider_names", return_value=[]
        ):
            live = _LiveServer(FakeAgent(), model_name="test-model")
            try:
                status, headers, raw = live.request("GET", "/v1/models")
                assert status == 200
                assert headers["Content-Type"].startswith("application/json")
                body = json.loads(raw.decode("utf-8"))
                assert body["object"] == "list"
                assert isinstance(body["data"], list)
                assert len(body["data"]) == 1
                item = body["data"][0]
                assert item["object"] == "model"
                assert item["id"] == "test-model"
                assert item["owned_by"] == "Zeloo"
                assert isinstance(item["created"], int)
            finally:
                live.close()

    def test_dynamic_model_list(self):
        """With providers, /v1/models returns one entry per provider."""
        with patch(
            "gateway.api_server._get_provider_names",
            return_value=["openai", "anthropic"],
        ):
            live = _LiveServer(FakeAgent())
            try:
                _, _, raw = live.request("GET", "/v1/models")
                body = json.loads(raw.decode("utf-8"))
                ids = [m["id"] for m in body["data"]]
                assert "openai" in ids
                assert "anthropic" in ids
                for item in body["data"]:
                    assert item["object"] == "model"
                    assert item["owned_by"] == item["id"]
            finally:
                live.close()


# ────────────────────────────────────────────────────────────────────
# Chat completions
# ────────────────────────────────────────────────────────────────────


class TestGatewayChatCompletions:
    def test_text_content(self):
        agent = FakeAgent(text="hello back")
        live = _LiveServer(agent)
        try:
            status, _, raw = live.request(
                "POST",
                "/v1/chat/completions",
                {"messages": [{"role": "user", "content": "hi"}]},
            )
            assert status == 200
            body = json.loads(raw.decode("utf-8"))
            assert body["id"].startswith("chatcmpl-")
            assert body["object"] == "chat.completion"
            assert body["model"]
            assert len(body["choices"]) == 1
            msg = body["choices"][0]["message"]
            assert msg["role"] == "assistant"
            assert msg["content"] == "hello back"
            assert body["choices"][0]["finish_reason"] == "stop"
            assert "usage" in body
        finally:
            live.close()

    def test_vision_content(self):
        """Multi-modal content with text + image_url is extracted."""
        agent = FakeAgent(text="I see a cat")
        live = _LiveServer(agent)
        try:
            content = [
                {"type": "text", "text": "What's in this image?"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,AAAA"},
                },
            ]
            status, _, _ = live.request(
                "POST",
                "/v1/chat/completions",
                {"messages": [{"role": "user", "content": content}]},
            )
            assert status == 200
            assert agent.run_calls
            sent = agent.run_calls[0]
            assert "What's in this image?" in sent
            assert "<image>data:image/png;base64,AAAA</image>" in sent
        finally:
            live.close()

    def test_vision_only_image(self):
        """Image-only content still produces a non-empty payload."""
        agent = FakeAgent(text="image-only reply")
        live = _LiveServer(agent)
        try:
            status, _, _ = live.request(
                "POST",
                "/v1/chat/completions",
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": "data:image/png;base64,ZZZZ"},
                                }
                            ],
                        }
                    ]
                },
            )
            assert status == 200
            assert "<image>" in agent.run_calls[0]
        finally:
            live.close()

    def test_stream_sse(self):
        """stream=true returns text/event-stream chunks + [DONE]."""
        agent = FakeAgent(tokens=["Hello", " ", "world"])
        live = _LiveServer(agent)
        try:
            conn = HTTPConnection("127.0.0.1", live.port, timeout=5)
            conn.request(
                "POST",
                "/v1/chat/completions",
                body=json.dumps(
                    {
                        "messages": [{"role": "user", "content": "hi"}],
                        "stream": True,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            assert resp.status == 200
            assert resp.getheader("Content-Type", "").startswith("text/event-stream")
            raw = resp.read().decode("utf-8")
            conn.close()

            # Each SSE event is rendered as a multi-line block terminated by \n\n.
            events = [ev for ev in raw.split("\n\n") if ev.strip()]
            data_lines = [
                line[len("data: "):]
                for ev in events
                for line in ev.splitlines()
                if line.startswith("data: ")
            ]
            assert data_lines, f"expected data: lines in: {raw!r}"
            chunks = [json.loads(d) for d in data_lines if d != "[DONE]"]
            assert chunks, "expected at least one SSE chunk"
            first = chunks[0]
            assert first["object"] == "chat.completion.chunk"
            assert first["id"].startswith("chatcmpl-")
            assert first["choices"][0]["delta"]["content"] == "Hello"

            # The final sentinel must be present.
            assert raw.rstrip().endswith("data: [DONE]")
        finally:
            live.close()

    def test_stream_sse_done_event_present(self):
        """The terminator must be the very last frame."""
        agent = FakeAgent(tokens=["a", "b"])
        live = _LiveServer(agent)
        try:
            status, _, raw = live.request(
                "POST",
                "/v1/chat/completions",
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                },
            )
            text = raw.decode("utf-8")
            assert status == 200
            assert text.rstrip().endswith("data: [DONE]")
        finally:
            live.close()

    def test_tool_calls_non_stream(self):
        """When tools are provided, the LLM stream path is used and
        tool_calls are surfaced in the streamed delta."""
        tool_calls = [
            {
                "id": "call_abc",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"city":"SF"}',
                },
            }
        ]
        agent = FakeAgent(tokens=["calling"], tool_calls=tool_calls)
        live = _LiveServer(agent)
        try:
            conn = HTTPConnection("127.0.0.1", live.port, timeout=5)
            conn.request(
                "POST",
                "/v1/chat/completions",
                body=json.dumps(
                    {
                        "messages": [{"role": "user", "content": "weather?"}],
                        "stream": True,
                        "tools": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "description": "Get weather",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {"city": {"type": "string"}},
                                    },
                                },
                            }
                        ],
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            raw = resp.read().decode("utf-8")
            conn.close()

            events = [ev for ev in raw.split("\n\n") if ev.strip()]
            data_lines = [
                line[len("data: "):]
                for ev in events
                for line in ev.splitlines()
                if line.startswith("data: ")
            ]
            chunks = [json.loads(d) for d in data_lines if d != "[DONE]"]
            # Find a chunk carrying tool_calls.
            tc_chunks = [
                e
                for e in chunks
                if e["choices"][0]["delta"].get("tool_calls")
            ]
            assert tc_chunks, "expected a tool_calls chunk in the stream"
            tc = tc_chunks[0]["choices"][0]["delta"]["tool_calls"][0]
            assert tc["id"] == "call_abc"
            assert tc["type"] == "function"
            assert tc["function"]["name"] == "get_weather"
        finally:
            live.close()

    def test_no_messages_returns_400(self):
        live = _LiveServer(FakeAgent())
        try:
            status, _, raw = live.request(
                "POST", "/v1/chat/completions", {"messages": []}
            )
            assert status == 400
            body = json.loads(raw.decode("utf-8"))
            assert body["error"]["type"] == "invalid_request_error"
        finally:
            live.close()

    def test_non_user_last_message_returns_400(self):
        live = _LiveServer(FakeAgent())
        try:
            status, _, _ = live.request(
                "POST",
                "/v1/chat/completions",
                {"messages": [{"role": "assistant", "content": "hi"}]},
            )
            assert status == 400
        finally:
            live.close()

    def test_invalid_json_returns_400(self):
        live = _LiveServer(FakeAgent())
        try:
            conn = HTTPConnection("127.0.0.1", live.port, timeout=5)
            conn.request(
                "POST",
                "/v1/chat/completions",
                body=b"{not json",
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            raw = resp.read()
            conn.close()
            assert resp.status == 400
            body = json.loads(raw.decode("utf-8"))
            assert body["error"]["type"] == "invalid_request_error"
        finally:
            live.close()

    def test_health_endpoint(self):
        live = _LiveServer(FakeAgent())
        try:
            status, _, raw = live.request("GET", "/health")
            assert status == 200
            assert json.loads(raw.decode("utf-8")) == {"status": "ok"}
        finally:
            live.close()

    def test_unknown_path_returns_404(self):
        live = _LiveServer(FakeAgent())
        try:
            status, _, _ = live.request("GET", "/v1/nope")
            assert status == 404
        finally:
            live.close()


# ────────────────────────────────────────────────────────────────────
# Internal helpers
# ────────────────────────────────────────────────────────────────────


class TestInternalHelpers:
    def test_convert_tools_to_internal(self):
        out = APIServer._convert_tools_to_internal(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "echo",
                        "description": "echoes",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]
        )
        assert out == [
            {
                "name": "echo",
                "description": "echoes",
                "parameters": {"type": "object", "properties": {}},
            }
        ]

    def test_convert_tools_skips_invalid(self):
        out = APIServer._convert_tools_to_internal(
            [
                {"type": "function", "function": {}},
                "not-a-dict",
                {"name": "bare"},  # no function wrapper, but has name
            ]
        )
        # Only the bare-name tool survives (others have no name).
        assert out == [{"name": "bare", "description": "", "parameters": {"type": "object", "properties": {}}}]

    def test_extract_user_text_string(self):
        assert (
            APIServer._extract_user_text({"role": "user", "content": "hello"})
            == "hello"
        )

    def test_extract_user_text_list(self):
        text = APIServer._extract_user_text(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,XYZ"},
                    },
                ],
            }
        )
        assert "look" in text
        assert "<image>data:image/png;base64,XYZ</image>" in text

    def test_extract_user_text_empty(self):
        assert (
            APIServer._extract_user_text({"role": "user", "content": []}) is None
        )

    def test_inject_tools_into_messages(self):
        msgs = APIServer._inject_tools_into_messages(
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "fn",
                        "description": "do fn",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            user_message="please",
        )
        assert msgs[0]["role"] == "system"
        assert "fn" in msgs[0]["content"]
        assert msgs[-1] == {"role": "user", "content": "please"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
