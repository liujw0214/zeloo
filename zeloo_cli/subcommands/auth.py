"""Zeloo ``auth`` subcommand — authentication status and management."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("auth")
class AuthCmd(Subcommand):
    name = "auth"
    help = "Manage authentication status and tokens"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="auth_action", help="Auth action")

        sub.add_parser("status", help="Show current authentication status")

        login_parser = sub.add_parser("login", help="Execute login flow")
        login_parser.add_argument(
            "provider",
            nargs="?",
            default=None,
            help=(
                "Provider name (e.g. openai, anthropic). "
                "Omit for the generic API-key prompt."
            ),
        )
        login_parser.add_argument(
            "--api-key",
            dest="api_key",
            default=None,
            help="Directly provide an API key for the provider (skips OAuth).",
        )
        login_parser.add_argument(
            "--code",
            dest="code",
            default=None,
            help="OAuth authorization code (for callback flow).",
        )
        login_parser.add_argument(
            "--redirect-uri",
            dest="redirect_uri",
            default="http://localhost:8888/callback",
            help="OAuth redirect URI (default: http://localhost:8888/callback).",
        )
        login_parser.add_argument(
            "--device-flow",
            dest="use_device_flow",
            action="store_true",
            help="Use RFC 8628 device authorization grant instead of the browser flow.",
        )

        sub.add_parser("logout", help="Clear authentication information")

        sub.add_parser("refresh", help="Refresh authentication token")

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "auth_action", None)
        if action == "status":
            return self._status()
        if action == "login":
            return _login(
                provider=getattr(args, "provider", None),
                api_key=getattr(args, "api_key", None),
                code=getattr(args, "code", None),
                redirect_uri=getattr(args, "redirect_uri", "http://localhost:8888/callback"),
                use_device_flow=getattr(args, "use_device_flow", False),
            )
        if action == "logout":
            return self._logout()
        if action == "refresh":
            return self._refresh()
        print("Usage: Zeloo auth [status|login|logout|refresh]")
        return 1

    def _get_zeloo_home(self) -> Path:
        val = os.environ.get("ZELOO_HOME", "").strip()
        if val:
            return Path(val)
        if sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA", "").strip()
            base = Path(local) if local else Path.home() / "AppData" / "Local"
            return base / "Zeloo"
        return Path.home() / ".Zeloo"

    def _get_auth_file(self) -> Path:
        return self._get_zeloo_home() / "auth.json"

    def _load_auth_info(self) -> dict | None:
        auth_file = self._get_auth_file()
        if not auth_file.exists():
            return None
        try:
            content = auth_file.read_text(encoding="utf-8")
            return json.loads(content)
        except Exception:
            return None

    def _save_auth_info(self, info: dict) -> None:
        auth_file = self._get_auth_file()
        auth_file.parent.mkdir(parents=True, exist_ok=True)
        auth_file.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")

    def _status(self) -> int:
        from zeloo_state import SessionDB

        auth_info = self._load_auth_info()

        has_api_key = False
        env_api_key = os.environ.get("API_KEY", "").strip()
        if env_api_key:
            has_api_key = True

        db_authenticated = False
        db_api_key_set = False
        try:
            db = SessionDB()
            sessions = db.list_sessions(limit=1) or []
            db_authenticated = len(sessions) >= 0
            db_api_key_set = db_authenticated
        except Exception:
            pass

        from zeloo_cli.rich_render import make_console, render_keyvalue

        console = make_console()
        pairs: list[tuple[str, str]] = []

        if auth_info:
            pairs.append(("Auth file", "present"))
            pairs.append(("User ID", auth_info.get("user_id", "unknown")))
            pairs.append(("Token valid", "yes" if auth_info.get("token") else "no"))
        else:
            pairs.append(("Auth file", "not found"))

        pairs.append(("API_KEY env var", "set" if has_api_key else "not set"))
        pairs.append(("Session DB", "accessible" if db_authenticated else "unavailable"))

        render_keyvalue(pairs)
        return 0

    def _logout(self) -> int:
        auth_file = self._get_auth_file()
        if auth_file.exists():
            try:
                auth_file.unlink()
                print("Authentication cleared.")
            except Exception as exc:
                print(f"Failed to clear auth: {exc}")
                return 1
        else:
            print("No authentication file found.")
        return 0

    def _refresh(self) -> int:
        auth_info = self._load_auth_info()
        if not auth_info:
            print("No authentication found. Run 'Zeloo auth login' first.")
            return 1

        print("Refreshing authentication token...")
        print("(Token refresh not yet implemented — this is a placeholder)")

        new_token = auth_info.get("token", "")
        if new_token:
            print(f"Token refreshed (simulated): {new_token[:16]}...")
        return 0


# ── Module-level dispatch helper ────────────────────────────────────────


def _legacy_login(api_key: str | None) -> int:
    """Original generic API-key prompt (preserved for backward compatibility)."""
    from zeloo_cli.rich_render import make_console

    console = make_console()
    cmd = AuthCmd()
    print("Starting login flow...")
    print("(Interactive login requires browser OAuth — this is a placeholder)")

    if not api_key:
        api_key = input("Enter API key (or press Enter to skip): ").strip()
    if api_key:
        cmd._save_auth_info(
            {
                "api_key": api_key,
                "user_id": "manual",
                "token": api_key[:16] + "..." if len(api_key) > 16 else api_key,
            }
        )
        print("API key saved to auth.json")
    else:
        print("No API key provided. Set API_KEY environment variable instead.")
    return 0


def _login(
    provider: str | None = None,
    api_key: str | None = None,
    code: str | None = None,
    redirect_uri: str = "http://localhost:8888/callback",
    use_device_flow: bool = False,
) -> int:
    """Authenticate with a specific provider or generic API key.

    Args:
        provider: Provider name (e.g. 'openai', 'anthropic'). None = generic key prompt.
        api_key: API key for direct entry (skips OAuth flow).
        code: OAuth authorization code (for callback flow).
        redirect_uri: OAuth redirect URI.
        use_device_flow: Use device flow (RFC 8628) where supported.
    """
    from zeloo_cli.rich_render import make_console

    console = make_console()

    if provider is None:
        # Original generic API key flow.
        return _legacy_login(api_key)

    # Provider-specific dispatch.
    import zeloo_cli.auth  # trigger eager registration
    from zeloo_cli.auth import AUTH_REGISTRY, get_auth
    from zeloo_cli.auth.token_store import TokenStore

    if provider not in AUTH_REGISTRY:
        console.print(f"[red]Unknown provider:[/red] {provider}")
        console.print(
            "[yellow]Available providers:[/yellow] "
            + ", ".join(sorted(AUTH_REGISTRY.keys()))
        )
        return 1

    auth = get_auth(provider)

    # 1. Already authenticated?
    if auth.is_authenticated():
        console.print(f"[green]✓[/green] Already authenticated with {provider}")
        return 0

    # 2. Direct API-key path.
    if api_key:
        env_var = f"{provider.upper()}_API_KEY"
        os.environ[env_var] = api_key
        # Reload so the provider picks up the env var.
        auth = get_auth(provider, api_key=api_key)
        if auth.is_authenticated():
            TokenStore().save(
                provider,
                {
                    "access_token": api_key,
                    "token_type": "Bearer",
                    "expires_at": None,
                    "scope": "",
                },
            )
            console.print(f"[green]✓[/green] Authenticated with {provider}")
            return 0

    # 3. OAuth / device flow.
    try:
        if use_device_flow:
            # Use the provider's device-flow helper when available
            # (e.g. OpenAI Codex). Otherwise fall back to a generic
            # DeviceFlowClient built from the provider's endpoints.
            device_login = getattr(auth, "device_login", None)
            if callable(device_login):
                token = asyncio.run(device_login())
            else:
                client = getattr(auth, "device_flow_client", None)
                if client is None:
                    console.print(
                        f"[red]Provider {provider} does not support the device flow[/red]"
                    )
                    return 1
                token = asyncio.run(client().run())
            # Persist via the base helper if available.
            save = getattr(auth, "save_token", None)
            if callable(save):
                save(token)
            else:
                TokenStore().save(provider, token.to_dict())
            console.print(f"[green]✓[/green] Authenticated with {provider} via device flow")
            return 0

        # Authorization-code flow.
        auth_url = auth.get_auth_url(redirect_uri)
        console.print("[yellow]Open this URL in your browser:[/yellow]")
        console.print(auth_url)

        if not code:
            try:
                code = input("\nPaste authorization code: ").strip()
            except EOFError:
                code = ""

        if not code:
            console.print("[red]No code provided[/red]")
            return 1

        token = asyncio.run(auth.exchange_code(code, redirect_uri))
        save = getattr(auth, "save_token", None)
        if callable(save):
            save(token)
        else:
            TokenStore().save(provider, token.to_dict())
        console.print(f"[green]✓[/green] Authenticated with {provider}")
        return 0
    except Exception as exc:  # noqa: BLE001 — surface any provider error
        console.print(f"[red]Auth failed:[/red] {exc}")
        return 1


def build_auth_parser(subparsers: Any, *, cmd_auth_handler: Any) -> None:
    """Attach the Hermes-style ``auth`` subparser."""
    from typing import Any

    auth_parser = subparsers.add_parser(
        "auth", help="Authentication management", description="Manage authentication status and tokens"
    )
    auth_subparsers = auth_parser.add_subparsers(dest="auth_action")

    auth_subparsers.add_parser("status", help="Show current authentication status")

    login_parser = auth_subparsers.add_parser("login", help="Execute login flow")
    login_parser.add_argument(
        "provider",
        nargs="?",
        default=None,
        help=(
            "Provider name (e.g. openai, anthropic). "
            "Omit for the generic API-key prompt."
        ),
    )
    login_parser.add_argument("--api-key", dest="api_key", default=None)
    login_parser.add_argument("--code", dest="code", default=None)
    login_parser.add_argument(
        "--redirect-uri",
        dest="redirect_uri",
        default="http://localhost:8888/callback",
    )
    login_parser.add_argument(
        "--device-flow",
        dest="use_device_flow",
        action="store_true",
    )

    auth_subparsers.add_parser("logout", help="Clear authentication information")
    auth_subparsers.add_parser("refresh", help="Refresh authentication token")

    auth_parser.set_defaults(func=cmd_auth_handler)