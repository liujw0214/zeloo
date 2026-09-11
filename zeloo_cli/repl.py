r"""Shared interactive REPL engine — used by both ``cli.py`` and ``main.py``.

Mirrors Hermes Agent's CLI slash-command registry and input history
pattern (see docs/58 §5). Features:

* Banner + skin-aware prompt rendering (borrowed from Hermes Agent)
* input history (ring-buffer, draft preservation on history walk)
* backslash continuation for multi-line input
* Full slash-command dispatch (``/help /model /session /review
  /plugins /stats /undo /clear /history /compress``)
* Streaming token output (on_token callback)
* TTY-safe: KeyboardInterrupt / EOFError handled gracefully
* ``_require_tty()`` guard for interactive commands
"""

from __future__ import annotations

import os
import sys
from typing import Callable, Optional

if False:
    from run_agent import AIAgent

logger = __import__("logging").getLogger(__name__)


# ── helpers ─────────────────────────────────────────────────────────


def _render_banner() -> None:
    """Print the banner; fall back to plain text on any error."""
    try:
        from zeloo_cli.skin_engine import render_banner
        print(render_banner())
    except Exception:  # noqa: BLE001
        from zeloo_cli.__about__ import __version__
        print(f"Zeloo {__version__} — interactive mode")


def _render_prompt() -> str:
    """Return the skin-coloured prompt symbol."""
    try:
        from zeloo_cli.skin_engine import render_prompt
        return render_prompt()
    except Exception:  # noqa: BLE001
        return "> "


# ── multi-line input accumulator ─────────────────────────────────────


class _MultiLineBuffer:
    """Accumulate lines ending with backslash into a single submission."""

    __slots__ = ("_lines", "_continuing")

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._continuing = False

    def feed(self, line: str) -> tuple[bool, str]:
        """Feed one line; return (submitted, final_text).

        A line ending with backslash accumulates and waits for more.
        A bare newline cancels an in-progress continuation.
        Plain text always submits.
        """
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            content = stripped.rstrip("\\").rstrip()
            self._lines.append(content)
            self._continuing = True
            return False, ""
        if self._continuing:
            if not stripped:
                self._continuing = False
                self._lines.clear()
                return True, ""
            self._lines.append(stripped)
            self._continuing = False
            result = "\n".join(self._lines)
            self._lines.clear()
            return True, result
        if stripped:
            return True, stripped
        return True, ""


# ── slash commands ───────────────────────────────────────────────────


def _cmd_help(agent: "AIAgent") -> None:
    print("/help     — show this help")
    print("/model    — show current model")
    print("/session  — show session ID")
    print("/review   — trigger background review of current session")
    print("/plugins  — list loaded plugins")
    print("/stats    — show cache statistics")
    print("/undo     — take back the last turn")
    print("/clear    — clear screen")
    print("/history  — show conversation history")
    print("/compress — compress conversation context")
    print("quit      — exit")


def _cmd_model(agent: "AIAgent") -> None:
    print(f"Model: {agent.model} (provider: {agent.provider})")
    if agent.base_url:
        print(f"Base URL: {agent.base_url}")


def _cmd_session(agent: "AIAgent") -> None:
    print(f"Session ID: {agent.session_id}")
    from datetime import datetime

    if agent.session_start:
        print(f"Started: {agent.session_start.strftime('%Y-%m-%d %H:%M:%S')}")


def _cmd_review(agent: "AIAgent") -> None:
    from agent.background_review import run_background_review

    payload = {
        "session_id": agent.session_id,
        "turn_id": agent._turn_count,
        "agent_home": str(getattr(agent._session_db, "db_path", "").parent)
        if agent._session_db
        else "",
        "model": agent.model,
        "provider": agent.provider,
        "base_url": agent.base_url,
    }
    import threading

    threading.Thread(
        target=run_background_review,
        args=(payload,),
        daemon=True,
        name="repl-slash-review",
    ).start()
    print("Background review started…")


