"""Zeloo Agent CLI — interactive command-line interface."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from run_agent import AIAgent
from zeloo_cli.config import load_config, load_env_file


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments with subcommand support.

    Subcommands mirror Zeloo CLI surface:
      install, doctor, config, status, backup, skills, session, model, mcp,
      tools, update, gateway, usage, oauth, chat.

    When no subcommand is given, falls back to chat mode (interactive or
    single-message).
    """
    cfg = load_config()

    parser = argparse.ArgumentParser(
        prog="zeloo",
        description="Zeloo Agent — a self-hosted, self-evolving AI agent",
    )
    parser.add_argument(
        "--profile", "-p",
        default=None,
        help="Select a profile for this invocation",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    # ---- Hermes Agent v0.16 global options (Round 66) ----
    parser.add_argument(
        "--tui", action="store_true",
        help="Launch the TUI instead of the classic CLI (equivalent to `zeloo tui`).",
    )
    parser.add_argument(
        "--cli", dest="force_cli", action="store_true",
        help="Force the classic CLI REPL even when config requests TUI.",
    )
    parser.add_argument(
        "--resume", "-r", default=None,
        help="Resume a previous session by ID or 'latest'.",
    )
    parser.add_argument(
        "--continue", "-c", dest="continue_", nargs="?", const="latest", default=None,
        help="Resume the most recent (or named) session.",
    )
    parser.add_argument(
        "--in", dest="in_dir", default=None,
        help="Change into <dir> before starting/resuming a session.",
    )
    parser.add_argument(
        "--worktree", "-w", action="store_true",
        help="Start in an isolated git worktree for parallel-agent workflows.",
    )
    parser.add_argument(
        "--yolo", action="store_true",
        help="Bypass dangerous-command approval prompts.",
    )
    parser.add_argument(
        "--checkpoints", action="store_true",
        help="Enable filesystem checkpoints before destructive file operations.",
    )
    parser.add_argument(
        "--pass-session-id", action="store_true",
        help="Include the session ID in the agent's system prompt.",
    )
    parser.add_argument(
        "--ignore-user-config", action="store_true",
        help="Ignore ~/.zeloo/config.yaml and fall back to built-in defaults.",
    )
    parser.add_argument(
        "--ignore-rules", action="store_true",
        help="Skip auto-injection of AGENTS.md / SOUL.md / memory / preloaded skills.",
    )
    parser.add_argument(
        "--quiet", "-Q", action="store_true",
        help="Suppress banner, spinner, and tool previews — output final response only.",
    )
    parser.add_argument(
        "--version", action="store_true",
        help="Show version and exit.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Chat (default)
    chat = subparsers.add_parser("chat", help="Chat with the agent (default)")
    chat.add_argument("--model", default=os.environ.get("zeloo_MODEL", cfg.get("model", "gpt-4o")))
    chat.add_argument(
        "--provider",
        default=os.environ.get("zeloo_PROVIDER", cfg.get("provider", "openai")),
    )
    chat.add_argument("--base-url", default=os.environ.get("zeloo_BASE_URL"))
    chat.add_argument("--api-key", default=None)
    chat.add_argument("--max-iterations", type=int, default=cfg.get("max_iterations", 90))
    chat.add_argument("--temperature", type=float, default=cfg.get("temperature", 0.0))
    chat.add_argument(
        "-q", "--query", default=None,
        help="Single non-interactive query (exits after response).",
    )
    chat.add_argument(
        "--query-file", default=None,
        help="Read the query from a file ('-' for stdin). Verbatim — no shell parsing.",
    )
    chat.add_argument("--resume", "-r", default=None, help="Resume a session by ID or 'latest'.")
    chat.add_argument(
        "--continue", "-c", dest="continue_", nargs="?", const="latest", default=None,
        help="Resume the most recent (or named) session.",
    )
    chat.add_argument(
        "message", nargs="*", help="Single message (omit for interactive)",
    )

    # Config
    config_p = subparsers.add_parser("config", help="Show or modify configuration")
    config_p.add_argument("action", choices=["show", "get", "set"], help="Action to perform")
    config_p.add_argument("key", nargs="?", help="Config key (dot-notation, e.g. model.provider)")
    config_p.add_argument("value", nargs="?", help="Value to set")

    # Install
    install_p = subparsers.add_parser("install", help="Initialize or repair Zeloo environment")
    install_p.add_argument("--repair", action="store_true", help="Repair broken installation")
    install_p.add_argument("--minimal", action="store_true", help="Skip optional dependency checks")

    # Doctor
    doctor_p = subparsers.add_parser("doctor", help="Diagnose configuration and dependency issues")
    doctor_p.add_argument("--fix", action="store_true", help="Automatically repair fixable issues")
    doctor_p.add_argument("--json", action="store_true", help="Output results as JSON")

    # Status: full implementation with --json / --watch lives in the
    # Round 66 block below. The simple stub that used to live here
    # was removed because argparse rejects duplicate subparsers.

    # Backup
    backup_p = subparsers.add_parser("backup", help="Back up the Zeloo home directory")
    backup_p.add_argument("--output", "-o", default=None, help="Output zip file path")

    # Status (Round 66: extended with --json / --watch)
    status_p = subparsers.add_parser("status", help="Show agent, auth, and platform status")
    status_p.add_argument("--json", action="store_true", dest="as_json",
                          help="Output status as JSON")
    status_p.add_argument("--watch", "-w", action="store_true",
                          help="Continuously refresh status every 2s")

    # Model — routed through zeloo_cli.subcommands.model which has its
    # own sub-parsers (``list`` / ``test``). We replicate the sub-parser
    # here so argparse can validate the sub-action before dispatch.
    model_p = subparsers.add_parser("model", help="List and test available models")
    model_sp = model_p.add_subparsers(dest="model_action", help="Model action")
    model_list_p = model_sp.add_parser("list", help="List all available models")
    model_list_p.add_argument("--provider", "-p", default=None, help="Filter by provider")
    model_test_p = model_sp.add_parser("test", help="Send a test request to a model")
    model_test_p.add_argument("model", help="Model name to test (e.g. gpt-4o)")
    model_test_p.add_argument("--provider", "-p", default="openai", help="Provider")
    model_test_p.add_argument(
        "--message", "-m", default="Reply with just 'OK'", help="Test message",
    )

    # Skills
    skills_p = subparsers.add_parser("skills", help="List available skills")
    skills_p.add_argument("action", nargs="?", default="list", choices=["list"])

    # Session
    session_p = subparsers.add_parser("session", help="Manage sessions")
    session_sp = session_p.add_subparsers(dest="session_action", help="Session action")
    list_p = session_sp.add_parser("list", help="List recent sessions")
    list_p.add_argument("--limit", type=int, default=20, help="Max sessions to show")
    export_p = session_sp.add_parser("export", help="Export session to JSONL")
    export_p.add_argument("session_id", help="Session ID to export")
    export_p.add_argument("--output", "-o", default=None, help="Output file path")
    delete_p = session_sp.add_parser("delete", help="Delete a session")
    delete_p.add_argument("session_id", help="Session ID to delete")
    delete_p.add_argument("--force", action="store_true", help="Skip confirmation")

    # MCP
    mcp_p = subparsers.add_parser("mcp", help="Manage MCP servers")
    mcp_sp = mcp_p.add_subparsers(dest="mcp_action", help="MCP action")
    mcp_list_p = mcp_sp.add_parser("list", help="List configured MCP servers")
    mcp_list_p.add_argument("--verbose", "-v", action="store_true", help="Show server details")
    mcp_test_p = mcp_sp.add_parser("test", help="Test an MCP server")
    mcp_test_p.add_argument("server", help="Server name")
    mcp_add_p = mcp_sp.add_parser("add", help="Add an MCP server")
    mcp_add_p.add_argument("server", help="Server name")
    mcp_add_p.add_argument("command", help="Command to run")
    mcp_add_p.add_argument("args", nargs="*", help="Additional arguments")

    # Usage
    usage_p = subparsers.add_parser("usage", help="Show API usage and cost reports")
    usage_sp = usage_p.add_subparsers(dest="usage_action", help="Usage report type")
    usage_sp.add_parser("total", help="Total usage across all sessions")
    usage_sp.add_parser("platform", help="Usage grouped by platform")
    session_usage_p = usage_sp.add_parser("session", help="Usage for a specific session")
    session_usage_p.add_argument("session_id", help="Session ID")

    # Tools
    tools_p = subparsers.add_parser("tools", help="List and inspect available tools")
    tools_sp = tools_p.add_subparsers(dest="tools_action", help="Tools action")
    tools_list_p = tools_sp.add_parser("list", help="List all tools")
    tools_list_p.add_argument("--category", "-c", default=None, help="Filter by category")
    tools_list_p.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")
    tools_show_p = tools_sp.add_parser("show", help="Show tool details")
    tools_show_p.add_argument("tool_name", help="Tool name")

    # Update
    update_p = subparsers.add_parser("update", help="Check for and install updates")
    update_p.add_argument("--check", action="store_true", help="Check only, do not install")
    update_p.add_argument("--pip", action="store_true", help="Also update core dependencies")

    # OAuth
    oauth_p = subparsers.add_parser("oauth", help="Manage OAuth logins for providers")
    oauth_p.add_argument("action", choices=["login", "logout", "status"], help="OAuth action")
    oauth_p.add_argument("provider", nargs="?", help="OAuth provider")

    # TUI
    tui_p = subparsers.add_parser(
        "tui",
        help="Launch the terminal UI (TUI) over the agent event stream",
    )
    tui_p.add_argument(
        "--demo",
        action="store_true",
        help="Inject synthetic events so the TUI works without an LLM key",
    )
    tui_p.add_argument(
        "--chat",
        action="store_true",
        help="Run the interactive chat-style TUI with history + slash completion",
    )
    tui_p.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )

    # Setup (Round 56: borrowed from Hermes Agent)
    setup_p = subparsers.add_parser(
        "setup",
        help="Interactive setup wizard (provider / model / API key)",
    )
    setup_p.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing config.yaml / .env without prompting",
    )
    setup_p.add_argument(
        "--json",
        action="store_true",
        help="Output a JSON summary of what was written",
    )
    setup_p.add_argument(
        "--home",
        default=None,
        help="Target Zeloo home directory (default: ~/.Zeloo)",
    )

    # Skin (Round 56: borrowed from Hermes Agent)
    skin_p = subparsers.add_parser(
        "skin",
        help="List / show / set CLI skins (color theme + banner)",
    )
    skin_sp = skin_p.add_subparsers(dest="skin_action", help="Skin action")
    skin_sp.add_parser("list", help="List available skins")
    skin_show = skin_sp.add_parser("show", help="Show the active skin in YAML form")
    skin_show.add_argument(
        "--name",
        default=None,
        help="Skin to show (default: $zeloo_SKIN or 'default')",
    )
    skin_set = skin_sp.add_parser("set", help="Set a single skin value")
    skin_set.add_argument("key", help="Dot-path, e.g. colors.prompt")
    skin_set.add_argument("value", help="New value (string, int, bool)")
    skin_set.add_argument(
        "--skin",
        default="default",
        help="Skin to modify (default: default)",
    )

    # Version (Round 66: Hermes Agent parity)
    subparsers.add_parser(
        "version",
        help="Print the Zeloo version (equivalent to --version)",
    )

    # Plugins (Round 66: Hermes Agent parity)
    plugins_p = subparsers.add_parser(
        "plugins",
        help="Manage native plugins and portable Agent Plugins v1 packages",
    )
    plugins_sp = plugins_p.add_subparsers(dest="plugins_action", help="Plugins action")
    plugins_sp.add_parser("list", help="List installed plugins")
    install_p = plugins_sp.add_parser("install", help="Install a plugin")
    install_p.add_argument("name", help="Plugin name (owner/repo or local path)")
    install_p.add_argument(
        "--no-enable", action="store_true",
        help="Install but leave the plugin disabled.",
    )
    enable_p = plugins_sp.add_parser("enable", help="Enable a plugin")
    enable_p.add_argument("name", help="Plugin name")
    disable_p = plugins_sp.add_parser("disable", help="Disable a plugin")
    disable_p.add_argument("name", help="Plugin name")
    plugins_sp.add_parser("update", help="Update a plugin (or all)").add_argument(
        "name", nargs="?", default=None,
    )
    remove_p = plugins_sp.add_parser("remove", help="Remove a plugin")
    remove_p.add_argument("name", help="Plugin name")

    # Cron (Round 66: Hermes Agent parity)
    cron_p = subparsers.add_parser(
        "cron",
        help="Manage scheduled tasks (cron-style)",
    )
    cron_sp = cron_p.add_subparsers(dest="cron_action", help="Cron action")
    cron_sp.add_parser("list", help="List scheduled tasks")
    cron_add_p = cron_sp.add_parser("add", help="Add a scheduled task")
    cron_add_p.add_argument("name", help="Task name")
    cron_add_p.add_argument("schedule", help="5-field cron expression")
    # NOTE: ``command`` would clash with the top-level subparsers'
    # ``dest="command"`` (argparse would store the positional list
    # there and break dispatch). Use ``task`` instead and join in
    # :func:`_cmd_cron`.
    cron_add_p.add_argument("task", nargs="+", help="Command to run (multi-word)")
    cron_rm_p = cron_sp.add_parser("remove", help="Remove a scheduled task")
    cron_rm_p.add_argument("name", help="Task name")

    return parser.parse_args()


