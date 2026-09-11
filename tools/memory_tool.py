"""Memory and user-profile tools."""

from __future__ import annotations

from tools.base import tool


@tool(name="memory", description="Read or write persistent memory", toolset="memory")
def memory(action: str = "read", target: str = "memory", content: str = "") -> str:
    """Manage persistent memory across sessions.

    Args:
        action: "read", "write", or "append".
        target: "memory" (MEMORY.md) or "user" (USER.md).
        content: Content to write/append (for write/append actions).
    """
    # This tool needs access to the agent's memory store.
    # In production, the agent injects itself into the tool context.
    from run_agent import _current_agent

    agent = _current_agent.get()
    if agent is None or agent._memory_store is None:
        return "Error: Memory store not available"

    store = agent._memory_store
    if action == "read":
        return store.read(target)
    elif action == "write":
        store.write(target, content)
        return "Memory written."
    elif action == "append":
        store.append(target, content)
        return "Memory appended."
    else:
        return f"Error: Unknown action '{action}'"


@tool(name="session_search", description="Search past conversation history", toolset="memory")
def session_search(query: str, limit: int = 10) -> str:
    """Search through past conversation messages.

    Args:
        query: Search query.
        limit: Maximum number of results.
    """
    from run_agent import _current_agent

    agent = _current_agent.get()
    if agent is None or agent._session_db is None:
        return "Error: Session database not available"

    results = agent._session_db.search_messages(agent.session_id, query, limit)
    if not results:
        return "(no results)"
    lines = []
    for row in results:
        lines.append(f"[{row['role']}] {row['content'][:200]}")
    return "\n---\n".join(lines)