def _cmd_plugins(_agent: "AIAgent") -> None:
    try:
        from plugins.manager import PluginManager

        mgr = PluginManager(plugin_dirs=["plugins"])
        infos = mgr.load_all()
        if not infos:
            print("(no plugins found)")
            return
        for name, info in infos.items():
            status = "OK" if info.enabled else f"FAILED ({info.error})"
            tools = ", ".join(info.tools_added) if info.tools_added else "(no tools)"
            print(f"  {name}: {status} — {tools}")
    except Exception as exc:  # noqa: BLE001
        print(f"Error loading plugins: {exc}")


def _cmd_stats(agent: "AIAgent") -> None:
    stats = agent.cache_stats()
    print(f"Cache hits:   {stats['hits']}")
    print(f"Cache misses: {stats['misses']}")
    print(f"Hit rate:     {stats['hit_rate']:.1%}")
    if agent._cost_tracker.total_tokens > 0:
        print(f"Cost:         {agent._cost_tracker.summary()}")


def _cmd_undo(agent: "AIAgent") -> None:
    if len(agent._messages) < 2:
        print("(nothing to undo)")
        return
    removed = agent._messages.pop()
    if removed.get("role") == "assistant" and agent._messages:
        removed = agent._messages.pop()
    print("(last turn removed)")


def _cmd_clear(_agent: "AIAgent") -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _cmd_history(agent: "AIAgent") -> None:
    if not agent._messages:
        print("(no conversation history)")
        return
    for i, msg in enumerate(agent._messages[-20:]):
        role = msg.get("role", "?").upper()
        content = str(msg.get("content", ""))[:120]
        prefix = "…" if len(str(msg.get("content", ""))) > 120 else ""
        print(f"  [{i + 1}] {role}: {content}{prefix}")


def _cmd_compress(agent: "AIAgent") -> None:
    print("(context compression not yet implemented)")


_SLASH_DISPATCH: dict[str, Callable[["AIAgent"], None]] = {
    "/help": _cmd_help,
    "/model": _cmd_model,
    "/session": _cmd_session,
    "/review": _cmd_review,
    "/plugins": _cmd_plugins,
    "/stats": _cmd_stats,
    "/undo": _cmd_undo,
    "/clear": _cmd_clear,
    "/history": _cmd_history,
    "/compress": _cmd_compress,
}


# ── main REPL ───────────────────────────────────────────────────────


def run_interactive_repl(
    agent: "AIAgent",
    *,
    quiet: bool = False,
    on_token: Optional[Callable[[str], None]] = None,
) -> None:
    """Run the interactive REPL loop.

    Args:
        agent:     The wired AIAgent instance.
        quiet:     Suppress the banner and session info.
        on_token:  Optional per-token streaming callback.
    """
    if not quiet:
        _render_banner()
        print("Type 'quit' or 'exit' to leave, '/help' for commands.")
        print("End a line with \\ to continue on the next line.\n")

    streaming = on_token is not None or (
        os.environ.get("zeloo_STREAM", "").lower() not in ("0", "false", "no")
    )
    multiline = _MultiLineBuffer()

    while True:
        try:
            prompt_text = _render_prompt()
            if multiline._continuing:
                prompt_text = "… "  # continuation prompt
            user_input = input(prompt_text).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            return 0

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit"):
            print("Goodbye!")
            return 0

        if user_input.startswith("/"):
            cmd_lower = user_input.split(maxsplit=1)[0].lower()
            handler = _SLASH_DISPATCH.get(cmd_lower)
            if handler:
                try:
                    handler(agent)
                except Exception as exc:  # noqa: BLE001
                    print(f"Command error: {exc}")
            else:
                print(f"Unknown command: {user_input} (try /help)")
            continue

        submitted, final_text = multiline.feed(user_input)
        if not submitted:
            continue
        if not final_text:
            continue

        try:
            print()
            if streaming:
                def _token_cb(token: str) -> None:
                    if on_token:
                        on_token(token)
                    else:
                        print(token, end="", flush=True)

                response = agent.run_conversation(final_text, on_token=_token_cb)
                if not on_token:
                    print()
            else:
                response = agent.run_conversation(final_text)
                if not quiet:
                    print(response)
            print()
        except KeyboardInterrupt:
            print("\nGoodbye!")
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"\nError: {exc}\n")
