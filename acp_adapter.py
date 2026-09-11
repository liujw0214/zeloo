"""ACP Adapter — bridge Zeloo to IDEs via the Agent Client Protocol.

ACP (Agent Client Protocol) is a protocol for integrating AI agents
into IDEs (VS Code, Cursor, etc.). This adapter allows Zeloo to be
controlled from within an IDE, receiving messages and returning results.

This is a skeleton implementation supporting the core ACP message types:
- initialize / initialized
- session/new
- message (user -> agent)
- message/update (agent -> client, streaming)
- message/end (agent -> client, final)
- session/end

The adapter runs a stdio-based JSON-RPC server and delegates to
:class:`AIAgent` for actual conversation handling.

Usage::

    from acp_adapter import ACPAdapter
    adapter = ACPAdapter()
    adapter.run_stdio()
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from typing import Any

logger = logging.getLogger(__name__)

ACP_PROTOCOL_VERSION = "1.0.0"


class ACPAdapter:
    """ACP protocol adapter for IDE integration.

    Bridges IDE clients to Zeloo's AIAgent via stdio JSON-RPC.
    Manages sessions and streams agent responses back to the client.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Any] = {}
        self._initialized = False
        self._agent: Any = None

    def _get_agent(self) -> Any:
        """Lazily initialize the AIAgent."""
        if self._agent is None:
            from run_agent import AIAgent

            self._agent = AIAgent()
        return self._agent

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------
    def _create_session(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new conversation session."""
        session_id = str(uuid.uuid4())
        metadata = params.get("metadata", {})
        self._sessions[session_id] = {
            "id": session_id,
            "metadata": metadata,
            "messages": [],
            "created_at": __import__("time").time(),
        }
        return {"sessionId": session_id}

    def _end_session(self, session_id: str) -> None:
        """End and clean up a session."""
        self._sessions.pop(session_id, None)

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------
    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Handle an incoming ACP message. Returns response or None."""
        msg_type = message.get("type", "")
        msg_id = message.get("id")

        if msg_type == "initialize":
            return self._handle_initialize(message)
        if msg_type == "initialized":
            self._initialized = True
            return None
        if msg_type == "session/new":
            result = self._create_session(message.get("params", {}))
            return {"type": "session/new/response", "id": msg_id, **result}
        if msg_type == "session/end":
            session_id = message.get("params", {}).get("sessionId", "")
            self._end_session(session_id)
            return None
        if msg_type == "message":
            return self._handle_user_message(message)

        return None

    def _handle_initialize(self, message: dict[str, Any]) -> dict[str, Any]:
        """Handle the initialize handshake."""
        return {
            "type": "initialize/response",
            "id": message.get("id"),
            "protocolVersion": ACP_PROTOCOL_VERSION,
            "capabilities": {
                "streaming": True,
                "tools": True,
            },
            "serverInfo": {"name": "Zeloo", "version": "0.1.0"},
        }

    def _handle_user_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Handle a user message and produce an agent response.

        In a full implementation, this would stream tokens back via
        message/update notifications. For now, it returns the complete
        response in a single message/end.
        """
        params = message.get("params", {})
        session_id = params.get("sessionId", "")
        content = params.get("content", "")

        if session_id not in self._sessions:
            return {
                "type": "message/end",
                "id": message.get("id"),
                "error": f"Unknown session: {session_id}",
            }

        session = self._sessions[session_id]
        session["messages"].append({"role": "user", "content": content})

        try:
            agent = self._get_agent()
            response = agent.run_conversation(content)
            session["messages"].append(
                {"role": "assistant", "content": response}
            )
            return {
                "type": "message/end",
                "id": message.get("id"),
                "content": response,
            }
        except Exception as e:
            logger.exception("Agent conversation failed")
            return {
                "type": "message/end",
                "id": message.get("id"),
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # Stdio transport
    # ------------------------------------------------------------------
    def run_stdio(self) -> None:
        """Run the ACP adapter reading JSON messages from stdin."""
        logger.info("Zeloo ACP adapter starting (stdio transport)")

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON: %s", line[:100])
                continue

            response = self.handle_message(message)
            if response is not None:
                print(json.dumps(response), flush=True)


def main() -> None:
    """Entry point for ``python -m acp_adapter``."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    adapter = ACPAdapter()
    adapter.run_stdio()


if __name__ == "__main__":
    main()