def interactive_mode(agent: AIAgent) -> None:
    """Run the interactive REPL — delegated to the shared zeloo_cli.repl module."""
    from zeloo_cli.repl import run_interactive_repl

    streaming = os.environ.get("zeloo_STREAM", "").lower() not in ("0", "false", "no")
    on_token = (lambda token: print(token, end="", flush=True)) if streaming else None
    run_interactive_repl(agent, on_token=on_token)


def handle_command(command: str, agent: AIAgent) -> None:
    """Handle slash commands."""
    if command == "/help":
        print("/help     — show this help")
        print("/model    — show current model")
        print("/session  — show session ID")
        print("/review   — trigger background review of current session")
        print("/plugins  — list loaded plugins")
        print("/stats    — show cache statistics")
        print("/undo     — take back the last turn")
        print("/clear    — clear screen")
        print("quit      — exit")
    elif command == "/model":
        print(f"Model: {agent.model} (provider: {agent.provider})")
    elif command == "/session":
        print(f"Session ID: {agent.session_id}")
    elif command == "/review":
        _trigger_review(agent)
    elif command == "/plugins":
        _list_plugins()
    elif command == "/stats":
        stats = agent.cache_stats()
        print(f"Cache hits:   {stats['hits']}")
        print(f"Cache misses: {stats['misses']}")
        print(f"Hit rate:     {stats['hit_rate']:.1%}")
    elif command == "/undo":
        _undo_last_turn(agent)
    elif command == "/clear":
        os.system("cls" if os.name == "nt" else "clear")
    else:
        print(f"Unknown command: {command}")


