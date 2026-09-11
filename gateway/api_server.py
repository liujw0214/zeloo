"""OpenAI-compatible HTTP API server.

Provides endpoints for chat completions, model listing, skills listing,
and health checks. Uses only the Python standard library so it runs
without extra dependencies.

Endpoints:
  GET  /health               — health check
  GET  /v1/models            — available models
  GET  /v1/skills            — available skills
  POST /v1/chat/completions  — chat completions (supports streaming, tools, vision)
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from security import RateLimiter, sanitize_input, validate_output

logger = logging.getLogger(__name__)

DEFAULT_PORT = 9113


def _get_provider_names() -> list[str]:
    """Return the list of registered provider names from the agent registry.

    Wrapped in a thin function so it can be patched in tests without
    importing the registry module at import time.
    """
    try:
        from agent.providers.registry import list_providers as _list

        return list(_list())
    except Exception:
        return []


def _build_completion_id() -> str:
    """Return a fresh OpenAI-style completion id (``chatcmpl-xxx``)."""
    return f"chatcmpl-{uuid.uuid4().hex[:12]}"


def _now_ts() -> int:
    """Return the current epoch timestamp (seconds)."""
    return int(time.time())


class APIServer:
    """Lightweight OpenAI-compatible API server."""

    def __init__(
        self,
        agent_factory: Callable[..., Any],
        host: str = "0.0.0.0",
        port: int = DEFAULT_PORT,
        model_name: str = "Zeloo",
        rate_limit_capacity: int = 60,
        rate_limit_rate: float = 1.0,
        auth_tokens: list[str] | None = None,
        mcp_reload_callback: Callable[[], int] | None = None,
    ) -> None:
        self._agent_factory = agent_factory
        self._host = host
        self._port = port
        self._model_name = model_name
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._rate_limiter = RateLimiter(
            capacity=rate_limit_capacity, rate=rate_limit_rate
        )
        # Bearer token allow-list. None or empty = auth disabled.
        self._auth_tokens: set[str] = set(auth_tokens or [])
        # Optional callback invoked by POST /v1/mcp/reload
        self._mcp_reload_callback = mcp_reload_callback

    def start(self) -> None:
        """Start the API server in a background thread."""
        server = ThreadingHTTPServer((self._host, self._port), self._make_handler())
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
            name=f"api-server-{self._port}",
        )
        self._thread.start()
        logger.info("API server listening on %s:%d", self._host, self._port)

    def stop(self) -> None:
        """Stop the API server."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            logger.info("API server stopped")

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                logger.debug("API %s - %s", self.address_string(), format % args)

            def do_GET(self) -> None:  # noqa: N802
                server._handle_get(self)

            def do_POST(self) -> None:  # noqa: N802
                server._handle_post(self)

        return _Handler

    # ── Auth ────────────────────────────────────────────────────────

    def _check_auth(self, handler: BaseHTTPRequestHandler) -> bool:
        """Return True if the request carries a valid Bearer token.

        When no tokens are configured, auth is disabled and all requests
        are allowed. The /health endpoint is always exempt.
        """
        if not self._auth_tokens:
            return True
        auth_header = handler.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            if token in self._auth_tokens:
                return True
        self._send_json(
            handler,
            401,
            {"error": {"message": "Unauthorized", "type": "authentication_error"}},
        )
        return False

    # ── GET handlers ────────────────────────────────────────────────

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        path = handler.path.split("?")[0]

        if path == "/health":
            self._send_json(handler, 200, {"status": "ok"})
            return

        if not self._check_auth(handler):
            return

        if path == "/v1/models":
            self._handle_list_models(handler)
        elif path == "/v1/skills":
            skills = self._list_skills()
            self._send_json(handler, 200, {"object": "list", "data": skills})
        else:
            self._send_json(handler, 404, {"error": {"message": "Not found", "type": "not_found"}})

    def _handle_list_models(self, handler: BaseHTTPRequestHandler) -> None:
        """H4: dynamic /v1/models listing from the agent provider registry.

        Falls back to a single ``self._model_name`` entry when no providers
        are registered (so an empty dev environment still returns a sane
        OpenAI-shaped payload).
        """
        providers = _get_provider_names()
        created = _now_ts()
        if providers:
            data = [
                {
                    "id": provider,
                    "object": "model",
                    "created": created,
                    "owned_by": provider,
                }
                for provider in providers
            ]
        else:
            data = [
                {
                    "id": self._model_name,
                    "object": "model",
                    "created": created,
                    "owned_by": "Zeloo",
                }
            ]
        self._send_json(handler, 200, {"object": "list", "data": data})

    def _list_skills(self) -> list[dict[str, Any]]:
        """List available skills from the skills directory."""
        try:
            from agent.skill_utils import (
                extract_skill_description,
                extract_skill_name,
                iter_skill_index_files,
                parse_frontmatter,
            )

            skills: list[dict[str, Any]] = []
            for skill_file in iter_skill_index_files():
                try:
                    content = skill_file.read_text(encoding="utf-8")
                    fm = parse_frontmatter(content)
                    skills.append(
                        {
                            "name": extract_skill_name(fm, skill_file),
                            "description": extract_skill_description(fm),
                        }
                    )
                except Exception:
                    logger.exception("Failed to read skill %s", skill_file)
            return skills
        except Exception:
            return []

    # ── POST handlers ───────────────────────────────────────────────

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        path = handler.path.split("?")[0]

        # MCP hot-reload endpoint (auth required)
        if path == "/v1/mcp/reload":
            if not self._check_auth(handler):
                return
            if self._mcp_reload_callback is None:
                self._send_json(
                    handler,
                    503,
                    {"error": {"message": "MCP reload not available", "type": "unavailable"}},
                )
                return
            try:
                count = self._mcp_reload_callback()
                self._send_json(handler, 200, {"status": "ok", "registered_tools": count})
            except Exception as exc:
                self._send_json(
                    handler,
                    500,
                    {"error": {"message": str(exc), "type": "internal_error"}},
                )
            return

        if path != "/v1/chat/completions":
            self._send_json(handler, 404, {"error": {"message": "Not found", "type": "not_found"}})
            return

        if not self._check_auth(handler):
            return

        # Rate limit by client IP
        client_ip = handler.client_address[0]
        if not self._rate_limiter.allow(client_ip):
            self._send_json(
                handler,
                429,
                {"error": {"message": "Rate limit exceeded", "type": "rate_limit_error"}},
            )
            return

        try:
            length = int(handler.headers.get("Content-Length", 0))
            raw = handler.rfile.read(length)
            body = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, ValueError):
            self._send_json(
                handler,
                400,
                {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}},
            )
            return

        messages = body.get("messages", [])
        if not messages or messages[-1].get("role") != "user":
            self._send_json(
                handler,
                400,
                {"error": {
                    "message": "Last message must be from user",
                    "type": "invalid_request_error",
                }},
            )
            return

        # H1: detect streaming requests
        stream = bool(body.get("stream", False))
        # H2: detect tool definitions
        tools = body.get("tools") or []

        # H3: vision / multi-modal content extraction
        user_message = self._extract_user_text(messages[-1])
        if user_message is None:
            self._send_json(
                handler,
                400,
                {"error": {
                    "message": "Last user message has no text/image content",
                    "type": "invalid_request_error",
                }},
            )
            return

        # Sanitize user input (strip control chars, truncate, scan threats)
        sanitized = sanitize_input(user_message)
        if sanitized.threats:
            logger.warning(
                "Threats detected in input from %s: %s", client_ip, sanitized.threats
            )

        try:
            agent = self._agent_factory(platform="api")
        except Exception:
            logger.exception("Failed to build agent for API request")
            self._send_json(
                handler,
                500,
                {"error": {"message": "Failed to build agent", "type": "server_error"}},
            )
            return

        completion_id = _build_completion_id()
        created = _now_ts()
        model = body.get("model") or self._model_name

        # H1: streaming response
        if stream:
            self._handle_stream(
                handler,
                agent=agent,
                user_message=sanitized.text,
                tools=tools,
                completion_id=completion_id,
                created=created,
                model=model,
            )
            return

        # Non-streaming: H2 tool support via run_conversation fallback
        try:
            response_text = agent.run_conversation(sanitized.text)
            response_text = validate_output(response_text)
        except Exception:
            logger.exception("API chat completion failed")
            self._send_json(
                handler,
                500,
                {"error": {"message": "Internal server error", "type": "server_error"}},
            )
            return

        result = self._build_completion_payload(
            completion_id=completion_id,
            created=created,
            model=model,
            content=response_text,
            tool_calls=None,
        )
        self._send_json(handler, 200, result)

    # ── H1: SSE streaming ───────────────────────────────────────────

    def _handle_stream(
        self,
        handler: BaseHTTPRequestHandler,
        *,
        agent: Any,
        user_message: str,
        tools: list[dict[str, Any]],
        completion_id: str,
        created: int,
        model: str,
    ) -> None:
        """Stream an OpenAI-shaped completion via SSE."""
        # Lazy import — the SSEStream class lives in the same package.
        from gateway.sse import SSEStream  # noqa: WPS433

        def _on_token(token: str) -> None:
            # Build the SSE chunk for each token delta.
            delta = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": token},
                        "finish_reason": None,
                    }
                ],
            }
            event = SSEStream.format_event_static(
                data=json.dumps(delta, ensure_ascii=False),
                event="message",
            )
            try:
                handler.wfile.write(event.encode("utf-8"))
                handler.wfile.flush()
            except Exception:
                logger.debug("Client disconnected during stream")

        try:
            # Switch response protocol to SSE BEFORE we start writing.
            handler.send_response(200)
            handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
            handler.send_header("Cache-Control", "no-cache")
            # Close after the stream so HTTPConnection.read() returns.
            handler.send_header("Connection", "close")
            handler.send_header("X-Accel-Buffering", "no")
            handler.end_headers()

            if tools:
                # Tool definitions are present — use the full LLM path so
                # tool_calls can be emitted alongside the streamed text.
                messages_payload = self._inject_tools_into_messages(
                    tools=tools, user_message=user_message
                )
                result = agent.call_llm_stream(messages_payload, on_token=_on_token)
                if result.get("tool_calls"):
                    self._stream_tool_calls(
                        handler,
                        completion_id=completion_id,
                        created=created,
                        model=model,
                        tool_calls=result["tool_calls"],
                    )
            else:
                # Plain text path: call_llm_stream accepts [str] messages
                agent.call_llm_stream(
                    [{"role": "user", "content": user_message}],
                    on_token=_on_token,
                )

            # Emit the final stop chunk.
            stop = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            handler.wfile.write(
                SSEStream.format_event_static(
                    data=json.dumps(stop, ensure_ascii=False),
                    event="message",
                ).encode("utf-8")
            )
            # Per OpenAI streaming spec, end the stream with a [DONE] sentinel.
            handler.wfile.write(b"data: [DONE]\n\n")
            handler.wfile.flush()
        except Exception:
            logger.exception("SSE stream failed")
            try:
                handler.wfile.write(b"data: [DONE]\n\n")
                handler.wfile.flush()
            except Exception:
                pass

    @staticmethod
    def _stream_tool_calls(
        handler: BaseHTTPRequestHandler,
        *,
        completion_id: str,
        created: int,
        model: str,
        tool_calls: list[dict[str, Any]],
    ) -> None:
        """Emit tool_calls as a single trailing SSE chunk.

        OpenAI's protocol does not stream tool_calls in a usable chunked
        fashion for our downstream code, so we send the full set as one
        delta after the content stream has finished.
        """
        from gateway.sse import SSEStream  # noqa: WPS433

        delta = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": tool_calls},
                    "finish_reason": None,
                }
            ],
        }
        handler.wfile.write(
            SSEStream.format_event_static(
                data=json.dumps(delta, ensure_ascii=False),
                event="message",
            ).encode("utf-8")
        )

    # ── H2: tool/function calling ───────────────────────────────────

    @staticmethod
    def _convert_tools_to_internal(
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert OpenAI-style tools into Zeloo internal tool schemas.

        OpenAI shape::

            {"type": "function", "function": {"name": "...", "description": "...",
             "parameters": {...JSON Schema...}}}

        Zeloo internal shape (used by the provider router)::

            {"name": "...", "description": "...", "parameters": {...}}
        """
        internal: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function") or {}
            name = function.get("name") or tool.get("name")
            if not name:
                continue
            internal.append(
                {
                    "name": name,
                    "description": function.get("description", ""),
                    "parameters": function.get(
                        "parameters", {"type": "object", "properties": {}}
                    ),
                }
            )
        return internal

    @staticmethod
    def _inject_tools_into_messages(
        *, tools: list[dict[str, Any]], user_message: str
    ) -> list[dict[str, Any]]:
        """Build a messages payload that includes the tool catalog in the
        system prompt.

        The provider router does not accept a separate ``tools`` argument
        on every code path, so we embed the tool descriptions as a system
        message prefix. This keeps the change opt-in and backwards
        compatible.
        """
        lines = ["You have access to the following tools:"]
        for tool in tools:
            function = tool.get("function") or {}
            name = function.get("name") or tool.get("name", "")
            desc = function.get("description", "")
            params = function.get("parameters", {})
            lines.append(
                f"- {name}: {desc} (parameters: {json.dumps(params, ensure_ascii=False)})"
            )
        lines.append(
            "If you decide to call a tool, respond with a JSON object of the form "
            '{"tool_calls": [{"id": "call_xxx", "type": "function", '
            '"function": {"name": "...", "arguments": "..."}}]}.'
        )
        system_msg = {"role": "system", "content": "\n".join(lines)}
        return [system_msg, {"role": "user", "content": user_message}]

    # ── H3: vision / multi-modal content ────────────────────────────

    @staticmethod
    def _extract_user_text(message: dict[str, Any]) -> str | None:
        """Extract user input from the last message.

        * If ``content`` is a string, return it as-is.
        * If ``content`` is a list of parts, return the concatenation of
          any ``type == "text"`` parts and a ``<image>`` placeholder for
          each ``type == "image_url"`` part.
        * Returns ``None`` when nothing usable is found.
        """
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                ptype = part.get("type")
                if ptype == "text":
                    text = part.get("text", "")
                    if text:
                        chunks.append(str(text))
                elif ptype == "image_url":
                    image = part.get("image_url") or {}
                    url = image.get("url", "")
                    if url:
                        chunks.append(f"<image>{url}</image>")
                elif ptype == "image":
                    # Some clients send base64 directly under "image".
                    data = part.get("data") or part.get("image", "")
                    if data:
                        chunks.append(f"<image>{data}</image>")
            return "\n".join(chunks) if chunks else None
        return None

    # ── Payload builders ────────────────────────────────────────────

    def _build_completion_payload(
        self,
        *,
        completion_id: str,
        created: int,
        model: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """Build an OpenAI-style chat.completion payload."""
        message: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _send_json(handler: BaseHTTPRequestHandler, status: int, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
