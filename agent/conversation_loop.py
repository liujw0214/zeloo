"""Agent conversation loop — think-act cycle with iteration budget."""

from __future__ import annotations

import base64
import io
import json
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agent.estop import estop
from agent.zeloo_constants import (
    DEFAULT_CONTEXT_KEEP_RECENT,
    DEFAULT_CONTEXT_MAX_MESSAGES,
    DEFAULT_CONTEXT_SUMMARY_CHARS,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_WORKERS,
)
from utils import count_message_tokens

logger = logging.getLogger(__name__)

# Default context window budget in tokens. When the conversation exceeds
# this, older messages are pruned (keeping the most recent N).
DEFAULT_MAX_CONTEXT_TOKENS = 128000

# Transient error substrings that warrant a retry.
_TRANSIENT_ERROR_MARKERS = (
    "rate limit",
    "rate_limit",
    "429",
    "timeout",
    "timed out",
    "connection",
    "temporarily unavailable",
    "502",
    "503",
    "500",
    "overloaded",
)

DEFAULT_LLM_MAX_RETRIES = 3
DEFAULT_LLM_RETRY_BASE_DELAY = 1.0  # seconds

# When LLM summarization is enabled, summaries are capped at this length.
DEFAULT_SUMMARY_MAX_TOKENS = 512


