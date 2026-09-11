"""Zeloo model subcommand — model listing, testing and management."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("model")
class ModelCmd(Subcommand):
    name = "model"
    help = "List, test and manage available models"

    PROVIDERS = {
        "openai": {
            "gpt-4o": "Latest GPT-4 with vision",
            "gpt-4o-mini": "Fast, affordable GPT-4",
            "gpt-4-turbo": "GPT-4 Turbo (128k context)",
            "gpt-3.5-turbo": "Legacy fast model",
        },
        "anthropic": {
            "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet (200k context)",
            "claude-3-5-haiku-20241022": "Claude 3.5 Haiku (fast)",
            "claude-3-opus-20240229": "Claude 3 Opus",
        },
        "deepseek": {
            "deepseek-chat": "DeepSeek Chat (128k context)",
            "deepseek-coder": "DeepSeek Coder",
        },
        "gemini": {
            "gemini-1.5-pro": "Gemini 1.5 Pro (2M context)",
            "gemini-1.5-flash": "Gemini 1.5 Flash (fast)",
        },
        "ollama": {
            "llama3.1": "Meta Llama 3.1 (local)",
            "qwen2.5": "Qwen 2.5 (local)",
            "mistral": "Mistral (local)",
        },
    }

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="model_action", help="Model action")

        list_p = sub.add_parser("list", help="List all available models")
        list_p.add_argument(
            "--provider", "-p", default=None,
            help="Filter by provider (openai, anthropic, deepseek...)",
        )

        sub.add_parser("current", help="Show the current default model")

        set_p = sub.add_parser("set", help="Set the default model")
        set_p.add_argument("model", help="Model name to set as default")

        info_p = sub.add_parser("info", help="Show detailed info about a model")
        info_p.add_argument("model", help="Model name to query")

        test_p = sub.add_parser("test", help="Send a test request to a model")
        test_p.add_argument("model", help="Model name to test (e.g. gpt-4o)")
        test_p.add_argument("--provider", "-p", default="openai", help="Provider")
        test_p.add_argument(
            "--message", "-m", default="Reply with just 'OK'",
            help="Test message to send",
        )

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "model_action", None)
        if action == "list":
            return self._list(args.provider)
        if action == "current":
            return self._current()
        if action == "set":
            return self._set(args.model)
        if action == "info":
            return self._info(args.model)
        if action == "test":
            return self._test(args.model, args.provider, args.message)
        print("Usage: Zeloo model [list|current|set|info|test]")
        return 1

    def _get_config_path(self) -> Path:
        from agent.zeloo_constants import get_zeloo_home
        return get_zeloo_home() / "config.yaml"

    def _load_config(self) -> dict:
        import yaml
        path = self._get_config_path()
        if not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _save_config(self, config: dict) -> None:
        import yaml
        path = self._get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def _list(self, provider: str | None) -> int:
        print("Available models:")
        for pname, models in sorted(self.PROVIDERS.items()):
            if provider and pname != provider:
                continue
            print(f"\n  [{pname}]")
            for mname, desc in sorted(models.items()):
                print(f"    {mname:<40} {desc}")
        return 0

    def _current(self) -> int:
        config = self._load_config()
        model = config.get("model", "gpt-4o")
        provider = config.get("provider", "openai")
        print(f"Current model: {model}")
        print(f"Current provider: {provider}")
        return 0

    def _set(self, model: str) -> int:
        config = self._load_config()
        old_model = config.get("model", "gpt-4o")
        config["model"] = model
        self._save_config(config)
        print(f"Default model changed: {old_model} -> {model}")
        return 0

    def _info(self, model: str) -> int:
        found = False
        for pname, models in self.PROVIDERS.items():
            if model in models:
                found = True
                print(f"Model: {model}")
                print(f"Provider: {pname}")
                print(f"Description: {models[model]}")
                return 0

        if not found:
            print(f"Model '{model}' not found in known models.")
            print()
            print("Known models:")
            for pname, models in sorted(self.PROVIDERS.items()):
                for mname in sorted(models.keys()):
                    if model.lower() in mname.lower():
                        print(f"  {mname} ({pname})")
            return 1
        return 0

    def _test(self, model: str, provider: str, message: str) -> int:
        print(f"Testing {model} via {provider}...")

        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get(
            f"{provider.upper()}_API_KEY"
        )
        if not api_key or "your-key" in api_key:
            print("Error: Set OPENAI_API_KEY (or provider key) in .env first.")
            return 1

        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": message}],
                max_tokens=20,
            )
            reply = resp.choices[0].message.content
            print(f"Response: {reply}")
            return 0
        except Exception as exc:
            print(f"Request failed: {exc}")
            return 1