def _list_plugins() -> None:
    """List loaded plugins and their tools."""
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
    except Exception as e:
        print(f"Error loading plugins: {e}")


def _trigger_review(agent: AIAgent) -> None:
    """Manually trigger a background review of the current session."""
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
        name=f"manual-review-{agent.session_id}",
    ).start()
    print(f"Background review triggered for session {agent.session_id}")


def _background_version_check() -> None:
    """Check for newer Zeloo versions in a background subprocess.

    Mirrors Hermes Agent's behavior in ``hermes_bootstrap.py``: spawn
    ``python -m zeloo_cli update --check`` so the main CLI process is
    never blocked on the PyPI round-trip. The child is bounded by a 30 s
    timeout; if it exceeds that we kill it and move on.

    Disabled when:
    - ``zeloo_DISABLE_UPDATE_CHECK`` is set to ``1``/``true``
    - stdout is not a TTY *and* ``zeloo_FORCE_UPDATE_CHECK`` is unset

    Failures are swallowed — the background check must never crash the
    main program.
    """
    import subprocess
    import sys

    # Skip if disabled via env
    if os.environ.get("zeloo_DISABLE_UPDATE_CHECK", "").lower() in ("1", "true"):
        return

    # Skip in non-interactive contexts (CI, cron, captured pipes)
    if not sys.stdout.isatty() and not os.environ.get("zeloo_FORCE_UPDATE_CHECK"):
        return

    try:
        # Invoke the project's CLI entry module (``cli.py``) as a
        # subprocess. ``-m zeloo_cli`` doesn't work because ``zeloo_cli``
        # is a subpackage without ``__main__``; ``cli.main`` is the
        # canonical entry wired into the ``Zeloo`` console script.
        proc = subprocess.Popen(
            [sys.executable, "-m", "cli", "update", "--check"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        return

    try:
        stdout, stderr = proc.communicate(timeout=30.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=2.0)
        except Exception:
            pass
        return
    except Exception:
        # Background check failure should never crash the main program
        return

    if proc.returncode != 0:
        return

    # Friendly notification only when a newer version was actually found.
    if "new version" in stdout.lower() or "update available" in stdout.lower():
        try:
            sys.stderr.write(f"[zeloo] {stdout.strip()}\n")
            sys.stderr.write("[zeloo] Run `zeloo update` to upgrade.\n")
            sys.stderr.flush()
        except Exception:
            pass


def main() -> None:
    """Entry point — dispatches subcommands or runs chat mode."""
    load_dotenv()
    args = parse_args()
    setup_logging(args.verbose)

    # ── `--version` short-circuits everything else ─────────────────
    if getattr(args, "version", False):
        from zeloo_cli.__about__ import __version__

        print(__version__)
        return 0

    if getattr(args, "profile", None):
        from zeloo_cli.profiles import activate_profile
        activate_profile(args.profile)

    # ── Apply Hermes Agent global flags (Round 66) ────────────────
    # Flags mutate env / cwd before any subcommand runs so downstream
    # code sees consistent state.
    _apply_global_flags(args)

    # ── Fire-and-forget background version check ─────────────────
    # Skipped when we *are* the `update --check` subprocess or when the
    # user disabled it via env / non-tty context (see helper).
    import threading
    if getattr(args, "command", None) != "update":
        threading.Thread(
            target=_background_version_check,
            daemon=True,
            name="zeloo-version-check",
        ).start()

    # `--tui` is equivalent to `zeloo tui --chat` — TUI wins over chat.
    if getattr(args, "tui", False):
        args.command = "tui"
        if not getattr(args, "chat", False):
            args.chat = True

    command = getattr(args, "command", None) or "chat"

    # ── Heavy subcommands → routed through zeloo_cli.subcommands framework
    # (install / doctor / model / session / mcp / tools / update / usage)
    if command in _SUBCOMMAND_ROUTING:
        from zeloo_cli.subcommands import _SUBCOMMANDS, _load_subcommands

        # Force import of all subcommand modules so the @subcommand
        # decorators populate ``_SUBCOMMANDS``.
        _load_subcommands()

        cls = _SUBCOMMANDS.get(command)
        if cls is None:
            print(f"Unknown subcommand: {command}")
            return 1
        return cls().run(args)

    # ── Lightweight subcommands kept inline (no class boilerplate) ──
    if command == "config":
        _cmd_config(args)
        return
    if command == "status":
        _cmd_status(args)
        return
    if command == "backup":
        _cmd_backup(args)
        return
    if command == "skills":
        _cmd_skills()
        return
    if command == "oauth":
        _cmd_oauth(args)
        return
    if command == "tui":
        _cmd_tui(args)
        return
    if command == "setup":
        return _cmd_setup(args)
    if command == "skin":
        return _cmd_skin(args)
    if command == "version":
        return _cmd_version()
    if command == "plugins":
        return _cmd_plugins(args)
    if command == "cron":
        rc = _cmd_cron(args)
        if rc is not None:
            return rc

    # ── Default: chat mode (REPL or single message) ──
    _load_plugins()

    # ── Session resume (Hermes Agent parity) ────────────────────────
    resume_target = _resolve_resume_target(args)
    if resume_target:
        os.environ["zeloo_RESUME_SESSION_ID"] = resume_target

    agent = AIAgent(
        model=args.model,
        provider=args.provider,
        base_url=args.base_url,
        api_key=args.api_key,
        platform="cli",
        max_iterations=args.max_iterations,
        temperature=args.temperature,
        restore_session_id=resume_target,
    )

    try:
        # --query / --query-file / positional → single-shot mode
        query_text = _read_query_text(args)
        if query_text is not None:
            response = agent.run_conversation(query_text)
            print(response)
        elif args.message:
            message = " ".join(args.message)
            response = agent.run_conversation(message)
            print(response)
        else:
            interactive_mode(agent)
    finally:
        agent.close()


# Map of subcommand names whose implementation lives in
# ``zeloo_cli.subcommands.*`` and is invoked via :func:`run_subcommand`.
_SUBCOMMAND_ROUTING = frozenset({
    "install", "doctor", "model", "session", "mcp", "tools", "update", "usage",
})


def _apply_global_flags(args: argparse.Namespace) -> None:
    """Translate Hermes Agent global flags into env vars / cwd.

    Called *before* any subcommand runs. Mirrors Hermes Agent's
    ``pre_run_hook`` pattern from ``cli.py``.
    """
    # `--in <dir>`: cd into the directory before anything else.
    in_dir = getattr(args, "in_dir", None)
    if in_dir:
        try:
            os.chdir(in_dir)
            os.environ["zeloo_CWD"] = str(Path(in_dir).resolve())
        except OSError as exc:
            print(f"Error: --in {in_dir!r} failed: {exc}", file=sys.stderr)

    # Boolean flags → env vars so downstream code can read them
    # uniformly (this is the same convention Hermes uses).
    if getattr(args, "yolo", False):
        os.environ["zeloo_YOLO"] = "1"
    if getattr(args, "checkpoints", False):
        os.environ["zeloo_CHECKPOINTS"] = "1"
    if getattr(args, "ignore_user_config", False):
        os.environ["zeloo_IGNORE_USER_CONFIG"] = "1"
    if getattr(args, "ignore_rules", False):
        os.environ["zeloo_IGNORE_RULES"] = "1"
    if getattr(args, "quiet", False):
        os.environ["zeloo_QUIET"] = "1"
    if getattr(args, "worktree", False):
        os.environ["zeloo_WORKTREE"] = "1"
        # Actually create an isolated git worktree and chdir into it.
        # Previously this flag was a no-op; now it mirrors Hermes Agent's
        # `pre_run_hook` behavior so parallel agent runs don't collide.
        if not os.environ.get("ZELOO_WORKTREE_PATH"):
            try:
                from zeloo_cli.worktree_helper import (
                    create_worktree,
                    is_in_worktree,
                )
                if not is_in_worktree():
                    repo_root = Path(__file__).resolve().parent
                    wt_info = create_worktree(repo_root)
                    os.chdir(wt_info.worktree_path)
                    os.environ["ZELOO_WORKTREE_PATH"] = str(wt_info.worktree_path)
                    os.environ["zeloo_WORKTREE_BRANCH"] = wt_info.branch_name
                    os.environ["zeloo_WORKTREE_SESSION"] = wt_info.session_id
                    print(f"[worktree] Created isolated branch {wt_info.branch_name}")
            except RuntimeError as exc:
                print(f"[worktree] Failed: {exc}", file=sys.stderr)
    if getattr(args, "pass_session_id", False):
        os.environ["zeloo_PASS_SESSION_ID"] = "1"

    # Propagate top-level --resume / --continue into chat-level args
    # if the chat subcommand didn't already set them.
    if getattr(args, "command", None) == "chat":
        if getattr(args, "resume", None) is None:
            args.resume = getattr(args, "_resume_global", None)
        if getattr(args, "_continue_global", None) is not None:
            args.continue_ = args._continue_global


def _resolve_resume_target(args: argparse.Namespace) -> str | None:
    """Return the session ID to resume, or ``None``.

    Honors the chat-level ``--resume`` / ``--continue`` flags (which
    always win over the global ones). Falls back to the most recent
    session when the keyword ``"latest"`` is passed.
    """
    candidate = (
        getattr(args, "resume", None)
        or getattr(args, "continue_", None)
        or getattr(args, "_continue_global", None)
    )
    if not candidate:
        return None

    if candidate == "latest":
        try:
            from zeloo_state import SessionDB

            db = SessionDB()
            sessions = db.list_sessions(limit=1)
            return sessions[0]["session_id"] if sessions else None
        except Exception:  # noqa: BLE001
            return None

    # Treat as a literal session ID (or a substring prefix if the
    # SessionDB supports prefix lookups; otherwise pass through).
    return candidate


def _read_query_text(args: argparse.Namespace) -> str | None:
    """Return the user query text from ``--query`` / ``--query-file`` / stdin.

    Precedence: ``--query`` > ``--query-file`` > None. Verbatim copy —
    the user is allowed to pass arbitrary text including quotes,
    ``$(...)`` and backticks without shell parsing.
    """
    if getattr(args, "query", None):
        return args.query

    path = getattr(args, "query_file", None)
    if not path:
        return None

    try:
        if path == "-":
            return sys.stdin.read()
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error: cannot read --query-file {path!r}: {exc}", file=sys.stderr)
        return None


def _cmd_config(args: argparse.Namespace) -> None:
    """Handle `Zeloo config show|get|set`."""
    from zeloo_cli.config import get_config_path, save_config

    cfg = load_config()

    if args.action == "show":
        import yaml
        print(yaml.dump(cfg, default_flow_style=False, sort_keys=False))
        return

    if args.action == "get":
        if not args.key:
            print("Usage: Zeloo config get <key>")
            return
        value = _get_nested(cfg, args.key)
        print(value if value is not None else f"(not set: {args.key})")
        return

    if args.action == "set":
        if not args.key or args.value is None:
            print("Usage: Zeloo config set <key> <value>")
            return
        _set_nested(cfg, args.key, args.value)
        save_config(cfg)
        print(f"Set {args.key} = {args.value}")
        print(f"Config saved to: {get_config_path()}")


def _cmd_status(args: argparse.Namespace) -> None:
    """Show agent, auth, and platform status.

    Round 66 (Hermes Agent parity): supports ``--json`` for
    machine-readable output and ``--watch`` for a 2s auto-refresh
    loop. ``Ctrl+C`` exits the watch loop cleanly.
    """
    cfg = load_config()
    profile = os.environ.get("zeloo_PROFILE", "default")

    def _snapshot() -> dict:
        env = load_env_file()
        flags = {k: v for k, v in env.items() if k.startswith("zeloo_")}
        return {
            "provider": cfg.get("provider", "openai"),
            "model": cfg.get("model", "gpt-4o"),
            "max_iterations": cfg.get("max_iterations", 90),
            "temperature": cfg.get("temperature", 0.0),
            "profile": profile,
            "platform_flags": flags,
            "global_flags": {
                k: v for k, v in {
                    "yolo": os.environ.get("zeloo_YOLO"),
                    "checkpoints": os.environ.get("zeloo_CHECKPOINTS"),
                    "quiet": os.environ.get("zeloo_QUIET"),
                    "worktree": os.environ.get("zeloo_WORKTREE"),
                    "ignore_rules": os.environ.get("zeloo_IGNORE_RULES"),
                    "ignore_user_config": os.environ.get("zeloo_IGNORE_USER_CONFIG"),
                }.items() if v
            },
            "timestamp": time.time(),
        }

    if getattr(args, "as_json", False):
        import json

        if getattr(args, "watch", False):
            try:
                while True:
                    print(json.dumps(_snapshot(), indent=2, sort_keys=True), flush=True)
                    print("---", flush=True)
                    time.sleep(2)
            except KeyboardInterrupt:
                return
        else:
            print(json.dumps(_snapshot(), indent=2, sort_keys=True))
        return

    # Human-readable rendering (Rich-rendered via rich_render).
    from zeloo_cli.rich_render import render_keyvalue

    if getattr(args, "watch", False):
        try:
            while True:
                if os.name == "nt":
                    os.system("cls")
                else:
                    os.system("clear")
                snap = _snapshot()
                render_keyvalue([
                    ("Provider", snap["provider"]),
                    ("Model", snap["model"]),
                    ("Max iterations", str(snap["max_iterations"])),
                    ("Temperature", str(snap["temperature"])),
                    ("Profile", snap["profile"]),
                    ("Global flags", str(snap["global_flags"]) or "(none)"),
                    ("Updated", time.strftime("%Y-%m-%d %H:%M:%S",
                                              time.localtime(snap["timestamp"]))),
                ])
                print("(Ctrl+C to exit watch)")
                time.sleep(2)
        except KeyboardInterrupt:
            return
    else:
        snap = _snapshot()
        render_keyvalue([
            ("Provider", snap["provider"]),
            ("Model", snap["model"]),
            ("Max iterations", str(snap["max_iterations"])),
            ("Temperature", str(snap["temperature"])),
            ("Profile", snap["profile"]),
            ("Global flags", str(snap["global_flags"]) or "(none)"),
        ])
        print("\nPlatform flags (from .env):")
        for k, v in sorted(snap["platform_flags"].items()):
            print(f"  {k}={v}")


def _cmd_backup(args: argparse.Namespace) -> None:
    """Back up the Zeloo home directory to a zip file."""
    import shutil
    from datetime import datetime

    home = os.path.expanduser(os.environ.get("zeloo_HOME", "~/.Zeloo"))
    if not os.path.isdir(home):
        print(f"Nothing to back up: {home} does not exist")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Default output goes into the *current working directory*, which
    # avoids writing into directories the sandbox / OS blocks by default.
    # Operators can still pass --output to choose any other path.
    output = args.output or os.path.join(
        os.getcwd(), f"zeloo_backup_{timestamp}.zip"
    )

    try:
        shutil.make_archive(output.replace(".zip", ""), "zip", home)
        size = os.path.getsize(output)
        print(f"Backup created: {output} ({size:,} bytes)")
    except PermissionError as exc:
        print(f"Backup failed (permission denied): {exc}")
        print(
            "Hint: pass --output to write to a writable directory "
            "(e.g. `zeloo backup --output ./zeloo_backup.zip`)."
        )
    except OSError as exc:
        print(f"Backup failed: {exc}")


def _cmd_skills() -> None:
    """List available skills."""
    from agent.skill_utils import (
        extract_skill_description,
        extract_skill_name,
        iter_skill_index_files,
        parse_frontmatter,
    )

    skills: dict[str, str] = {}
    for skill_file in iter_skill_index_files():
        try:
            content = skill_file.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            name = extract_skill_name(fm, skill_file)
            desc = extract_skill_description(fm)
            skills[name] = desc
        except Exception:
            pass

    if not skills:
        print("No skills found.")
        return

    # Rich-rendered table (Hermes Agent parity).
    from zeloo_cli.rich_render import make_console, make_table

    console = make_console()
    table = make_table(
        title=f"Available skills ({len(skills)})",
        columns=[
            ("NAME", "bold cyan"),
            ("DESCRIPTION", "white"),
        ],
    )
    for name, desc in skills.items():
        table.add_row(name, (desc or "")[:80])
    console.print(table)

def _cmd_oauth(args: argparse.Namespace) -> None:
    """Manage OAuth logins for providers."""
    from agent.oauth import OAuthTokenStore
    from agent.oauth import login as oauth_login

    store = OAuthTokenStore()
    action = args.action

    if action == "status":
        providers = store.list_providers()
        if not providers:
            print("No OAuth logins. Use `Zeloo oauth login <provider>` to add one.")
            print("Known OAuth providers: codex, nous")
            return
        print("OAuth logins:")
        for name in providers:
            token = store.get(name)
            if token is None:
                continue
            exp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(token.expires_at)) \
                if token.expires_at > 0 else "never"
            state = "expired" if token.is_expired else "valid"
            print(f"  {name:<12} {state:<8} expires: {exp}")
        return

    provider = args.provider
    if not provider:
        print(f"Error: 'oauth {action}' requires a provider name.")
        print(f"Usage: Zeloo oauth {action} <provider>")
        return

    if action == "login":
        try:
            oauth_login(provider)
        except Exception as exc:
            print(f"OAuth login failed: {exc}")
    elif action == "logout":
        token = store.get(provider)
        if token is None:
            print(f"No stored token for '{provider}'.")
            return
        store.delete(provider)
        print(f"Logged out from '{provider}'.")


def _cmd_tui(args: argparse.Namespace) -> int:
    """Launch the Zeloo terminal UI (Textual-based).

    Falls back to a helpful install message when ``textual`` is missing.
    The ``--demo`` flag injects a synthetic event stream so the UI can
    be exercised without configuring an LLM key.
    """
    from zeloo_tui import is_textual_available, launch

    if not is_textual_available():
        print(
            "The TUI requires the 'textual' package.\n"
            "Install with:  uv pip install textual\n"
            "or:            pip install textual"
        )
        return 1

    if getattr(args, "demo", False):
        # Run the demo emitter on a daemon thread before textual takes
        # over the main thread.
        from zeloo_tui.cli import _start_demo_emitter

        _start_demo_emitter()

    return launch(chat_mode=getattr(args, "chat", False))


def _get_nested(cfg: dict, key: str) -> object:
    """Get a value from nested dict using dot-notation key."""
    parts = key.split(".")
    cur: object = cfg
    for part in parts:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _set_nested(cfg: dict, key: str, value: str) -> None:
    """Set a value in nested dict using dot-notation key."""
    parts = key.split(".")
    cur = cfg
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    parsed: object = value
    if value.lower() in ("true", "false"):
        parsed = value.lower() == "true"
    else:
        try:
            parsed = int(value)
        except ValueError:
            try:
                parsed = float(value)
            except ValueError:
                parsed = value
    cur[parts[-1]] = parsed


def _load_plugins() -> None:
    """Load all plugins from the plugins directory."""
    try:
        from plugins.manager import PluginManager
        mgr = PluginManager(plugin_dirs=["plugins"])
        infos = mgr.load_all()
        loaded = [n for n, i in infos.items() if i.enabled]
        if loaded:
            names = ", ".join(loaded)
            logging.getLogger(__name__).debug(
                "Loaded %d plugin(s): %s", len(loaded), names
            )
    except Exception:
        logging.getLogger(__name__).exception("Failed to load plugins")


def _cmd_setup(args: argparse.Namespace) -> int:
    """Run the interactive setup wizard (borrowed from Hermes Agent).

    Builds a :class:`WizardAnswers` and writes it to
    ``config.yaml`` + ``.env`` in the Zeloo home directory. The
    wizard auto-degrades to a defaults-only flow when stdin is not
    a TTY (CI / docker entrypoint), so the same code path is safe to
    invoke from non-interactive contexts.
    """
    from pathlib import Path

    from zeloo_cli.setup_wizard import run_setup

    home = Path(args.home) if args.home else None
    return run_setup(home=home, overwrite=args.overwrite, json_output=args.json)


def _cmd_skin(args: argparse.Namespace) -> int:
    """Manage CLI / TUI skins.

    Subcommands:

    * ``zeloo skin list`` — built-in + user skins
    * ``zeloo skin show`` — pretty-print the active skin
    * ``zeloo skin set colors.prompt magenta`` — override a single
      field of a user skin
    """
    from zeloo_cli.skin_engine import (
        list_skins,
        load_skin,
        set_skin_value,
    )

    action = getattr(args, "skin_action", None)
    if action == "list":
        for s in list_skins():
            print(f"  {s['name']:<16} [{s['source']}] {s['title']}")
        return 0
    if action == "show":
        skin = load_skin(args.name)
        import json

        print(json.dumps(skin.to_dict(), indent=2))
        return 0
    if action == "set":
        # Coerce value to int / bool / str to match the dataclass
        # field's expected type. The CLI accepts string input so
        # this is the standard "auto-type" idiom.
        raw = args.value
        if raw.lower() == "true":
            value: object = True
        elif raw.lower() == "false":
            value = False
        else:
            try:
                value = int(raw)
            except ValueError:
                try:
                    value = float(raw)
                except ValueError:
                    value = raw
        path = set_skin_value(args.key, value, skin_name=args.skin)
        print(f"Updated {args.key}={value!r} in {path}")
        return 0
    print("Usage: zeloo skin [list|show|set <key> <value>]")
    return 1


# ---------------------------------------------------------------------------
# Round 66: Hermes Agent v0.16.0 parity commands.
# ---------------------------------------------------------------------------


def _cmd_version() -> int:
    """Print the Zeloo version. Mirrors Hermes Agent's ``hermes version``."""
    from zeloo_cli.__about__ import __codename__, __version__

    print(f"Zeloo {__version__}  —  {__codename__}")
    return 0


def _cmd_plugins(args: argparse.Namespace) -> int:
    """Manage native plugins (Hermes Agent parity).

    Backed by ``plugins.manager.PluginManager``. The manager reads
    ``plugins/*.py`` and tracks enable/disable state in ``plugin_state``.
    """
    try:
        from plugins.manager import PluginManager
    except Exception as exc:  # noqa: BLE001
        print(f"Error: plugins subsystem unavailable: {exc}")
        return 1

    action = getattr(args, "plugins_action", None)
    if not action:
        print("Usage: Zeloo plugins [list|install|enable|disable|update|remove]")
        return 1

    mgr = PluginManager(plugin_dirs=["plugins"])

    if action == "list":
        try:
            infos = mgr.load_all()
        except Exception as exc:  # noqa: BLE001
            print(f"Error loading plugins: {exc}")
            return 1
        if not infos:
            print("(no plugins found)")
            return 0
        from zeloo_cli.rich_render import make_console, make_table

        table = make_table(
            title=f"Installed plugins ({len(infos)})",
            columns=[
                ("NAME", "bold cyan"),
                ("STATUS", "yellow"),
                ("TOOLS", "white"),
            ],
        )
        for name, info in infos.items():
            table.add_row(
                name,
                "enabled" if info.enabled else f"disabled ({info.error or 'ok'})",
                ", ".join(info.tools_added) if info.tools_added else "(none)",
            )
        make_console().print(table)
        return 0

    if action == "enable":
        mgr.enable(args.name)
        print(f"Plugin enabled: {args.name}")
        return 0

    if action == "disable":
        mgr.disable(args.name)
        print(f"Plugin disabled: {args.name}")
        return 0

    if action == "install":
        try:
            mgr.install(args.name, enable=not getattr(args, "no_enable", False))
            print(f"Plugin installed: {args.name}")
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"Install failed: {exc}")
            return 1

    if action == "remove":
        mgr.remove(args.name)
        print(f"Plugin removed: {args.name}")
        return 0

    if action == "update":
        target = getattr(args, "name", None) or "*"
        mgr.update(target)
        print(f"Plugin update issued for: {target}")
        return 0

    print(f"Unknown plugins action: {action}")
    return 1