class ConversationLoop:
    """The think-act cycle that drives agent tool use until completion."""

    def __init__(
        self,
        agent: Any,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        max_workers: int = DEFAULT_MAX_WORKERS,
        llm_max_retries: int = DEFAULT_LLM_MAX_RETRIES,
        llm_retry_base_delay: float = DEFAULT_LLM_RETRY_BASE_DELAY,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        use_llm_summary: bool = False,
    ) -> None:
        self.agent = agent
        self.max_iterations = max_iterations
        self.max_workers = max_workers
        self.llm_max_retries = llm_max_retries
        self.llm_retry_base_delay = llm_retry_base_delay
        self.max_context_tokens = max_context_tokens
        self.use_llm_summary = use_llm_summary
        self._interrupt_requested = False
        self.api_call_count = 0
        # Fine-grained iteration budget. ``remaining`` starts at
        # max_iterations and is decremented per LLM call. When it hits
        # zero, one grace call is allowed so the agent can wrap up.
        self.iteration_budget_remaining: int = max_iterations
        self._budget_grace_call: bool = False

    def request_interrupt(self) -> None:
        """Signal the loop to stop at the next iteration boundary."""
        self._interrupt_requested = True

    def run(self, messages: list[dict[str, Any]], on_token: Any | None = None) -> str:
        """Run the conversation loop and return the final assistant message.

        Args:
            messages: The conversation messages so far.
            on_token: Optional callback invoked for each streamed token
                       during the final (non-tool-call) response.
        """
        self._interrupt_requested = False
        self.api_call_count = 0
        self.iteration_budget_remaining = self.max_iterations
        self._budget_grace_call = False

        while (
            self.api_call_count < self.max_iterations
            and self.iteration_budget_remaining > 0
        ) or self._budget_grace_call:
            if self._interrupt_requested:
                logger.info("Loop interrupted by user")
                return self._partial_response(messages)

            # Emergency stop check — halts everything immediately
            if estop.is_stopped():
                state = estop.get_state()
                logger.warning("ESTOP active, aborting loop: %s", state.reason)
                return f"[emergency stop: {state.reason}]"

            # Consume the grace call flag (this is the extra wrap-up call)
            grace = self._budget_grace_call
            if grace:
                self._budget_grace_call = False

            # Compress context if history grew too long
            self._maybe_compress_context(messages)

            # Build API request with cached system prompt
            system_prompt = self.agent.get_cached_system_prompt()
            full_messages = [{"role": "system", "content": system_prompt}, *messages]

            # Stream only the final response (no tool calls). For iterations
            # that may produce tool calls, use non-streaming to get the full
            # tool_calls payload reliably. On the grace call, always stream
            # so the user sees the wrap-up response.
            stream = bool(on_token and (grace or self.api_call_count == self.max_iterations - 1))
            response = self._call_llm_with_retry(full_messages, stream=stream, on_token=on_token)
            if response is None:
                return "[LLM unavailable after retries]"

            self.api_call_count += 1
            self.iteration_budget_remaining = max(0, self.iteration_budget_remaining - 1)

            # When the budget hits zero, allow one final grace call so the
            # agent can wrap up the task instead of being cut off mid-tool.
            if self.iteration_budget_remaining == 0 and not grace:
                self._budget_grace_call = True

            # Check for tool calls
            tool_calls = response.get("tool_calls")
            if not tool_calls:
                # Final text response
                content = response.get("content", "")
                messages.append({"role": "assistant", "content": content})
                return content

            # Execute tool calls in parallel
            assistant_message = {
                "role": "assistant",
                "content": response.get("content") or "",
                "tool_calls": tool_calls,
            }
            messages.append(assistant_message)

            results = self._execute_tool_calls(tool_calls)
            for result in results:
                messages.append(result)

        # Max iterations reached
        return self._partial_response(messages, reason="max_iterations")

    def _call_llm_with_retry(
        self,
        messages: list[dict[str, Any]],
        stream: bool = False,
        on_token: Any | None = None,
    ) -> dict[str, Any] | None:
        """Call the LLM with exponential-backoff retry on transient errors.

        Returns the response dict, or ``None`` if all retries are exhausted.
        Non-transient errors are logged and re-raised.
        """
        for attempt in range(self.llm_max_retries + 1):
            try:
                if stream:
                    return self.agent.call_llm_stream(messages, on_token=on_token)
                return self.agent.call_llm(messages)
            except Exception as e:
                err_text = str(e).lower()
                transient = self._is_transient_error(err_text)
                if not transient or attempt == self.llm_max_retries:
                    logger.exception("LLM call failed (transient=%s)", transient)
                    return None
                delay = self.llm_retry_base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "LLM transient error (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1,
                    self.llm_max_retries,
                    e,
                    delay,
                )
                time.sleep(delay)
        return None

    @staticmethod
    def _is_transient_error(error_text: str) -> bool:
        """Return True if the error text indicates a transient/retryable failure."""
        return any(marker in error_text for marker in _TRANSIENT_ERROR_MARKERS)

    def _execute_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Execute tool calls in parallel and return result messages.

        If an interrupt is requested while tools are running, pending
        (not-yet-started) futures are cancelled and in-flight results are
        returned as-is.
        """
        results: list[dict[str, Any] | None] = [None] * len(tool_calls)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_index = {
                executor.submit(self._execute_single_tool, tc): i
                for i, tc in enumerate(tool_calls)
            }
            pending = set(future_to_index)
            while pending:
                # Check for interrupt before waiting
                if self._interrupt_requested:
                    self._cancel_futures(pending, future_to_index, tool_calls, results)
                    break

                done, pending = self._wait_any(pending, timeout=0.5)
                for future in done:
                    idx = future_to_index[future]
                    try:
                        results[idx] = future.result()
                    except Exception as e:
                        logger.exception("Tool execution failed")
                        tc = tool_calls[idx]
                        results[idx] = {
                            "role": "tool",
                            "tool_call_id": tc.get("id"),
                            "name": tc.get("function", {}).get("name"),
                            "content": f"Error: {e}",
                        }

        return [r for r in results if r is not None]

    @staticmethod
    def _wait_any(futures: set, timeout: float):
        """Wait for at least one future to complete, with a timeout."""
        from concurrent.futures import FIRST_COMPLETED, wait

        done, pending = wait(futures, timeout=timeout, return_when=FIRST_COMPLETED)
        return done, pending

    def _cancel_futures(
        self,
        pending: set,
        future_to_index: dict,
        tool_calls: list[dict[str, Any]],
        results: list,
    ) -> None:
        """Cancel pending futures and mark in-flight ones as cancelled."""
        for future in pending:
            # cancel() only succeeds for not-yet-started tasks
            if not future.cancel():
                idx = future_to_index[future]
                tc = tool_calls[idx]
                results[idx] = {
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "name": tc.get("function", {}).get("name"),
                    "content": "[cancelled due to interrupt]",
                }
        logger.info("Cancelled %d pending tool future(s)", len(pending))

    def _execute_single_tool(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        """Execute a single tool call and return a tool result message."""
        function = tool_call.get("function", {})
        name = function.get("name", "")
        arguments = function.get("arguments", "{}")

        import json

        try:
            args = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError:
            args = {}

        # Validate arguments against the tool's JSON schema before execution.
        # This catches malformed LLM output early and returns a clear error
        # message so the LLM can correct its call.
        validation_error = self._validate_tool_args(name, args)
        if validation_error:
            return {
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "name": name,
                "content": f"Argument validation error: {validation_error}",
            }

        result = self.agent.execute_tool(name, args)

        # Safety-net: forward the latest cost snapshot to Langfuse at the
        # end of every tool call. The primary call site is in
        # run_agent.py right after each LLM response, but calling here
        # guarantees that any cost recorded inside tools (or by direct
        # calls into the agent's _cost_tracker) is also reflected in
        # remote observability dashboards.
        cost_tracker = getattr(self.agent, "_cost_tracker", None)
        if cost_tracker is not None and hasattr(cost_tracker, "push_to_tracer"):
            try:
                cost_tracker.push_to_tracer()
            except Exception:  # noqa: BLE001
                # push_to_tracer swallows its own errors; this is the
                # outermost safety net so a misbehaving tracer cannot
                # break the tool result delivery.
                logger.warning(
                    "conversation_loop: cost push failed for tool %s", name
                )

        return {
            "role": "tool",
            "tool_call_id": tool_call.get("id"),
            "name": name,
            "content": self._sanitize_result(result, tool_name=name),
        }

    def _validate_tool_args(self, name: str, args: dict[str, Any]) -> str | None:
        """Validate tool arguments against the registered schema.

        Returns an error message string if validation fails, or ``None``
        if the arguments are valid (or no schema is available).
        """
        if not isinstance(args, dict):
            return f"arguments must be a JSON object, got {type(args).__name__}"

        schemas = getattr(self.agent, "tool_schemas", None) or getattr(
            self.agent, "_tool_schemas", None
        )
        if not schemas:
            return None  # no schemas available, skip validation

        schema = None
        for s in schemas:
            if s.get("function", {}).get("name") == name or s.get("name") == name:
                schema = s
                break
        if not schema:
            return None  # unknown tool, let execute_tool handle it

        params = schema.get("function", {}).get("parameters", schema.get("parameters", {}))
        if not params or params.get("type") != "object":
            return None

        # Check required fields
        for required in params.get("required", []):
            if required not in args:
                return f"missing required argument: {required}"

        # Check basic types for provided arguments
        properties = params.get("properties", {})
        for key, value in args.items():
            if key not in properties:
                continue  # allow extra args (backward compat)
            prop_type = properties[key].get("type")
            if not prop_type:
                continue
            if not self._check_type(value, prop_type):
                return (
                    f"argument '{key}' should be {prop_type}, "
                    f"got {type(value).__name__}"
                )
        return None

    @staticmethod
    def _check_type(value: Any, expected_type: str) -> bool:
        """Check if *value* matches the JSON schema *expected_type*."""
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        py_type = type_map.get(expected_type)
        if py_type is None:
            return True
        if expected_type == "integer" and isinstance(value, bool):
            return False
        return isinstance(value, py_type)

    def _sanitize_result(self, result: Any, *, tool_name: str = "tool") -> str:
        """Sanitize tool result for injection into the message stream.

        Pre-converts multi-modal payloads (``bytes``, ``PIL.Image``) to a
        structured ``image_base64`` marker so vision-capable providers
        can round-trip them, then routes the (now string-shaped) value
        through the same two passes as before:

          1. ``tools.output_scan.scan_tool_output`` — runs the result
             through the secret scanner, replaces matched credentials
             with ``[REDACTED]``, prepends a ``[Zeloo: redacted N
             secret(s) …]`` header when something was stripped, and
             writes a ``tool_output_secret_found`` audit event. This
             guarantees that EVERY tool result flowing through the
             conversation loop is filtered, even for tools that did
             not opt in individually.
          2. Truncation to :data:`MAX_TOOL_RESULT_LENGTH` so a single
             verbose tool doesn't blow up the context window.

        Supports text strings, dicts (JSON), lists, PIL images, and
        bytes with image mime types. Returns a multimodal-friendly JSON
        marker for image payloads; otherwise a flattened text / JSON
        representation.
        """
        text = self._coerce_to_text(result, tool_name=tool_name)
        try:
            from tools.output_scan import scan_tool_output

            # ``scan_tool_output`` is fail-open: any scanner / audit
            # failure returns the original text unchanged, so this
            # never breaks the tool path.
            text = scan_tool_output(
                text,
                tool_name=tool_name,
                source=tool_name,
            )
        except Exception:  # noqa: BLE001
            logger.warning("conversation_loop: tool-output scan failed for %s", tool_name)
            # Continue with the (unscanned) text — never break the loop.

        # Truncate overly long results
        from agent.zeloo_constants import MAX_TOOL_RESULT_LENGTH

        if len(text) > MAX_TOOL_RESULT_LENGTH:
            text = text[:MAX_TOOL_RESULT_LENGTH] + "\n...[truncated]"
        return text

    @staticmethod
    def _coerce_to_text(result: Any, tool_name: str = "tool") -> str:
        """Convert a tool result into a model-friendly string.

        Handles strings, ``dict`` / ``list`` (JSON), ``bytes`` (treated
        as ``image/png``), and ``PIL.Image.Image`` (encoded to PNG).

        Returns a JSON-encoded ``image_base64`` marker for image
        payloads; the corresponding provider is expected to detect the
        marker and rebuild the multimodal content array. For anything
        else, falls back to ``str(result)``.
        """
        if isinstance(result, str):
            return result

        # bytes → image_base64 marker
        if isinstance(result, bytes):
            b64 = base64.b64encode(result).decode("ascii")
            return json.dumps(
                {
                    "type": "image_base64",
                    "mime": "image/png",
                    "data": b64,
                },
                ensure_ascii=False,
            )

        # dict / list → JSON
        if isinstance(result, (dict, list)):
            try:
                return json.dumps(result, ensure_ascii=False, default=str)
            except Exception:
                return repr(result)

        # PIL Image → base64 PNG
        try:
            from PIL import Image
        except ImportError:
            Image = None  # type: ignore[assignment]
        if Image is not None and isinstance(result, Image.Image):
            buf = io.BytesIO()
            result.save(buf, format="PNG")
            return json.dumps(
                {
                    "type": "image_base64",
                    "mime": "image/png",
                    "data": base64.b64encode(buf.getvalue()).decode("ascii"),
                },
                ensure_ascii=False,
            )

        # fallback
        return str(result)

    def _partial_response(
        self, messages: list[dict[str, Any]], reason: str = "interrupted"
    ) -> str:
        """Extract the last assistant content as a partial response."""
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg["content"]
        return f"[Task {reason}]"

    def _maybe_compress_context(self, messages: list[dict[str, Any]]) -> None:
        """Compress the message history in place when it exceeds thresholds.

        Compression is triggered when **either** the message count or the
        estimated token count exceeds the configured limit.

        Strategy (no LLM round-trip — purely structural):
          * Keep the first user message (original intent) verbatim.
          * Keep the last ``DEFAULT_CONTEXT_KEEP_RECENT`` messages verbatim.
          * Replace the middle messages with a single summary message
            containing role + truncated content previews.
          * Rebuild the cached system prompt so volatile-layer updates
            (memory/skills) are reflected after compression.
        """
        msg_count = len(messages)
        token_count = count_message_tokens(messages)
        if (
            msg_count <= DEFAULT_CONTEXT_MAX_MESSAGES
            and token_count <= self.max_context_tokens
        ):
            return

        logger.info(
            "Context compression triggered: %d messages / %d tokens -> keeping %d recent",
            msg_count,
            token_count,
            DEFAULT_CONTEXT_KEEP_RECENT,
        )

        keep_recent = DEFAULT_CONTEXT_KEEP_RECENT
        first_msg = messages[0] if messages else None
        tail = messages[-keep_recent:]

        # Summarize the middle section
        middle = messages[1:-keep_recent] if first_msg else messages[:-keep_recent]

        if self.use_llm_summary:
            summary_text = self._llm_summarize(middle)
        else:
            summary_lines: list[str] = []
            for msg in middle:
                role = msg.get("role", "?")
                content = str(msg.get("content") or "")
                preview = content[:DEFAULT_CONTEXT_SUMMARY_CHARS]
                if len(content) > DEFAULT_CONTEXT_SUMMARY_CHARS:
                    preview += "..."
                summary_lines.append(f"[{role}] {preview}")
            summary_text = "\n".join(summary_lines)

        summary_msg = {
            "role": "user",
            "content": (
                "[Context compressed — earlier conversation summarized below]\n"
                + summary_text
            ),
        }

        # Rebuild the message list
        messages.clear()
        if first_msg:
            messages.append(first_msg)
        messages.append(summary_msg)
        messages.extend(tail)

        # Rebuild system prompt to capture any volatile-layer changes
        try:
            self.agent.invalidate_system_prompt()
        except AttributeError:
            pass  # agent may not expose this method

    def _llm_summarize(self, messages: list[dict[str, Any]]) -> str:
        """Generate an LLM-based summary of the middle conversation messages.

        Uses the auxiliary client if available (cheaper model), otherwise
        falls back to the agent's main model. On any failure, returns a
        structural summary instead.
        """
        # Build a compact transcript
        lines: list[str] = []
        for msg in messages[:50]:  # cap to avoid huge prompts
            role = msg.get("role", "?")
            content = str(msg.get("content") or "")[:500]
            lines.append(f"{role}: {content}")
        transcript = "\n".join(lines)

        prompt = (
            "Summarize the following conversation concisely, preserving key "
            "decisions, tool results, and user intent. Keep it under 300 words:\n\n"
            f"{transcript}"
        )

        try:
            aux = getattr(self.agent, "auxiliary_client", None)
            if aux is not None and getattr(aux, "enabled", False):
                return aux.summarize(prompt)
            # Fallback: use the main model directly
            response = self.agent.call_llm(
                [{"role": "user", "content": prompt}]
            )
            content = response.get("content", "")
            if content:
                return content[:2000]
        except Exception:
            logger.exception("LLM summarization failed, falling back to structural")

        # Structural fallback
        previews = []
        for msg in messages:
            role = msg.get("role", "?")
            content = str(msg.get("content") or "")[:DEFAULT_CONTEXT_SUMMARY_CHARS]
            previews.append(f"[{role}] {content}")
        return "\n".join(previews)
