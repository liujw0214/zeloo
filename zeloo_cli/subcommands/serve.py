"""Zeloo serve subcommand — run the OpenAI-compatible API gateway server.

This is a thin, foreground wrapper around :class:`gateway.api_server.APIServer`.
It exists so that ``zeloo serve`` mirrors the documented CLI surface
(see ``docs/CLI_REFERENCE.md`` § *Core Conversation* → ``Zeloo serve``).

The actual HTTP server lives in :mod:`gateway.api_server`; this module
only:

1. parses CLI options (host / port / workers / reload / api-key / CORS / model),
2. builds an :class:`APIServer` instance with a minimal agent factory,
3. blocks the main thread until ``Ctrl+C`` (or any other shutdown signal).
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from zeloo_cli.subcommands import Subcommand, subcommand

logger = logging.getLogger(__name__)


@subcommand("serve")
class ServeCommand(Subcommand):
    """Run the OpenAI-compatible API gateway server."""

    name = "serve"
    help = (
        "Run the OpenAI-compatible API gateway server "
        "(alias for `zeloo gateway foreground`)"
    )

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Attach serve-specific flags to *parser*."""
        parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
        parser.add_argument(
            "--port", type=int, default=9113, help="Listen port (default: 9113)",
        )
        parser.add_argument(
            "--workers", type=int, default=1, help="Worker count (default: 1)",
        )
        parser.add_argument(
            "--reload", action="store_true", help="Auto-reload on code changes",
        )
        parser.add_argument(
            "--api-key", default=None, help="Bearer token for API auth",
        )
        parser.add_argument(
            "--cors-origins", default="*", help="Comma-separated CORS origins",
        )
        parser.add_argument(
            "--model-name", default="Zeloo",
            help="Model name reported to OpenAI clients",
        )

    def run(self, args: argparse.Namespace) -> int:
        """Start the API server (foreground)."""
        from gateway.api_server import APIServer

        cors_origins = self._parse_cors(args.cors_origins)
        auth_tokens = self._parse_auth_tokens(args.api_key)

        agent_factory = self._build_agent_factory()

        server = APIServer(
            agent_factory=agent_factory,
            host=args.host,
            port=args.port,
            model_name=args.model_name,
            auth_tokens=auth_tokens,
        )
        # CORS origins are passed through to the handler at construction time
        # when supported; APIServer currently exposes them via a class
        # attribute to keep the constructor signature stable.
        APIServer.cors_origins = cors_origins  # type: ignore[attr-defined]

        reload_enabled = bool(getattr(args, "reload", False))
        self._log_startup(args, cors_origins, auth_tokens, reload_enabled)

        # Install a SIGINT/SIGTERM handler so the foreground process
        # stops cleanly on Ctrl+C without leaking the background thread.
        stop_event = threading.Event()

        def _shutdown(signum: int, _frame: Any) -> None:
            logger.info("Received signal %s; shutting down API server...", signum)
            stop_event.set()
            try:
                server.stop()
            except Exception:  # noqa: BLE001
                logger.exception("Error while stopping API server")

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _shutdown)
            except (ValueError, OSError):
                # signal() may fail in sub-threads or on Windows for SIGTERM
                pass

        try:
            server.start()
        except OSError as exc:
            print(f"Error: failed to start API server: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("API server crashed during startup")
            print(f"Error: API server failed: {exc}", file=sys.stderr)
            return 1

        try:
            # Block the main thread; server runs in a background thread.
            stop_event.wait()
        except KeyboardInterrupt:
            _shutdown(signal.SIGINT, None)
        finally:
            try:
                server.stop()
            except Exception:  # noqa: BLE001
                logger.exception("Error while stopping API server")
        return 0

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_cors(raw: str | None) -> list[str]:
        """Parse a comma-separated CORS origin string into a clean list."""
        if not raw:
            return ["*"]
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        return origins or ["*"]

    @staticmethod
    def _parse_auth_tokens(raw: str | None) -> list[str] | None:
        """Collect API auth tokens from CLI and env."""
        tokens: list[str] = []
        if raw:
            tokens.append(raw)
        env_token = os.environ.get("zeloo_API_TOKEN", "").strip()
        if env_token:
            tokens.append(env_token)
        return tokens or None

    def _build_agent_factory(self) -> Callable[..., Any]:
        """Build a minimal agent factory compatible with ``APIServer``.

        The factory signature is ``(**kwargs) -> AIAgent``. We lazily
        import :mod:`run_agent` so that ``serve --help`` and unit
        tests don't pull the entire agent runtime into the process.
        """

        def _factory(**_kwargs: Any) -> Any:
            try:
                from run_agent import AIAgent
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"Cannot import AIAgent; run `zeloo setup` first ({exc})",
                ) from exc
            return AIAgent(platform="api")

        return _factory

    @staticmethod
    def _log_startup(
        args: argparse.Namespace,
        cors_origins: list[str],
        auth_tokens: list[str] | None,
        reload_enabled: bool,
    ) -> None:
        """Print a friendly startup banner."""
        workers = max(1, int(getattr(args, "workers", 1) or 1))
        print(
            f"Zeloo API server starting on http://{args.host}:{args.port}\n"
            f"  model_name:    {args.model_name}\n"
            f"  workers:       {workers}\n"
            f"  reload:        {reload_enabled}\n"
            f"  cors_origins:  {', '.join(cors_origins)}\n"
            f"  auth:          {'enabled' if auth_tokens else 'disabled'}\n"
            "Press Ctrl+C to stop."
        )


__all__ = ["ServeCommand"]


# Make ``python -m zeloo_cli.subcommands.serve`` work as a smoke test.
if __name__ == "__main__":  # pragma: no cover
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    parser = argparse.ArgumentParser(prog="zeloo serve")
    ServeCommand.configure_parser(parser)
    ns = parser.parse_args()
    raise SystemExit(ServeCommand().run(ns))
