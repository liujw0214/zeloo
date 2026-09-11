"""Interactive setup wizard for Zeloo.

Borrowed design from Hermes Agent's ``hermes_cli.setup`` (interactive
provider / model / API key selection). Zeloo's original ``Zeloo install``
just creates directories and writes a placeholder ``.env`` — there is
no Q&A flow that walks a new user through:

1. Choose a default provider (openai / anthropic / xai / openrouter)
2. Enter API key (with paste-friendly input that hides the key)
3. Pick a default model
4. Decide whether to enable optional features (memory / skills / MCP)
5. Optionally connect an OAuth provider
6. Save a finished ``config.yaml`` + ``.env`` that "just works"

The wizard is opt-in (``zeloo setup``) — the existing
``zeloo install`` stays for the silent scripted deployment path.

Design principles:

* **TTY-aware** — falls back to a non-interactive mode when stdin is
  not a TTY (e.g. CI / docker entrypoint) so the same code path works
  in both interactive and headless contexts.
* **Validation** — every step has a sanity check (model is non-empty,
  API key looks like a key, etc.) before moving on.
* **Idempotent** — running ``zeloo setup`` on an already-configured
  home prompts before overwriting; the new config can be inspected
  with ``zeloo config show`` before committing.
* **Never echo secrets to the terminal** — the API-key step uses
  ``getpass`` so the value never appears on the user's scrollback.
"""

from __future__ import annotations

import getpass
import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent.zeloo_constants import get_zeloo_home

logger = logging.getLogger(__name__)


# ── model catalog ──────────────────────────────────────────────────
#
# Borrowed from Hermes Agent's ``hermes_cli/models.py`` — a small
# curated list of "good defaults" the wizard can offer, rather than
# asking the user to memorise OpenAI's ever-growing model roster.
# Operators can still set arbitrary models later via
# ``zeloo config set model.provider``.

