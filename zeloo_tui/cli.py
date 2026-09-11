"""``zeloo-tui`` / ``zeloo tui --demo`` entry point + synthetic emitter.

The demo emitter is used when no real LLM key is configured: it pushes
a believable event stream onto the global ``CallbackRegistry`` so the
UI can be exercised end-to-end.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from tui_gateway.agent_callbacks import (
    AgentEventType,
    emit_cancelled,
    emit_error,
    emit_finish,
    emit_start,
    emit_think,
    emit_tool_call,
    emit_tool_result,
)

logger = logging.getLogger(__name__)

_DEMO_STATE: dict[str, object] = {"thread": None, "stop": False}


def start_demo_emitter() -> threading.Thread:
    """Spawn a daemon thread that emits a synthetic event stream.

    The emitter is idempotent: calling it twice is a no-op.
    """
    existing = _DEMO_STATE.get("thread")
    if isinstance(existing, threading.Thread) and existing.is_alive():
        return existing

    stop_flag = {"value": False}
    _DEMO_STATE["stop"] = stop_flag

    def _run() -> None:
        session_id = uuid.uuid4().hex[:12]
        logger.info("demo emitter: session=%s", session_id)
        try:
            emit_start(session_id, demo=True)
            for iteration in range(1, 4):
                if stop_flag["value"]:
                    return
                emit_think(session_id, iteration=iteration)
                time.sleep(0.4)
                emit_tool_call(
                    session_id,
                    name="web_search",
                    args={"query": "Zeloo agent runtime"},
                )
                time.sleep(0.3)
                emit_tool_result(
                    session_id,
                    name="web_search",
                    result="42 hits",
                )
                time.sleep(0.2)
            emit_finish(session_id, tokens=123)
        except Exception as exc:  # noqa: BLE001
            emit_error(session_id, exc)

    thread = threading.Thread(target=_run, name="zeloo-tui-demo", daemon=True)
    _DEMO_STATE["thread"] = thread
    thread.start()
    return thread


# Backwards-compat alias — older docstrings reference this private name.
def _start_demo_emitter() -> threading.Thread:
    return start_demo_emitter()


def stop_demo_emitter() -> None:
    """Signal the demo emitter thread to exit (best-effort)."""
    stop_flag = _DEMO_STATE.get("stop")
    if isinstance(stop_flag, dict):
        stop_flag["value"] = True
    thread = _DEMO_STATE.get("thread")
    if isinstance(thread, threading.Thread):
        thread.join(timeout=1.0)


# Re-export so tests / external code can introspect demo helpers.
__all__ = [
    "start_demo_emitter",
    "stop_demo_emitter",
    "_start_demo_emitter",
    "AgentEventType",
]