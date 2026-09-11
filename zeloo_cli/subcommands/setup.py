"""``zeloo setup`` subcommand — Hermes-style setup wizard container.

This module exposes :func:`cmd_setup` which is wired into ``main.py`` as
the handler for the ``setup`` subcommand. It supports all the Hermes-style
options:

* ``section [model|tts|terminal|gateway|tools|telemetry|agent]``
  Run a specific section instead of the full wizard.
* ``--non-interactive`` Use defaults / env vars, never prompt.
* ``--reset`` Reset configuration to defaults.
* ``--reconfigure`` Re-run the full wizard showing current values.
* ``--quick`` Only prompt for items that are missing or unset.
* ``--portal`` One-shot OAuth provider setup.

Each section has its own handler that knows about the relevant
subsystems (voice backends, terminal backends, toolsets, telemetry).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from agent.zeloo_constants import get_zeloo_home
from zeloo_cli.setup_wizard import (
    PROVIDER_CATALOG,
    WizardAnswers,
    apply_wizard_answers,
    run_setup_wizard,
)

logger = logging.getLogger(__name__)

SECTIONS = ["model", "tts", "terminal", "gateway", "tools", "telemetry", "agent"]

VOICE_BACKENDS = ["console", "openai", "elevenlabs"]
TERMINAL_BACKENDS = ["local", "docker", "ssh", "modal", "daytona", "singularity", "vercel_sandbox"]


# ── helpers ───────────────────────────────────────────────────────


def _load_existing_config(home: Path) -> dict[str, Any]:
    cfg_path = home / "config.yaml"
    if not cfg_path.exists():
        return {}
    try:
        import yaml

        with open(cfg_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _merge_yaml(home: Path, key_path: str, value: Any) -> None:
    """Deep-set ``key_path`` (dot-notation) in ``home/config.yaml``.

    Creates the file if missing. Existing nested dicts are preserved.
    """
    import yaml

    cfg_path = home / "config.yaml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = _load_existing_config(home)
    parts = key_path.split(".")
    cursor: dict[str, Any] = cfg
    for part in parts[:-1]:
        if part not in cursor or not isinstance(cursor[part], dict):
            cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = value
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _is_missing_or_unset(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _prompt_choice_or_default(
    text: str, choices: list[str], default: str, non_interactive: bool
) -> str:
    if non_interactive or not _stdin_isatty():
        return default
    try:
        from rich.prompt import Prompt

        return Prompt.ask(text, choices=choices, default=default)
    except Exception:
        try:
            raw = input(f"{text} ({'/'.join(choices)}) [{default}]: ").strip().lower()
        except (EOFError, OSError):
            return default
        return raw if raw in choices else default


def _stdin_isatty() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _voice_config(existing: dict[str, Any]) -> dict[str, Any]:
    """Return the configured voice section, or an empty mapping."""
    value = existing.get("voice", {})
    return value if isinstance(value, dict) else {}


def _terminal_config(existing: dict[str, Any]) -> dict[str, Any]:
    """Return the configured terminal section, or an empty mapping."""
    value = existing.get("terminal", {})
    return value if isinstance(value, dict) else {}


def _build_voice_backend(existing: dict[str, Any]) -> tuple[str, Any]:
    """Build the configured voice backend without performing a network call."""
    from gateway.voice import get_voice_backend

    voice_cfg = _voice_config(existing)
    name = str(voice_cfg.get("backend", "console")).lower()
    if name not in VOICE_BACKENDS:
        name = "console"

    kwargs: dict[str, Any] = {}
    if name == "openai":
        kwargs["api_key"] = voice_cfg.get("api_key") or os.environ.get("OPENAI_API_KEY", "")
        if voice_cfg.get("model"):
            kwargs["tts_model"] = voice_cfg["model"]
        if voice_cfg.get("voice"):
            kwargs["tts_voice"] = voice_cfg["voice"]
        if voice_cfg.get("stt_model"):
            kwargs["stt_model"] = voice_cfg["stt_model"]
        if voice_cfg.get("base_url"):
            kwargs["base_url"] = voice_cfg["base_url"]
    elif name == "elevenlabs":
        kwargs["api_key"] = voice_cfg.get("api_key") or os.environ.get("ELEVENLABS_API_KEY", "")
        if voice_cfg.get("voice_id"):
            kwargs["voice_id"] = voice_cfg["voice_id"]
        if voice_cfg.get("model_id"):
            kwargs["model_id"] = voice_cfg["model_id"]
        if voice_cfg.get("stt_model"):
            kwargs["stt_model"] = voice_cfg["stt_model"]

    return name, get_voice_backend(name, **kwargs)


def is_voice_backend_available(backend: Any) -> bool:
    """Return whether a voice backend is ready for use."""
    check = getattr(backend, "is_available", None)
    if not callable(check):
        return True
    try:
        return bool(check())
    except Exception:
        return False


def _voice_availability_message(backend: Any) -> tuple[bool, str]:
    """Probe a voice backend and return its user-facing availability status."""
    available = is_voice_backend_available(backend)
    return (True, "available") if available else (False, "not available")


def _test_voice_backend(backend: Any) -> tuple[bool, str]:
    """Generate one short TTS sample and return its result."""
    with tempfile.TemporaryDirectory(prefix="zeloo-tts-") as directory:
        output_path = str(Path(directory) / "voice-test.mp3")
        try:
            result = backend.tts("Zeloo voice test.", output_path)
        except Exception as exc:
            return False, str(exc)
        if not result or not Path(output_path).exists():
            return False, "TTS returned without an output file"
        return True, result


def _docker_daemon_status(timeout: float = 10.0) -> tuple[bool, str]:
    """Check whether the local Docker CLI can reach a daemon."""
    docker = shutil.which("docker")
    if docker is None:
        return False, "docker executable not found in PATH"
    try:
        result = subprocess.run(
            [docker, "info"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, "Docker daemon reachable"
    detail = (result.stderr or result.stdout).strip()
    return False, detail or f"docker info exited with {result.returncode}"


def _test_terminal_backend(terminal_cfg: dict[str, Any]) -> tuple[bool, str]:
    """Probe the configured terminal backend without changing its state."""
    backend_name = str(terminal_cfg.get("backend", "local")).lower()
    if backend_name not in TERMINAL_BACKENDS:
        return False, f"unknown backend {backend_name!r}"
    if backend_name == "local":
        try:
            from terminal.local import LocalTerminalBackend

            backend = LocalTerminalBackend(cwd=terminal_cfg.get("cwd"))
            result = backend.execute(
                f'"{sys.executable}" -c "print(\'zeloo-terminal-ok\')"',
                timeout=min(15, int(terminal_cfg.get("timeout", 30))),
            )
            return (True, result.stdout.strip()) if result.success else (False, result.stderr.strip())
        except Exception as exc:
            return False, str(exc)
    if backend_name == "docker":
        return _docker_daemon_status()
    if backend_name == "ssh":
        host = str(terminal_cfg.get("host", "")).strip()
        if not host:
            return False, "SSH host is not configured"
        if importlib.util.find_spec("paramiko") is None:
            return False, "paramiko is not installed"
        key_path = terminal_cfg.get("key_path") or os.environ.get("SSH_KEY_FILE")
        if key_path:
            key_path = Path(str(key_path)).expanduser()
            if not key_path.is_file():
                return False, f"SSH private key not found: {key_path}"
        try:
            from terminal.ssh import SSHTerminalBackend

            backend = SSHTerminalBackend(
                host=host,
                port=int(terminal_cfg.get("port", 22)),
                username=str(terminal_cfg.get("user", "")),
                password=os.environ.get("SSH_PASSWORD", ""),
                key_path=key_path,
            )
            try:
                result = backend.execute("true", timeout=min(15, int(terminal_cfg.get("timeout", 30))))
                return (True, "SSH connection reachable") if result.success else (False, result.stderr.strip())
            finally:
                backend.close()
        except Exception as exc:
            return False, str(exc)
    if backend_name == "modal":
        if importlib.util.find_spec("modal") is None:
            return False, "modal SDK is not installed"
        return True, "modal SDK available"
    if backend_name == "daytona":
        if importlib.util.find_spec("daytona") is None:
            return False, "daytona SDK is not installed"
        if not os.environ.get("DAYTONA_API_KEY"):
            return False, "DAYTONA_API_KEY is not configured"
        return True, "Daytona SDK and credentials available"
    if backend_name == "vercel_sandbox":
        if not os.environ.get("VERCEL_DEPLOYMENT_URL"):
            return False, "VERCEL_DEPLOYMENT_URL is not configured"
        return True, "Vercel sandbox configuration available"
    if backend_name == "singularity":
        command = shutil.which("apptainer") or shutil.which("singularity")
        if command is None:
            return False, "singularity/apptainer executable not found"
        if not terminal_cfg.get("image"):
            return False, "Singularity image is not configured"
        return True, f"{Path(command).name} available"
    return False, f"unsupported terminal backend {backend_name!r}"


# ── section handlers ───────────────────────────────────────────────


def cmd_setup_model(
    home: Path,
    *,
    answers: WizardAnswers | None = None,
    non_interactive: bool = False,
) -> int:
    """``zeloo setup model`` — pick provider / model / API key."""
    if answers is None:
        answers = WizardAnswers()

    existing = _load_existing_config(home)
    env = os.environ

    existing_provider = existing.get("provider", "openai")
    existing_model = existing.get("model", "gpt-4o")
    existing_key_env = PROVIDER_CATALOG.get(existing_provider, {}).get("env_var", "")
    existing_api_key = env.get(existing_key_env, "")

    if non_interactive:
        answers.provider = existing_provider
        answers.model = existing_model
        answers.api_key = existing_api_key
    else:
        from zeloo_cli.setup_wizard import _make_prompt, _step_api_key, _step_provider

        ask = _make_prompt()
        provider, model, base_url = _step_provider(ask)
        answers.provider = provider
        answers.model = model
        answers.base_url = base_url
        primary_key, extras = _step_api_key(provider, ask)
        if primary_key:
            answers.api_key = primary_key
        answers.extra_providers.update(extras)

    try:
        cfg_path, env_path = apply_wizard_answers(
            answers, home=home, overwrite=True
        )
        print(f"  config → {cfg_path}")
        print(f"  env    → {env_path}")
        return 0
    except FileExistsError as exc:
        print(f"Error: {exc}")
        return 1


def cmd_setup_tts(
    home: Path,
    *,
    non_interactive: bool = False,
    test: bool = False,
) -> int:
    """``zeloo setup tts`` — pick voice backend or test the current one."""
    if test:
        return cmd_setup_tts_test(home, non_interactive=non_interactive)

    existing = _load_existing_config(home)
    voice_cfg = _voice_config(existing)
    current = str(voice_cfg.get("backend", "console"))

    backend = _prompt_choice_or_default(
        "Voice backend",
        VOICE_BACKENDS,
        current if current in VOICE_BACKENDS else "console",
        non_interactive=non_interactive,
    )

    cfg: dict[str, Any] = {"backend": backend}

    if backend == "openai":
        cfg["model"] = (
            str(voice_cfg.get("model", "tts-1"))
            if non_interactive
            else _ask_str("OpenAI TTS model", "tts-1", non_interactive)
        )
        cfg["voice"] = (
            str(voice_cfg.get("voice", "alloy"))
            if non_interactive
            else _ask_str(
                "Voice (alloy/echo/fable/onyx/nova/shimmer)",
                "alloy",
                non_interactive,
            )
        )
        if voice_cfg.get("stt_model"):
            cfg["stt_model"] = voice_cfg["stt_model"]
        if voice_cfg.get("base_url"):
            cfg["base_url"] = voice_cfg["base_url"]
    elif backend == "elevenlabs":
        cfg["voice_id"] = (
            str(voice_cfg.get("voice_id", ""))
            if non_interactive
            else _ask_str(
                "ElevenLabs voice name or ID (blank defaults to Rachel)",
                "",
                non_interactive,
            )
        )
        cfg["model_id"] = (
            str(voice_cfg.get("model_id", "eleven_multilingual_v2"))
            if non_interactive
            else _ask_str(
                "ElevenLabs model_id",
                "eleven_multilingual_v2",
                non_interactive,
            )
        )

    _merge_yaml(home, "voice", cfg)
    print(f"  voice backend set to {backend}")
    return 0


def cmd_setup_tts_test(home: Path, *, non_interactive: bool = False) -> int:
    """Check the configured voice backend and generate one short TTS sample."""
    existing = _load_existing_config(home)
    backend_name, backend = _build_voice_backend(existing)
    print(f"Testing voice backend {backend_name}...")
    available, message = _voice_availability_message(backend)
    if not available:
        print(f"  unavailable: {message}")
        return 1

    ok, detail = _test_voice_backend(backend)
    if not ok:
        print(f"  failed: {detail}")
        return 1
    print(f"  TTS sample generated: {detail}")
    return 0


def cmd_setup_terminal(
    home: Path,
    *,
    non_interactive: bool = False,
    test: bool = False,
) -> int:
    """``zeloo setup terminal`` — pick terminal backend or test it."""
    if test:
        return cmd_setup_terminal_test(home, non_interactive=non_interactive)

    existing = _load_existing_config(home)
    terminal_cfg = _terminal_config(existing)
    current = str(terminal_cfg.get("backend", "local"))

    backend = _prompt_choice_or_default(
        "Terminal backend",
        TERMINAL_BACKENDS,
        current if current in TERMINAL_BACKENDS else "local",
        non_interactive=non_interactive,
    )

    cfg: dict[str, Any] = {
        "backend": backend,
        "timeout": int(terminal_cfg.get("timeout", terminal_cfg.get("default_timeout", 30))),
        "sandbox": bool(terminal_cfg.get("sandbox", False)),
    }

    if backend in ("docker", "modal", "daytona", "vercel_sandbox", "singularity"):
        cfg["image"] = terminal_cfg.get("image", "python:3.12-slim")
        cfg["sandbox"] = bool(terminal_cfg.get("sandbox", True))
    elif backend == "ssh":
        cfg["host"] = terminal_cfg.get("host", "")
        cfg["port"] = int(terminal_cfg.get("port", 22))
        cfg["user"] = terminal_cfg.get("user", os.environ.get("USER", ""))
        key_path = terminal_cfg.get("key_path") or os.environ.get("SSH_KEY_FILE")
        if key_path:
            cfg["key_path"] = str(Path(str(key_path)).expanduser())
    elif backend == "local":
        cfg["cwd"] = terminal_cfg.get("cwd", str(Path.cwd()))

    _merge_yaml(home, "terminal", cfg)
    print(f"  terminal backend set to {backend}")
    return 0


def cmd_setup_terminal_test(home: Path, *, non_interactive: bool = False) -> int:
    """Probe the configured terminal backend without changing it."""
    del non_interactive
    terminal_cfg = _terminal_config(_load_existing_config(home))
    backend_name = str(terminal_cfg.get("backend", "local"))
    print(f"Testing terminal backend {backend_name}...")
    ok, detail = _test_terminal_backend(terminal_cfg)
    if not ok:
        print(f"  failed: {detail}")
        return 1
    print(f"  reachable: {detail}")
    return 0


def cmd_setup_gateway(home: Path, *, non_interactive: bool = False) -> int:
    """``zeloo setup gateway`` — gateway port + auth."""
    from gateway.api_server import DEFAULT_PORT as _API_PORT

    existing = _load_existing_config(home)
    current_port = existing.get("gateway", {}).get("api", {}).get("port", _API_PORT)

    if non_interactive:
        port = current_port
    else:
        port_str = _ask_str(f"Gateway port [{_API_PORT}]", str(_API_PORT), non_interactive)
        try:
            port = int(port_str)
        except ValueError:
            port = _API_PORT

    api_key = os.environ.get("ZELOO_API_KEY", "")
    if not api_key and not non_interactive:
        try:
            import getpass

            api_key = getpass.getpass("API key (leave empty to disable auth): ").strip()
        except (EOFError, OSError):
            api_key = ""

    cfg: dict[str, Any] = {"api": {"port": port}}
    if api_key:
        cfg["api"]["auth_token"] = api_key

    _merge_yaml(home, "gateway", cfg)
    print(f"  gateway port set to {port}")
    if api_key:
        print("  auth: enabled (token written to config)")
    else:
        print("  auth: disabled (open access)")
    return 0


def cmd_setup_tools(home: Path, *, non_interactive: bool = False) -> int:
    """``zeloo setup tools`` — enable/disable toolsets."""
    from toolsets import zeloo_CORE_TOOLS

    existing = _load_existing_config(home)
    current_toolsets = existing.get("toolsets", list(zeloo_CORE_TOOLS.keys())[:6])

    if non_interactive:
        toolsets = current_toolsets
    else:
        print("Available toolsets:")
        for ts in zeloo_CORE_TOOLS:
            print(f"  - {ts}: {len(zeloo_CORE_TOOLS[ts])} tools")
        print()
        try:
            raw = input(
                "Comma-separated toolset names (default: "
                + ",".join(current_toolsets)
                + "): "
            ).strip()
        except (EOFError, OSError):
            raw = ""
        if not raw:
            toolsets = current_toolsets
        else:
            toolsets = [t.strip() for t in raw.split(",") if t.strip()]

    unknown = [t for t in toolsets if t not in zeloo_CORE_TOOLS]
    if unknown:
        print(f"Warning: unknown toolsets ignored: {unknown}")
        toolsets = [t for t in toolsets if t in zeloo_CORE_TOOLS]

    _merge_yaml(home, "toolsets", toolsets)
    print(f"  enabled toolsets: {', '.join(toolsets)}")
    return 0


def cmd_setup_telemetry(home: Path, *, non_interactive: bool = False) -> int:
    """``zeloo setup telemetry`` — observability config."""
    existing = _load_existing_config(home)
    current = existing.get("observability", {})

    cfg: dict[str, Any] = {
        "enabled": current.get("enabled", True),
        "langfuse": current.get("langfuse", {"enabled": False}),
        "usage_tracking": current.get("usage_tracking", {"enabled": True}),
    }

    if not non_interactive:
        cfg["enabled"] = _prompt_yes_no(
            "Enable observability?", cfg["enabled"], non_interactive
        )
        if cfg["enabled"]:
            cfg["usage_tracking"]["enabled"] = _prompt_yes_no(
                "Track token usage & costs?", cfg["usage_tracking"]["enabled"], non_interactive
            )
            cfg["langfuse"]["enabled"] = _prompt_yes_no(
                "Enable Langfuse tracing?", cfg["langfuse"].get("enabled", False), non_interactive
            )
            if cfg["langfuse"]["enabled"]:
                cfg["langfuse"]["public_key"] = _ask_str(
                    "Langfuse public key", "", non_interactive
                )
                cfg["langfuse"]["secret_key"] = _ask_str(
                    "Langfuse secret key", "", non_interactive
                )
                cfg["langfuse"]["host"] = _ask_str(
                    "Langfuse host", "https://cloud.langfuse.com", non_interactive
                )

    _merge_yaml(home, "observability", cfg)
    print(f"  observability enabled: {cfg['enabled']}")
    if cfg["enabled"]:
        print(f"  usage_tracking: {cfg['usage_tracking']['enabled']}")
        print(f"  langfuse: {cfg['langfuse']['enabled']}")
    return 0


def cmd_setup_agent(home: Path, *, non_interactive: bool = False) -> int:
    """``zeloo setup agent`` — agent-level defaults."""
    existing = _load_existing_config(home)
    cfg: dict[str, Any] = {
        "max_iterations": existing.get("max_iterations", 25),
        "temperature": existing.get("temperature", 0.0),
        "streaming": existing.get("streaming", True),
        "pass_session_id": existing.get("pass_session_id", False),
        "checkpoints": existing.get("checkpoints", False),
    }

    if not non_interactive:
        max_str = _ask_str("Max iterations per turn (1-200)", str(cfg["max_iterations"]), non_interactive)
        try:
            cfg["max_iterations"] = max(1, min(200, int(max_str)))
        except ValueError:
            pass

        temp_str = _ask_str("Temperature (0.0-2.0)", str(cfg["temperature"]), non_interactive)
        try:
            cfg["temperature"] = max(0.0, min(2.0, float(temp_str)))
        except ValueError:
            pass

        cfg["streaming"] = _prompt_yes_no("Stream responses?", cfg["streaming"], non_interactive)
        cfg["pass_session_id"] = _prompt_yes_no(
            "Pass session_id to model?", cfg["pass_session_id"], non_interactive
        )
        cfg["checkpoints"] = _prompt_yes_no(
            "Enable filesystem checkpoints?", cfg["checkpoints"], non_interactive
        )

    for key, value in cfg.items():
        _merge_yaml(home, key, value)
    print(f"  max_iterations: {cfg['max_iterations']}")
    print(f"  temperature: {cfg['temperature']}")
    print(f"  streaming: {cfg['streaming']}")
    return 0


# ── helpers for prompts ────────────────────────────────────────────


def _ask_str(text: str, default: str, non_interactive: bool) -> str:
    if non_interactive or not _stdin_isatty():
        return default
    try:
        raw = input(f"{text} [{default}]: ").strip()
    except (EOFError, OSError):
        return default
    return raw or default


def _prompt_yes_no(text: str, default: bool, non_interactive: bool) -> bool:
    if non_interactive or not _stdin_isatty():
        return default
    hint = "Y/n" if default else "y/N"
    try:
        raw = input(f"{text} [{hint}]: ").strip().lower()
    except (EOFError, OSError):
        return default
    if not raw:
        return default
    return raw in ("y", "yes")


# ── section registry ───────────────────────────────────────────────


_SECTION_HANDLERS = {
    "model": cmd_setup_model,
    "tts": cmd_setup_tts,
    "terminal": cmd_setup_terminal,
    "gateway": cmd_setup_gateway,
    "tools": cmd_setup_tools,
    "telemetry": cmd_setup_telemetry,
    "agent": cmd_setup_agent,
}


# ── portal flow ────────────────────────────────────────────────────


def cmd_setup_portal(home: Path, *, non_interactive: bool = False) -> int:
    """``zeloo setup --portal`` — one-shot OAuth provider setup.

    Zeloo doesn't ship a native OAuth provider — it delegates to
    existing providers (OpenAI / Anthropic / Google). This flow:
    1. Prompts for the provider
    2. Prompts for the API key (via getpass)
    3. Writes a complete config that "just works" with the chosen provider
    """
    print("Zeloo Portal setup")
    print("=" * 40)
    print("Zeloo doesn't ship a native portal — pick a provider to start.")
    print()

    provider = _prompt_choice_or_default(
        "Provider",
        list(PROVIDER_CATALOG.keys()),
        "openai",
        non_interactive=non_interactive,
    )
    catalog = PROVIDER_CATALOG.get(provider, PROVIDER_CATALOG["openai"])
    answers = WizardAnswers(provider=provider, model=catalog["default_model"])

    if not non_interactive:
        try:
            import getpass

            key = getpass.getpass(f"API key for {catalog['label']} (env={catalog['env_var']}): ").strip()
            if key:
                answers.api_key = key
        except (EOFError, OSError):
            pass

    try:
        cfg_path, env_path = apply_wizard_answers(
            answers, home=home, overwrite=True
        )
        print(f"  config → {cfg_path}")
        print(f"  env    → {env_path}")
        return 0
    except FileExistsError as exc:
        print(f"Error: {exc}")
        return 1


# ── top-level dispatcher ───────────────────────────────────────────


def cmd_setup(args: argparse.Namespace) -> int:
    """Hermes-style ``setup`` subcommand dispatcher."""
    home = (
        Path(args.home) if getattr(args, "home", None) else get_zeloo_home()
    )
    non_interactive = bool(getattr(args, "non_interactive", False))
    reset = bool(getattr(args, "reset", False))
    reconfigure = bool(getattr(args, "reconfigure", False))
    quick = bool(getattr(args, "quick", False))
    portal = bool(getattr(args, "portal", False))
    json_output = bool(getattr(args, "json", False))
    overwrite = bool(getattr(args, "overwrite", False))
    section = getattr(args, "section", None)
    action = getattr(args, "action", None)
    if action and section not in ("tts", "terminal"):
        print("Only tts/terminal sections support the test action.")
        return 1
    should_test = bool(getattr(args, "test", False) or action == "test")
    if getattr(args, "test", False) and section not in ("tts", "terminal"):
        print("Only tts/terminal sections support --test.")
        return 1

    if reset and home.exists():
        for f in (home / "config.yaml", home / ".env"):
            if f.exists():
                f.unlink()
        print(f"Reset configuration in {home}")

    if portal:
        code = cmd_setup_portal(home, non_interactive=non_interactive)
        return code

    if section:
        handler = _SECTION_HANDLERS.get(section)
        if handler is None:
            print(f"Unknown section: {section}")
            print(f"Valid sections: {', '.join(SECTIONS)}")
            return 1
        handler_kwargs: dict[str, bool] = {"non_interactive": non_interactive}
        if should_test and section in ("tts", "terminal"):
            handler_kwargs["test"] = True
        return handler(home, **handler_kwargs)

    if quick:
        existing = _load_existing_config(home)
        env = os.environ
        needs_provider = _is_missing_or_unset(existing.get("provider"))
        needs_model = _is_missing_or_unset(existing.get("model"))
        needs_key = all(
            _is_missing_or_unset(
                env.get(PROVIDER_CATALOG.get(p, {}).get("env_var", ""))
            )
            for p in PROVIDER_CATALOG
        )

        if needs_provider or needs_model or needs_key:
            print("Quick setup: filling missing items.")
            try:
                answers = run_setup_wizard(home=home)
            except KeyboardInterrupt:
                print("\nSetup cancelled.")
                return 1
        else:
            print("Quick setup: nothing missing.")
            return 0

        try:
            cfg_path, env_path = apply_wizard_answers(
                answers, home=home, overwrite=True
            )
            if json_output:
                print(
                    json.dumps(
                        {
                            "config": str(cfg_path),
                            "env": str(env_path),
                            "mode": "quick",
                        },
                        indent=2,
                    )
                )
            else:
                print(f"  config → {cfg_path}")
                print(f"  env    → {env_path}")
            return 0
        except FileExistsError as exc:
            print(f"Error: {exc}")
            return 1

    if non_interactive:
        try:
            answers = WizardAnswers()
            cfg_path, env_path = apply_wizard_answers(
                answers, home=home, overwrite=True
            )
            if json_output:
                print(
                    json.dumps(
                        {
                            "config": str(cfg_path),
                            "env": str(env_path),
                            "mode": "non-interactive",
                        },
                        indent=2,
                    )
                )
            return 0
        except Exception as exc:
            print(f"Error: {exc}")
            return 1

    try:
        answers = run_setup_wizard(home=home)
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        return 1

    try:
        cfg_path, env_path = apply_wizard_answers(
            answers,
            home=home,
            overwrite=overwrite or reconfigure,
        )
    except FileExistsError as exc:
        print(f"Error: {exc}")
        return 1
    except OSError as exc:
        print(f"IO error: {exc}")
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


def build_setup_parser(subparsers: Any, *, cmd_setup_handler: Any) -> None:
    """Attach the Hermes-style ``setup`` subparser."""
    setup_parser = subparsers.add_parser(
        "setup",
        help="Interactive setup wizard (provider / model / API key)",
        description="Configure Zeloo with an interactive wizard. "
        "Run a specific section: "
        "zeloo setup model|tts|terminal|gateway|tools|telemetry|agent",
    )
    setup_parser.add_argument(
        "section",
        nargs="?",
        choices=SECTIONS,
        default=None,
        help="Run a specific setup section instead of the full wizard",
    )
    setup_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Non-interactive mode (use defaults / env vars)",
    )
    setup_parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset configuration to defaults before running",
    )
    setup_parser.add_argument(
        "--reconfigure",
        action="store_true",
        help="Re-run the full wizard (existing files are overwritten)",
    )
    setup_parser.add_argument(
        "--quick",
        action="store_true",
        help="Only prompt for items that are missing or unset",
    )
    setup_parser.add_argument(
        "--portal",
        action="store_true",
        help="One-shot OAuth provider setup",
    )
    setup_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing config.yaml / .env without prompting",
    )
    setup_parser.add_argument(
        "action",
        nargs="?",
        choices=["test"],
        default=None,
        help="Optional section action; currently supports 'test' for TTS/terminal",
    )
    setup_parser.add_argument(
        "--test",
        action="store_true",
        help="Test the selected section (TTS generates a short sample; terminal probes connectivity)",
    )
    setup_parser.add_argument(
        "--json",
        action="store_true",
        help="Output a JSON summary",
    )
    setup_parser.add_argument(
        "--home",
        default=None,
        help="Target Zeloo home directory (default: ~/.Zeloo)",
    )
    setup_parser.set_defaults(func=cmd_setup_handler)