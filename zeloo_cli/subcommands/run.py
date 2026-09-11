"""Zeloo run subcommand — execute a prompt locally or remotely."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from zeloo_cli.rich_render import make_console
from zeloo_cli.subcommands import Subcommand, subcommand
from zeloo_cli.remote_client import RemoteClient, RemoteConfig

logger = logging.getLogger(__name__)


@subcommand("run")
class RunCommand(Subcommand):
    """Run a prompt through local agent or remote gateway."""

    name = "run"
    help = "Execute a prompt (default local, or --remote <gateway>)"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("prompt", nargs="+", help="Prompt text (or '-' for stdin)")
        parser.add_argument(
            "--remote", default=None, metavar="URL",
            help="Forward to remote gateway (e.g. https://zeloo.example.com:9113 or zeloo://host:port)",
        )
        parser.add_argument("--api-key", default=None, help="API key for remote gateway")
        parser.add_argument("--model", default=None, help="Override model name")
        parser.add_argument("--provider", default=None, help="Provider for local run")
        parser.add_argument("--system", default=None, help="System prompt")
        parser.add_argument("--temperature", type=float, default=None)
        parser.add_argument("--max-tokens", type=int, default=None)
        parser.add_argument("--stdin", action="store_true", help="Read prompt from stdin")
        parser.add_argument("--check", action="store_true", help="Only check remote connectivity")

    def run(self, args: argparse.Namespace) -> int:
        """Execute the prompt."""
        prompt_text = self._gather_prompt(args)
        if not prompt_text:
            console = make_console()
            console.print("[red]No prompt provided[/red]")
            return 1

        if args.remote:
            return self._run_remote(args, prompt_text)
        else:
            return self._run_local(args, prompt_text)

    def _gather_prompt(self, args: argparse.Namespace) -> str:
        """Combine CLI args and stdin into a single prompt string."""
        parts = list(args.prompt) if args.prompt else []
        prompt_text = " ".join(parts).strip()

        if args.stdin or (len(parts) == 1 and parts[0] == "-"):
            stdin_data = sys.stdin.read()
            if prompt_text and prompt_text != "-":
                return f"{prompt_text}\n\n{stdin_data}"
            return stdin_data.strip()

        return prompt_text

    def _run_remote(self, args: argparse.Namespace, prompt: str) -> int:
        """Forward the prompt to a remote gateway."""
        api_key = args.api_key or os.environ.get("ZELOO_REMOTE_API_KEY")
        config = RemoteConfig.from_url(args.remote, api_key=api_key)
        client = RemoteClient(config)

        console = make_console()

        # Check connectivity first
        if not client.health_check():
            console.print(f"[red]Cannot reach remote gateway at {config.base_url}[/red]")
            console.print("[yellow]Check the URL and ensure the gateway is running[/yellow]")
            return 1

        if args.check:
            models = client.list_models()
            console.print(f"[green]✓[/green] Remote gateway reachable ({len(models)} models)")
            for m in models[:5]:
                console.print(f"  • {m}")
            return 0

        messages = []
        if args.system:
            messages.append({"role": "system", "content": args.system})
        messages.append({"role": "user", "content": prompt})

        kwargs = {}
        if args.temperature is not None:
            kwargs["temperature"] = args.temperature
        if args.max_tokens is not None:
            kwargs["max_tokens"] = args.max_tokens

        try:
            response = client.chat_completion(
                messages=messages, model=args.model, **kwargs,
            )
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            console.print(content)
            return 0
        except Exception as e:
            console.print(f"[red]Remote execution failed:[/red] {e}")
            return 1

    def _run_local(self, args: argparse.Namespace, prompt: str) -> int:
        """Run the prompt locally via the agent loop."""
        # Delegate to existing chat path or call agent_runtime
        # For simplicity, print a deprecation note + delegate to chat
        console = make_console()
        console.print(
            "[yellow]Hint:[/yellow] `zeloo run` without --remote is equivalent to `zeloo chat --query`. "
            "For richer interactions, use `zeloo chat` or `zeloo tui`."
        )
        # Inline one-shot
        import subprocess
        cmd = ["zeloo", "chat", "--query", prompt]
        if args.model:
            cmd.extend(["--model", args.model])
        if args.provider:
            cmd.extend(["--provider", args.provider])
        result = subprocess.run(cmd)
        return result.returncode
