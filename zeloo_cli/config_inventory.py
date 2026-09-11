"""Configuration inventory and validation for Zeloo.

Provides introspection helpers over the default configuration
schema: which keys exist, where each value comes from (default,
.env, file), how two configs differ, and a YAML template that
documents every option for end users.
"""

from __future__ import annotations

from typing import Any

from zeloo_cli.config_defaults import DEFAULT_CONFIG

#: Static metadata table describing each top-level config section.
#: Each entry maps to a human-readable description that is rendered
#: into ``export_config_template`` and ``list_all_configs``.
_SECTION_DESCRIPTIONS: dict[str, str] = {
    "version": "Schema version of this configuration file.",
    "model": "LLM provider, default model, and generation parameters.",
    "voice": "Text-to-speech and speech-to-text backend settings.",
    "terminal": "Shell execution backend, timeouts, and sandbox flag.",
    "approvals": "How Zeloo prompts before executing sensitive actions.",
    "mcp_servers": "MCP server registry (per-server connection settings).",
    "agents": "Agent profile definitions (system prompts, tools, etc.).",
    "skills": "User / workspace skill overrides.",
    "display": "Frontend interface choice (CLI vs TUI) and skin.",
    "logging": "Log level and structured-output format.",
}

#: Field-level descriptions. Used by ``export_config_template`` for
#: inline ``#`` comments. Keep entries short so the rendered YAML
#: stays readable.
_FIELD_DESCRIPTIONS: dict[str, str] = {
    "model.provider": "LLM provider identifier (openai, anthropic, ...).",
    "model.default": "Default model name used by new sessions.",
    "model.temperature": "Sampling temperature in [0.0, 2.0].",
    "model.max_tokens": "Maximum tokens per generation request.",
    "voice.backend": "Voice I/O backend (console, elevenlabs, ...).",
    "voice.tts_model": "Text-to-speech model name.",
    "voice.stt_model": "Speech-to-text model name.",
    "terminal.backend": "Terminal backend (local, docker, ssh, ...).",
    "terminal.timeout": "Per-command timeout in seconds.",
    "terminal.sandbox": "Whether to execute commands in a sandbox.",
    "approvals.mode": "Approval mode (interactive, auto, deny).",
    "approvals.denial_breaker_threshold": "Consecutive denials before escalation.",
    "display.interface": "Frontend interface (cli or tui).",
    "display.skin": "Active TUI skin identifier.",
    "logging.level": "Log level (DEBUG, INFO, WARNING, ERROR).",
    "logging.format": "Log format (text or json).",
}

#: Keys that are considered "well known" by other modules. The
#: ``find_unused_configs`` helper flags any key present in a user
#: config that is not in this set — a useful smoke test for typos.
_KNOWN_KEYS: frozenset[str] = frozenset(
    {
        "version",
        "model.provider",
        "model.default",
        "model.temperature",
        "model.max_tokens",
        "voice.backend",
        "voice.tts_model",
        "voice.stt_model",
        "terminal.backend",
        "terminal.timeout",
        "terminal.sandbox",
        "approvals.mode",
        "approvals.denial_breaker_threshold",
        "display.interface",
        "display.skin",
        "logging.level",
        "logging.format",
    }
)


def _flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict into ``{dotted.path: value}`` entries."""
    out: dict[str, Any] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                out.update(_flatten(value, path))
            else:
                out[path] = value
    return out


def list_all_configs() -> dict[str, dict[str, Any]]:
    """Return metadata for every known config key.

    Shape::

        {
            "model.default": {
                "source": "default",
                "default": "gpt-4o",
                "description": "Default model name used by new sessions.",
            },
            ...
        }
    """
    flat = _flatten(DEFAULT_CONFIG)
    inventory: dict[str, dict[str, Any]] = {}
    for path, value in flat.items():
        inventory[path] = {
            "source": "default",
            "default": value,
            "description": _FIELD_DESCRIPTIONS.get(path, _SECTION_DESCRIPTIONS.get(path.split(".")[0], "")),
        }
    return inventory


def find_unused_configs(config: dict[str, Any]) -> list[str]:
    """Return dotted paths that appear in ``config`` but are unknown.

    The helper recurses through ``config`` and produces a sorted list
    of dotted paths whose leaf is not in :data:`_KNOWN_KEYS`. Section
    containers like ``mcp_servers``, ``agents`` and ``skills`` are
    always considered "known" because their keys are user-defined.
    """
    flat = _flatten(config)
    # Section containers that contain user-defined keys.
    container_keys = {"mcp_servers", "agents", "skills"}

    unknown: list[str] = []
    for path in flat.keys():
        top = path.split(".", 1)[0]
        if top in container_keys:
            continue
        if path not in _KNOWN_KEYS:
            unknown.append(path)
    unknown.sort()
    return unknown


def get_config_diff(config1: dict[str, Any], config2: dict[str, Any]) -> dict[str, Any]:
    """Compute the difference between two config dicts.

    The returned mapping has three keys:

    * ``added``    - paths present in ``config2`` but not ``config1``
    * ``removed``  - paths present in ``config1`` but not ``config2``
    * ``changed``  - paths present in both with different values

    Each entry is a ``{path: value_in_config2}`` mapping (or the
    appropriate side for removed keys).
    """
    flat1 = _flatten(config1)
    flat2 = _flatten(config2)

    keys1 = set(flat1.keys())
    keys2 = set(flat2.keys())

    added = {k: flat2[k] for k in sorted(keys2 - keys1)}
    removed = {k: flat1[k] for k in sorted(keys1 - keys2)}
    changed: dict[str, Any] = {}
    for k in sorted(keys1 & keys2):
        if flat1[k] != flat2[k]:
            changed[k] = {"from": flat1[k], "to": flat2[k]}

    return {"added": added, "removed": removed, "changed": changed}


def export_config_template() -> str:
    """Return a YAML-formatted configuration template with inline comments.

    The template documents every known default so users can copy
    it into their ``config.yaml`` and edit only the values they care
    about.
    """
    lines: list[str] = [
        "# Zeloo configuration template",
        "# Generated from the active schema; do not edit this file in place.",
        "",
    ]

    for section, value in DEFAULT_CONFIG.items():
        desc = _SECTION_DESCRIPTIONS.get(section, "")
        if desc:
            lines.append(f"# {section}: {desc}")
        else:
            lines.append(f"# {section}")
        if isinstance(value, dict):
            _render_section(value, section, lines, indent=0)
        else:
            lines.append(f"{section}: {_yaml_scalar(value)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_section(
    section: dict[str, Any],
    prefix: str,
    lines: list[str],
    indent: int,
) -> None:
    """Append indented ``key: value`` lines for ``section`` to ``lines``."""
    pad = "  " * indent
    for key, value in section.items():
        path = f"{prefix}.{key}"
        comment = _FIELD_DESCRIPTIONS.get(path)
        comment_suffix = f"  # {comment}" if comment else ""
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:{comment_suffix}")
            _render_section(value, path, lines, indent + 1)
        else:
            lines.append(f"{pad}{key}: {_yaml_scalar(value)}{comment_suffix}")


def _yaml_scalar(value: Any) -> str:
    """Render a Python scalar as a YAML literal suitable for a template."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    # Strings: prefer double-quoted form only when needed.
    text = str(value)
    needs_quote = any(ch in text for ch in (":", "#", "\n", '"', "'"))
    if needs_quote:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


__all__ = [
    "export_config_template",
    "find_unused_configs",
    "get_config_diff",
    "list_all_configs",
]