def _cmd_cron(args: argparse.Namespace) -> int:
    """Manage scheduled tasks (Hermes Agent parity)."""
    try:
        from zeloo_cli.cron_store import CronStore
    except Exception:  # noqa: BLE001
        # Fall back to an in-process scheduler.
        from zeloo_cli.cron_store import InMemoryCronStore as CronStore  # type: ignore

    store = CronStore()
    action = getattr(args, "cron_action", None)
    if not action:
        print("Usage: Zeloo cron [list|add|remove]")
        return 1

    if action == "list":
        tasks = store.list_tasks()
        if not tasks:
            print("(no scheduled tasks)")
            return 0
        from zeloo_cli.rich_render import make_console, make_table

        table = make_table(
            title=f"Scheduled tasks ({len(tasks)})",
            columns=[
                ("NAME", "bold cyan"),
                ("SCHEDULE", "yellow"),
                ("COMMAND", "white"),
            ],
        )
        for t in tasks:
            table.add_row(t["name"], t["schedule"], t["command"])
        make_console().print(table)
        return 0

    if action == "add":
        command_text = " ".join(args.task)
        store.add_task(args.name, args.schedule, command_text)
        print(f"Task scheduled: {args.name}  @  {args.schedule}")
        return 0

    if action == "remove":
        store.remove_task(args.name)
        print(f"Task removed: {args.name}")
        return 0

    print(f"Unknown cron action: {action}")
    return 1


def _undo_last_turn(agent: AIAgent) -> None:
    """Take back the last N turns (Hermes Agent ``/undo`` parity).

    Implementation note: we pop the most recent ``user`` + ``assistant``
    messages from the in-memory transcript and append a synthetic
    ``[undone]`` marker so the conversation loop sees the corrected
    history. Persisted messages in ``zeloo_state.messages`` are not
    deleted (matches Hermes behaviour — undo only affects the live
    session).
    """
    history = getattr(agent, "_history", None)
    if not history:
        print("Nothing to undo.")
        return

    # Pop the last pair (user + assistant) until we find a user turn
    # or hit the beginning.
    popped = 0
    while history and popped < 2:
        msg = history.pop()
        if msg.get("role") == "user" and popped >= 1:
            popped += 1
            break
        if msg.get("role") == "assistant" and popped == 0:
            popped += 1
        elif msg.get("role") == "user" and popped == 0:
            popped += 1
            break
    history.append({"role": "system", "content": "[undone] last turn rolled back."})
    if hasattr(agent, "_turn_count"):
        agent._turn_count = max(0, agent._turn_count - 1)
    print(f"Undid last turn ({popped} message(s) popped).")


if __name__ == "__main__":
    main()