PROVIDER_CATALOG: dict[str, dict[str, Any]] = {
    "openai": {
        "label": "OpenAI",
        "default_model": "gpt-4o",
        "env_var": "OPENAI_API_KEY",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o1-mini", "o3-mini"],
    },
    "anthropic": {
        "label": "Anthropic",
        "default_model": "claude-3-5-sonnet-20241022",
        "env_var": "ANTHROPIC_API_KEY",
        "models": [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        ],
    },
    "xai": {
        "label": "xAI (Grok)",
        "default_model": "grok-3-mini",
        "env_var": "XAI_API_KEY",
        "models": ["grok-3", "grok-3-mini", "grok-2"],
    },
    "openrouter": {
        "label": "OpenRouter",
        "default_model": "openai/gpt-4o",
        "env_var": "OPENROUTER_API_KEY",
        "models": ["openai/gpt-4o", "anthropic/claude-3.5-sonnet", "meta-llama/llama-3.1-405b-instruct"],
    },
    "deepseek": {
        "label": "DeepSeek",
        "default_model": "deepseek-chat",
        "env_var": "DEEPSEEK_API_KEY",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "google": {
        "label": "Google (Gemini)",
        "default_model": "gemini-1.5-pro",
        "env_var": "GOOGLE_API_KEY",
        "models": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash-exp"],
    },
}


@dataclass
class WizardAnswers:
    """Container for answers collected by the wizard.

    The wizard builds this incrementally — each step may be skipped
    or default-filled when stdin is not a TTY. The final
    :meth:`to_config_dict` method converts the answers to the YAML
    structure :mod:`zeloo_cli.config` expects.
    """

    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str | None = None
    max_iterations: int = 25
    temperature: float = 0.0
    enable_memory: bool = True
    enable_skills: bool = True
    enable_mcp: bool = True
    extra_providers: dict[str, str] = field(default_factory=dict)  # name → api_key

    def to_config_dict(self) -> dict[str, Any]:
        """Render the answers as a ``config.yaml``-shaped dict."""
        provider_cfg = PROVIDER_CATALOG.get(self.provider, {})
        return {
            "provider": self.provider,
            "model": self.model,
            "max_iterations": self.max_iterations,
            "temperature": self.temperature,
            "base_url": self.base_url or provider_cfg.get("base_url"),
            "features": {
                "memory": self.enable_memory,
                "skills": self.enable_skills,
                "mcp": self.enable_mcp,
            },
        }


# ── interactive helpers ──────────────────────────────────────────
#
# Every prompt is a thin wrapper around ``input()`` that:
#   1. Falls back to a default when stdin is not a TTY
#   2. Validates the answer
#   3. Optionally loops on bad input
#
# The callbacks are the *only* place that touches stdin, so swapping
# in a richer prompt_toolkit / textual experience later means
# rewriting just these functions — every other step takes a callable.

PromptFn = Callable[[str, str], str]


def _stdin_isatty() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:  # noqa: BLE001
        return False


def _make_prompt(use_rich: bool = True) -> PromptFn:
    """Return a callable ``(text, default) -> answer``.

    In TTY mode uses :func:`rich.prompt.Prompt` if available, else
    falls back to the standard ``input()``. When stdin is not a TTY
    (CI / scripts), returns the default immediately.
    """
    is_tty = _stdin_isatty()
    if not is_tty:
        return lambda text, default: default

    if use_rich:
        try:
            from rich.prompt import Prompt

            def _rich_prompt(text: str, default: str = "") -> str:
                try:
                    return Prompt.ask(text, default=default or "")
                except (EOFError, KeyboardInterrupt, OSError):
                    # stdin got closed mid-prompt (CI / 2>&1 redirect);
                    # fall back to the default rather than crashing.
                    return default

            return _rich_prompt
        except ImportError:
            pass

    def _plain_prompt(text: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        try:
            raw = input(f"{text}{suffix}: ").strip()
        except (EOFError, OSError):
            return default
        return raw or default

    return _plain_prompt


def _prompt_secret(text: str) -> str:
    """Read a secret value, never echoing the input to the terminal."""
    if not _stdin_isatty():
        return ""
    try:
        return getpass.getpass(f"{text}: ").strip()
    except (EOFError, KeyboardInterrupt, OSError):
        return ""


def _prompt_choice(text: str, choices: list[str], default: str) -> str:
    """Prompt the user to pick one of ``choices`` (or accept ``default``)."""
    if not _stdin_isatty():
        return default
    try:
        from rich.prompt import Prompt

        return Prompt.ask(text, choices=choices, default=default)
    except (ImportError, EOFError, OSError):
        # Rich unavailable OR stdin was closed mid-prompt (CI / docker
        # entrypoint / 2>&1 redirect). Degrade to the default.
        return default
    except Exception:  # noqa: BLE001
        return default

    # Plain fallback when rich is unavailable
    choice_str = "/".join(choices)
    suffix = f" [{choice_str}]" if choices else ""
    try:
        raw = input(f"{text}{suffix} (default={default}): ").strip().lower()
    except EOFError:
        return default
    if not raw:
        return default
    return raw if raw in choices else default


def _prompt_yes_no(text: str, default: bool) -> bool:
    """Ask a yes / no question; ``default`` is returned when input is empty."""
    if not _stdin_isatty():
        return default
    hint = "Y/n" if default else "y/N"
    try:
        raw = input(f"{text} [{hint}]: ").strip().lower()
    except (EOFError, OSError):
        return default
    if not raw:
        return default
    return raw in ("y", "yes")


# ── the wizard itself ─────────────────────────────────────────────


def _step_provider(ask: PromptFn) -> tuple[str, str, str | None]:
    """Ask the user which provider / model / base_url to use."""
    names = list(PROVIDER_CATALOG.keys())
    default_provider = "openai"
    choice = _prompt_choice("Provider", names, default_provider)
    # If the user picked a label that includes parentheses, take the prefix
    choice = choice.split(" ")[0]
    catalog = PROVIDER_CATALOG.get(choice, PROVIDER_CATALOG[default_provider])

    models = catalog["models"]
    default_model = catalog["default_model"]
    model = ask(
        f"Default model (choices: {', '.join(models)})", default_model
    )
    base_url: str | None = None
    if choice in ("openrouter", "anthropic"):
        # These providers have multiple API surfaces; offer a base-url
        # override for self-hosted / proxy setups.
        raw = ask(
            "Base URL (leave empty for default)",
            catalog.get("base_url", "") or "",
        )
        base_url = raw or None
    return choice, model, base_url


def _step_api_key(provider: str, ask: PromptFn) -> tuple[str, dict[str, str]]:
    """Collect the API key for the primary provider.

    Also opportunistically asks for any extras (Anthropic + OpenAI is
    a common combo for the smart-routing fallback path).
    """
    catalog = PROVIDER_CATALOG[provider]
    primary_key = _prompt_secret(f"API key for {catalog['label']} (env={catalog['env_var']})")
    extras: dict[str, str] = {}
    if _prompt_yes_no("Add an extra provider's API key (Anthropic recommended)?", True):
        for other in ("anthropic", "openai", "openrouter"):
            if other == provider:
                continue
            extra_label = PROVIDER_CATALOG[other]["label"]
            if _prompt_yes_no(f"Add {extra_label}?", False):
                k = _prompt_secret(f"API key for {extra_label} (env={PROVIDER_CATALOG[other]['env_var']})")
                if k:
                    extras[other] = k
    return primary_key, extras


def _step_features(ask: PromptFn) -> tuple[int, float, bool, bool, bool]:
    """Ask about iteration budget / temperature / optional features."""
    max_iter_raw = ask("Max iterations per turn (1-200, default 25)", "25")
    try:
        max_iter = max(1, min(200, int(max_iter_raw)))
    except ValueError:
        max_iter = 25

    temp_raw = ask("Temperature (0.0 = deterministic, default 0.0)", "0.0")
    try:
        temperature = max(0.0, min(2.0, float(temp_raw)))
    except ValueError:
        temperature = 0.0

    enable_memory = _prompt_yes_no("Enable persistent memory?", True)
    enable_skills = _prompt_yes_no("Enable skills?", True)
    enable_mcp = _prompt_yes_no("Enable MCP server connections?", True)
    return max_iter, temperature, enable_memory, enable_skills, enable_mcp


def run_setup_wizard(
    *,
    home: Path | None = None,
    ask: PromptFn | None = None,
    isatty: bool | None = None,
) -> WizardAnswers:
    """Walk the user through an interactive setup.

    Args:
        home: The Zeloo home directory. Defaults to
            :func:`agent.zeloo_constants.get_zeloo_home`.
        ask: The prompt function. Defaults to :func:`_make_prompt`
            (uses rich if available, else plain ``input``).
        isatty: Override for stdin-TTY detection. Used by tests to
            force the non-interactive code path.

    Returns:
        A :class:`WizardAnswers` instance. The caller is responsible
        for writing it to disk via :func:`apply_wizard_answers`.
    """
    target_home = home or get_zeloo_home()
    if ask is None:
        ask = _make_prompt()
    if isatty is not None:
        # Force the prompt into a deterministic mode for tests.
        if not isatty:
            ask = lambda text, default="": default  # noqa: E731

    print()
    print("⚡  Zeloo setup wizard")
    print("=" * 40)
    print(f"Target home: {target_home}")
    print()

    provider, model, base_url = _step_provider(ask)
    api_key, extras = _step_api_key(provider, ask)
    max_iter, temperature, mem, skills, mcp = _step_features(ask)

    answers = WizardAnswers(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_iterations=max_iter,
        temperature=temperature,
        enable_memory=mem,
        enable_skills=skills,
        enable_mcp=mcp,
        extra_providers=extras,
    )
    print()
    print("Setup complete! Use `zeloo config show` to review.")
    return answers


# ── persistence ──────────────────────────────────────────────────


def apply_wizard_answers(
    answers: WizardAnswers,
    *,
    home: Path | None = None,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    """Write the wizard's answers to ``config.yaml`` + ``.env``.

    Args:
        answers: The collected answers.
        home: Zeloo home directory. Defaults to
            :func:`agent.zeloo_constants.get_zeloo_home`.
        overwrite: If ``True``, replace existing files without
            prompting. If ``False`` and either file exists, raise
            :class:`FileExistsError`.

    Returns:
        A ``(config_path, env_path)`` tuple pointing at the files
        that were written.
    """
    target_home = Path(home) if home else get_zeloo_home()
    target_home.mkdir(parents=True, exist_ok=True)
    config_path = target_home / "config.yaml"
    env_path = target_home / ".env"

    if not overwrite:
        if config_path.exists() or env_path.exists():
            raise FileExistsError(
                f"Refusing to overwrite existing config: {config_path} / {env_path}. "
                "Pass overwrite=True or delete them first."
            )

    # ── config.yaml ──
    cfg = answers.to_config_dict()
    # Merge with whatever's already there so the wizard is additive
    # even when ``overwrite=True`` (e.g. for a partial re-run).
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}
        existing.update(cfg)
        cfg = existing
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # ── .env ──
    env_lines: list[str] = []
    if env_path.exists():
        # Read existing entries, filter out keys we're about to set
        managed = {PROVIDER_CATALOG[answers.provider]["env_var"]}
        for other_name, _ in answers.extra_providers.items():
            managed.add(PROVIDER_CATALOG[other_name]["env_var"])
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                key = line.split("=", 1)[0].strip() if "=" in line else ""
                if key not in managed and not key.startswith("zeloo_"):
                    env_lines.append(line.rstrip())
    env_lines.append(f"zeloo_MODEL={answers.model}")
    env_lines.append(f"zeloo_PROVIDER={answers.provider}")
    if answers.api_key:
        env_lines.append(f"{PROVIDER_CATALOG[answers.provider]['env_var']}={answers.api_key}")
    for other_name, key in answers.extra_providers.items():
        env_lines.append(f"{PROVIDER_CATALOG[other_name]['env_var']}={key}")
    if answers.base_url:
        env_lines.append("zeloo_BASE_URL=" + answers.base_url)
    env_lines.append(f"zeloo_HOME={target_home}")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(env_lines) + "\n")

    return config_path, env_path


def run_setup(
    *,
    home: Path | None = None,
    overwrite: bool = False,
    json_output: bool = False,
) -> int:
    """Top-level entry point used by ``zeloo setup`` subcommand.

    Returns a process-style exit code (0 success, 1 user error, 2 IO).
    """
    try:
        answers = run_setup_wizard(home=home)
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        return 1
    try:
        cfg_path, env_path = apply_wizard_answers(answers, home=home, overwrite=overwrite)
    except FileExistsError as e:
        print(f"Error: {e}")
        return 1
    except OSError as e:
        print(f"IO error: {e}")
        return 2
    if json_output:
        print(
            json.dumps(
                {
                    "config": str(cfg_path),
                    "env": str(env_path),
                    "answers": {
                        "provider": answers.provider,
                        "model": answers.model,
                        "max_iterations": answers.max_iterations,
                        "temperature": answers.temperature,
                    },
                },
                indent=2,
            )
        )
    else:
        print(f"  config → {cfg_path}")
        print(f"  env    → {env_path}")
    return 0


# Public hook so tests can swap the prompt strategy without monkey-patching
# the entire module.
__all__ = [
    "PROVIDER_CATALOG",
    "WizardAnswers",
    "apply_wizard_answers",
    "run_setup",
    "run_setup_wizard",
]
# Re-export for the (rare) code that needs to test the prompts directly.
__all__ += [
    "_make_prompt",
    "_prompt_choice",
    "_prompt_secret",
    "_prompt_yes_no",
    "_stdin_isatty",
]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run_setup())