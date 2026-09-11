"""Zeloo Agent CLI entry point — Hermes-style architecture.

Mirrors hermes_cli/main.py structure with:
- hermes_bootstrap at top of every entry point
- Startup watchdog arming for gateway foreground runs
- Early TUI decision (before heavy imports)
- _require_tty guard for interactive commands
- _set_process_title (cosmetic process name)
- Shared REPL engine from zeloo_cli.repl
- One-shot cleanup (_cleanup_oneshot_runtime)
- Profile-aware environment setup
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Callable, Optional, Union

import hermes_bootstrap

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

hermes_bootstrap.harden_import_path(str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

_ZELOO_VERSION = "0.16.0"

SubcommandHandler = Union[argparse.Action, Callable[[argparse.Namespace], int]]

# ── Startup watchdog ─────────────────────────────────────────────────────────


def _argv_is_gateway_foreground(argv: list[str]) -> bool:
    return any(a == "gateway" and b == "foreground" for a, b in zip(argv, argv[1:]))


if _argv_is_gateway_foreground(sys.argv[1:]):
    try:
        from hermes_startup_watchdog import arm_startup_watchdog as _arm_sw

        _arm_sw()
        del _arm_sw
    except Exception:
        pass

# ── One-shot cleanup ─────────────────────────────────────────────────────────


def _exit_after_oneshot(rc: object) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    try:
        logging.shutdown()
    except Exception:
        pass
    os._exit(rc if isinstance(rc, int) else (0 if rc is None else 1))


_ONESHOT_CLEANUPS: tuple[tuple[str, str, dict, type], ...] = (
    ("tools.terminal_tool", "cleanup_all_environments", {}, Exception),
    ("tools.mcp_tool_lifecycle", "shutdown_mcp_servers", {}, BaseException),
    ("agent.auxiliary_client", "shutdown_cached_clients", {}, Exception),
)


def _cleanup_oneshot_runtime() -> None:
    import importlib as _importlib

    for module, attr, kwargs, swallow in _ONESHOT_CLEANUPS:
        try:
            getattr(_importlib.import_module(module), attr)(**kwargs)
        except swallow:
            pass


# ── Process title ────────────────────────────────────────────────────────────


def _set_process_title() -> None:
    try:
        import setproctitle  # type: ignore[import-untyped]

        setproctitle.setproctitle("zeloo")
        return
    except ImportError:
        pass
    try:
        import ctypes
        import platform

        system = platform.system()
        if system == "Linux":
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            libc.prctl(15, b"zeloo", 0, 0, 0)  # PR_SET_NAME = 15
        elif system == "Darwin":
            libc = ctypes.CDLL("libc.dylib", use_errno=True)
            libc.pthread_setname_np(b"zeloo")
    except Exception:
        pass


# ── Early TUI decision ───────────────────────────────────────────────────────


def _config_default_interface_early() -> str:
    value = "cli"
    try:
        from agent.zeloo_constants import get_zeloo_home

        cfg_path = get_zeloo_home() / "config.yaml"
        if cfg_path.exists():
            import yaml as _yaml_e

            with open(cfg_path, encoding="utf-8") as _f:
                raw = _yaml_e.safe_load(_f) or {}
            disp = raw.get("display", {})
            if isinstance(disp, dict) and disp.get("interface", "").strip().lower() == "tui":
                value = "tui"
    except Exception:
        pass
    return value


def _wants_tui_early(argv: Optional[list[str]] = None) -> bool:
    if argv is None:
        argv = sys.argv[1:]
    if "--cli" in argv:
        return False
    if os.environ.get("ZELOO_TUI") == "1" or "--tui" in argv:
        return True
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False
    except Exception:
        return False
    return _config_default_interface_early() == "tui"


# ── TTY guard ────────────────────────────────────────────────────────────────


def _require_tty(command_name: str) -> None:
    if not sys.stdin.isatty():
        print(
            f"Error: 'zeloo {command_name}' requires an interactive terminal.\n"
            f"It cannot be run through a pipe or non-interactive subprocess.\n"
            f"Run it directly in your terminal instead.",
            file=sys.stderr,
        )
        sys.exit(1)


# ── version ──────────────────────────────────────────────────────────────────


def _print_version() -> None:
    print(f"Zeloo {_ZELOO_VERSION}")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ── subcommand handlers ──────────────────────────────────────────────────────


def _cmd_version(_args: argparse.Namespace) -> int:
    _print_version()
    return 0


def _cmd_chat(args: argparse.Namespace) -> int:
    from zeloo_cli.profiles import activate_profile
    from zeloo_cli.config import load_config, load_env_file
    from zeloo_cli.repl import run_interactive_repl

    profile = getattr(args, "profile", None) or "default"
    if profile != "default":
        activate_profile(profile)
    config = load_config()
    env = load_env_file()

    model = getattr(args, "model", None) or config.get("model", "gpt-4o")
    provider = getattr(args, "provider", None) or config.get("provider", "openai")
    base_url = getattr(args, "base_url", None) or env.get("BASE_URL", "") or config.get("base_url", "")
    api_key = getattr(args, "api_key", None) or env.get("API_KEY", "")
    max_iterations = getattr(args, "max_iterations", None) or config.get("max_iterations", 90)
    temperature = getattr(args, "temperature", None) or config.get("temperature", 0.0)
    resume = getattr(args, "resume", None) or getattr(args, "continue_", None)

    query = getattr(args, "query", None)
    query_file = getattr(args, "query_file", None)
    message = getattr(args, "message", None)

    if query_file:
        if query_file == "-":
            query_text = sys.stdin.read()
        else:
            query_text = Path(query_file).expanduser().read_text(encoding="utf-8")
    elif query:
        query_text = query
    elif message:
        query_text = " ".join(message)
    else:
        query_text = None

    if query_text is None:
        _require_tty("chat")

    streaming = os.environ.get("ZELOO_STREAM", "").lower() not in ("0", "false", "no")
    on_token = (lambda token: print(token, end="", flush=True)) if streaming else None

    try:
        from run_agent import AIAgent

        agent = AIAgent(
            model=model,
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            max_iterations=max_iterations,
            temperature=temperature,
            restore_session_id=resume,
        )
        try:
            if query_text is not None:
                response = agent.run_conversation(query_text, on_token=on_token)
                print() if on_token else print(response)
            else:
                run_interactive_repl(
                    agent,
                    quiet=getattr(args, "quiet", False) or getattr(args, "Q", False),
                    on_token=on_token,
                )
        finally:
            agent.close()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_tui(args: argparse.Namespace) -> int:
    _require_tty("tui")
    from zeloo_cli.profiles import activate_profile
    from zeloo_cli.config import load_config, load_env_file
    from zeloo_tui import is_textual_available, launch

    if not is_textual_available():
        print(
            "The TUI requires the 'textual' package.\n"
            "Install with:  uv pip install textual\n"
            "or:            pip install textual"
        )
        return 1

    profile = getattr(args, "profile", None) or "default"
    if profile != "default":
        activate_profile(profile)
    config = load_config()
    env = load_env_file()

    model = getattr(args, "model", None) or config.get("model", "gpt-4o")
    provider = getattr(args, "provider", None) or config.get("provider", "openai")
    base_url = getattr(args, "base_url", None) or env.get("BASE_URL", "") or config.get("base_url", "")
    api_key = getattr(args, "api_key", None) or env.get("API_KEY", "")

    try:
        from run_agent import AIAgent

        agent = AIAgent(
            model=model,
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            platform="tui",
        )

        import threading

        agent_thread = threading.Thread(
            target=lambda: agent.run_conversation(""),
            name="zeloo-tui-agent",
            daemon=True,
        )
        agent_thread.start()

        try:
            launch(chat_mode=True, on_exit=agent.close)
        finally:
            try:
                agent.shutdown()
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:
        print(f"Error launching TUI: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_gateway(args: argparse.Namespace) -> int:
    from zeloo_cli import gateway as gw

    action = getattr(args, "gateway_action", None)

    if action == "foreground":
        return gw.run_gateway_foreground(
            home=Path(args.home) if getattr(args, "home", None) else None,
            port=getattr(args, "port", None),
        )
    elif action == "start":
        return gw.cmd_gateway_start(args)
    elif action == "stop":
        return gw.cmd_gateway_stop(args)
    elif action == "restart":
        return gw.cmd_gateway_restart(args)
    elif action == "status":
        return gw.cmd_gateway_status(args)
    elif action == "install":
        return gw.cmd_gateway_install_service(args)
    elif action == "uninstall":
        return gw.cmd_gateway_uninstall_service(args)
    else:
        print("Usage: zeloo gateway [start|stop|restart|status|install|uninstall|foreground]")
        return 1


def _cmd_gateway_register(subparsers) -> None:
    p = subparsers.add_parser("gateway", help="Gateway process management")
    sp = p.add_subparsers(dest="gateway_action", help="Gateway action")

    for name, help_text in [
        ("start", "Start the gateway daemon"),
        ("stop", "Stop the gateway daemon"),
        ("restart", "Restart the gateway daemon"),
        ("status", "Show gateway status"),
        ("foreground", "Run gateway in foreground (blocking)"),
        ("install", "Install as a system service"),
        ("uninstall", "Uninstall the system service"),
    ]:
        sub = sp.add_parser(name, help=help_text)
        sub.add_argument("--port", type=int, default=None)
        sub.add_argument("--home", default=None)
        sub.add_argument("--no-drain", action="store_true")
        sub.add_argument("--supervised", action="store_true")

    p.set_defaults(func=_cmd_gateway)


def _cmd_doctor(args: argparse.Namespace) -> int:
    from zeloo_cli.subcommands import doctor

    return doctor.main(fix=getattr(args, "fix", False), json=getattr(args, "json", False))


def _cmd_install(args: argparse.Namespace) -> int:
    from zeloo_cli.subcommands import install

    return install.main(repair=getattr(args, "repair", False), minimal=getattr(args, "minimal", False))


def _cmd_config(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("config", args)


def _cmd_setup(args: argparse.Namespace) -> int:
    from zeloo_cli.subcommands.setup import cmd_setup as setup_handler

    return setup_handler(args)


def _cmd_cron(args: argparse.Namespace) -> int:
    from zeloo_cli.subcommands.cron import cmd_cron as cron_handler

    return cron_handler(args)


def _cmd_mcp(args: argparse.Namespace) -> int:
    from zeloo_cli.subcommands.mcp import cmd_mcp as mcp_handler

    return mcp_handler(args)


def _cmd_status(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("status", args)


def _cmd_sync(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("sync", args)


def _cmd_browser(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("browser", args)


def _cmd_backup(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("backup", args)


def _cmd_dump(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("dump", args)


def _cmd_secrets(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("secrets", args)


def _cmd_model(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("model", args)


def _cmd_skills(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("skills", args)


def _cmd_memory(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("memory", args)


def _cmd_auth(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("auth", args)


def _cmd_sessions(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("sessions", args)


def _cmd_logs(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("logs", args)


def _cmd_tools(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("tools", args)


def _cmd_profile(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("profile", args)


def _cmd_logout(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("logout", args)


def _cmd_login(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("login", args)


def _cmd_verify(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("verify", args)


def _cmd_uninstall(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("uninstall", args)


def _cmd_hooks(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("hooks", args)


def _cmd_plugins(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("plugins", args)


def _cmd_dashboard(args: argparse.Namespace) -> int:
    return _run_zeloo_subcommand("dashboard", args)


def _cmd_oneshot(args: argparse.Namespace) -> int:
    from zeloo_cli.oneshot import run_oneshot
    message = getattr(args, "message", None) or []
    return run_oneshot(" ".join(message))


def _run_zeloo_subcommand(name: str, args: argparse.Namespace) -> int:
    from zeloo_cli.subcommands import run_subcommand

    return run_subcommand(name, args)


# ── parser builder ───────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zeloo",
        description=f"Zeloo Agent {_ZELOO_VERSION} — self-hosted AI runtime",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("--version", action="store_true", help="Show version")
    parser.add_argument(
        "--profile", "-p", default=None,
        help="Select a profile for this invocation",
    )

    # Hermes Agent global flags
    parser.add_argument(
        "--tui", action="store_true",
        help="Launch the TUI instead of the classic CLI REPL.",
    )
    parser.add_argument(
        "--cli", dest="force_cli", action="store_true",
        help="Force the classic CLI REPL even when config requests TUI.",
    )
    parser.add_argument("--resume", "-r", default=None)
    parser.add_argument("--continue", "-c", dest="continue_", nargs="?", const="latest", default=None)
    parser.add_argument("--in", dest="in_dir", default=None)
    parser.add_argument("--worktree", "-w", action="store_true")
    parser.add_argument("--yolo", action="store_true")
    parser.add_argument("--checkpoints", action="store_true")
    parser.add_argument("--pass-session-id", action="store_true")
    parser.add_argument("--ignore-user-config", action="store_true")
    parser.add_argument("--ignore-rules", action="store_true")
    parser.add_argument("--quiet", "-Q", action="store_true", dest="Q")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # chat
    p = subparsers.add_parser("chat", help="Chat with the agent (default)")
    p.add_argument("--model", default=None)
    p.add_argument("--provider", default=None)
    p.add_argument("--base-url", dest="base_url", default=None)
    p.add_argument("--api-key", dest="api_key", default=None)
    p.add_argument("--max-iterations", type=int, default=None)
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("-q", "--query", default=None)
    p.add_argument("--query-file", default=None)
    p.add_argument("--resume", "-r", default=None)
    p.add_argument("--continue", "-c", dest="continue_", nargs="?", const="latest", default=None)
    p.add_argument("--toolsets", default=None)
    p.add_argument("-s", dest="skills", default=None)
    p.add_argument("--worktree", "-w", action="store_true")
    p.add_argument("--yolo", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--pass-session-id", action="store_true")
    p.add_argument("message", nargs="*")
    p.set_defaults(func=_cmd_chat)

    # tui
    p = subparsers.add_parser("tui", help="Launch the interactive TUI")
    p.add_argument("--model", default=None)
    p.add_argument("--provider", default=None)
    p.add_argument("--base-url", dest="base_url", default=None)
    p.add_argument("--api-key", dest="api_key", default=None)
    p.set_defaults(func=_cmd_tui)

    # version
    p = subparsers.add_parser("version", help="Print the Zeloo version")
    p.set_defaults(func=_cmd_version)

    # doctor
    p = subparsers.add_parser("doctor", help="Diagnose configuration issues")
    p.add_argument("--fix", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_doctor)

    # install
    p = subparsers.add_parser("install", help="Initialize or repair Zeloo")
    p.add_argument("--repair", action="store_true")
    p.add_argument("--minimal", action="store_true")
    p.set_defaults(func=_cmd_install)

    # config — delegated to zeloo_cli subcommands framework
    from zeloo_cli.subcommands.config import ConfigCmd

    p = subparsers.add_parser("config", help="Show, get, set, list or edit configuration")
    ConfigCmd.configure_parser(p)
    p.set_defaults(func=_cmd_config)

    # model — model management
    from zeloo_cli.subcommands.model import ModelCmd

    p = subparsers.add_parser("model", help="List, test and manage available models")
    ModelCmd.configure_parser(p)
    p.set_defaults(func=_cmd_model)

    # setup / cron / mcp / status / sync / browser (delegated to zeloo_cli subcommands framework)
    from zeloo_cli.subcommands.setup import build_setup_parser
    from zeloo_cli.subcommands.cron import build_cron_parser
    from zeloo_cli.subcommands.mcp import build_mcp_parser
    from zeloo_cli.subcommands.skills import build_skills_parser
    from zeloo_cli.subcommands.memory import build_memory_parser
    from zeloo_cli.subcommands.auth import build_auth_parser

    build_setup_parser(subparsers, cmd_setup_handler=_cmd_setup)
    build_cron_parser(subparsers, cmd_cron_handler=_cmd_cron)
    build_mcp_parser(subparsers, cmd_mcp_handler=_cmd_mcp)
    build_skills_parser(subparsers, cmd_skills_handler=_cmd_skills)
    build_memory_parser(subparsers, cmd_memory_handler=_cmd_memory)
    build_auth_parser(subparsers, cmd_auth_handler=_cmd_auth)

    # status — full system + gateway + agent status
    p = subparsers.add_parser("status", help="Show agent, gateway and system status")
    p.add_argument("--json", action="store_true")
    p.add_argument("--agent", action="store_true")
    p.add_argument("--gateway", action="store_true")
    p.add_argument("--system", action="store_true")
    p.set_defaults(func=_cmd_status)

    # sync — memory/skills sync status and operations
    sync_parser = subparsers.add_parser("sync", help="Sync local memory and skills with remote (if configured)")
    sync_sub = sync_parser.add_subparsers(dest="sync_command")
    sync_sub.add_parser("status", help="Show sync status")
    sync_sub.add_parser("push", help="Push local to remote")
    sync_sub.add_parser("pull", help="Pull remote to local")
    sync_sub.add_parser("now", help="Full reconciliation (pull + push)")
    sp = sync_sub.add_parser("stats", help="Show sync statistics")
    sp.add_argument("--by", choices=["skill", "date"], default="date")
    sync_parser.set_defaults(func=_cmd_sync)

    # browser — browser process management
    p = subparsers.add_parser("browser", help="Browser process management (close real-profile browser)")
    bp = p.add_subparsers(dest="browser_action")
    bp.add_parser("close-profile", help="Close the browser holding the real profile").add_argument("--browser", choices=["chrome", "edge", "brave", "chromium"])
    bp.add_parser("list-browsers", help="List available Chromium-based browsers")
    bp.add_parser("check-profile", help="Check if real browser profile directory is accessible")
    p.set_defaults(func=_cmd_browser)

    # backup — backup management
    from zeloo_cli.subcommands.backup import BackupCmd

    p = subparsers.add_parser("backup", help="Backup management (create, list, restore, delete)")
    BackupCmd.configure_parser(p)
    p.set_defaults(func=_cmd_backup)

    # dump — data export
    from zeloo_cli.subcommands.dump import DumpCmd

    p = subparsers.add_parser("dump", help="Export sessions, memories or config")
    DumpCmd.configure_parser(p)
    p.set_defaults(func=_cmd_dump)

    # secrets — secrets management
    from zeloo_cli.subcommands.secrets import SecretsCmd

    p = subparsers.add_parser("secrets", help="Manage encrypted secrets")
    SecretsCmd.configure_parser(p)
    p.set_defaults(func=_cmd_secrets)

    _cmd_gateway_register(subparsers)

    # sessions — session history management
    p = subparsers.add_parser("sessions", help="Manage session history (list, show, delete, search)")
    sp = p.add_subparsers(dest="sessions_action")
    sp.add_parser("list", help="List recent sessions").add_argument(
        "--limit", "-n", type=int, default=20
    )
    sp.add_parser("show", help="Show session details").add_argument("session_id")
    delete_p = sp.add_parser("delete", help="Delete a session")
    delete_p.add_argument("session_id")
    delete_p.add_argument("--force", action="store_true")
    sp.add_parser("search", help="Search session messages").add_argument("query")
    p.set_defaults(func=_cmd_sessions)

    # logs — log viewing and management
    p = subparsers.add_parser("logs", help="View, tail, or clear Zeloo logs")
    p.add_argument("--lines", "-n", type=int, default=100)
    p.add_argument("--level", "-l", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default=None)
    sp = p.add_subparsers(dest="logs_action")
    sp.add_parser("tail", help="Follow log output in real-time")
    sp.add_parser("clear", help="Clear all log files").add_argument("--force", action="store_true")
    sp.add_parser("list", help="List available log files")
    p.set_defaults(func=_cmd_logs)

    # tools — tool discovery and validation
    p = subparsers.add_parser("tools", help="List, inspect and validate available tools")
    sp = p.add_subparsers(dest="tools_action")
    sp.add_parser("list", help="List all available tools")
    sp.add_parser("show", help="Show detailed info for a tool").add_argument("tool_name")
    sp.add_parser("validate", help="Validate tool configuration and registration")
    p.set_defaults(func=_cmd_tools)

    # profile — multi-profile management
    from zeloo_cli.subcommands.profile import ProfileCmd

    p = subparsers.add_parser("profile", help="Manage Zeloo profiles")
    ProfileCmd.configure_parser(p)
    p.set_defaults(func=_cmd_profile)

    # logout — clear authentication
    from zeloo_cli.subcommands.logout import LogoutCmd

    p = subparsers.add_parser("logout", help="Clear authentication credentials")
    LogoutCmd.configure_parser(p)
    p.set_defaults(func=_cmd_logout)

    # login — deprecated login command
    from zeloo_cli.subcommands.login import LoginCmd

    p = subparsers.add_parser("login", help="Interactive login (deprecated — use auth login)")
    LoginCmd.configure_parser(p)
    p.set_defaults(func=_cmd_login)

    # verify — project verification
    from zeloo_cli.subcommands.verify import VerifyCmd

    p = subparsers.add_parser("verify", help="Detect project recipe and smoke-test it")
    VerifyCmd.configure_parser(p)
    p.set_defaults(func=_cmd_verify)

    # uninstall — uninstall Zeloo
    from zeloo_cli.subcommands.uninstall import UninstallCmd

    p = subparsers.add_parser("uninstall", help="Uninstall Zeloo Agent")
    UninstallCmd.configure_parser(p)
    p.set_defaults(func=_cmd_uninstall)

    # hooks — shell hook management
    from zeloo_cli.subcommands.hooks import HooksCmd
    p = subparsers.add_parser("hooks", help="Inspect and manage shell-script hooks")
    HooksCmd.configure_parser(p)
    p.set_defaults(func=_cmd_hooks)

    # plugins — plugin management
    from zeloo_cli.subcommands.plugins import PluginsCmd
    p = subparsers.add_parser("plugins", help="Manage plugins (list, install, remove, enable, disable)")
    PluginsCmd.configure_parser(p)
    p.set_defaults(func=_cmd_plugins)

    # dashboard — web UI dashboard
    from zeloo_cli.subcommands.dashboard import DashboardCmd
    p = subparsers.add_parser("dashboard", help="Start the web UI dashboard")
    DashboardCmd.configure_parser(p)
    p.set_defaults(func=_cmd_dashboard)

    # z — oneshot shortcut
    p = subparsers.add_parser("z", help="Oneshot mode — send prompt, get response, exit")
    p.add_argument("message", nargs="*")
    p.set_defaults(func=_cmd_oneshot)

    return parser


# ── main ─────────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    load_dotenv()

    parser = _build_parser()
    args = parser.parse_args(argv)

    _setup_logging(getattr(args, "verbose", False))

    if getattr(args, "version", False):
        _print_version()
        return 0

    _set_process_title()

    # Profile activation
    if getattr(args, "profile", None):
        from zeloo_cli.profiles import activate_profile

        activate_profile(args.profile)

    # Global env mutations (Hermes Agent parity)
    if getattr(args, "in_dir", None):
        try:
            os.chdir(args.in_dir)
        except Exception as exc:
            print(f"Cannot chdir to {args.in_dir}: {exc}", file=sys.stderr)
            return 1

    command = getattr(args, "command", None)

    # TUI shortcut: `zeloo` (no args) or `--tui` → launch TUI
    if command is None and _wants_tui_early():
        command = "tui"

    handler: Optional[SubcommandHandler] = getattr(args, "func", None)

    if handler is not None:
        try:
            return handler(args)  # type: ignore[return-value]
        except SystemExit:
            raise
        except Exception as exc:
            logger.exception("Command failed")
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if command is None:
        return _cmd_chat(args)

    print(f"Unknown command: {command}")
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
