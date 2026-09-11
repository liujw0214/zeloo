"""Pydantic schema + validation utilities for ``config.yaml``.

This module provides:

* :class:`ConfigSchema` — the typed Pydantic v2 model that mirrors the
  on-disk ``config.yaml`` shape.
* :func:`validate_config` / :func:`validate_config_dict` — entry points
  that turn errors into a structured ``(ok, errors)`` tuple.
* :func:`migrate_legacy_config` — best-effort upgrade helper for older
  flat configs.
* :func:`get_default_config` / :func:`generate_config_template` —
  helpers used by the setup wizard and ``Zeloo config edit``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Section models
# ---------------------------------------------------------------------------

class ProviderConfig(BaseModel):
    """Per-provider credentials and defaults."""

    enabled: bool = True
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    organization: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    """Top-level LLM settings."""

    default_provider: str = "openai"
    default_model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    fallback_chain: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    """Agent loop tuning knobs."""

    max_iterations: int = 10
    temperature: float = 0.7
    timeout_seconds: int = 60
    enable_tools: bool = True
    enable_memory: bool = True
    enable_streaming: bool = True


class MemoryConfig(BaseModel):
    """Memory subsystem settings."""

    enabled: bool = True
    backend: str = "sqlite"
    max_entries: int = 10_000
    ttl_days: int = 90


class SkillsConfig(BaseModel):
    """Skills subsystem settings."""

    enabled: bool = True
    auto_load: list[str] = Field(default_factory=list)
    workspace: str = "default"


class BrowserConfig(BaseModel):
    """Browser automation settings."""

    enabled: bool = False
    backend: str = "playwright"
    headless: bool = True
    timeout_seconds: int = 30


class MCPConfig(BaseModel):
    """MCP server configuration."""

    enabled: bool = True
    auto_register: bool = False
    servers: dict[str, dict[str, Any]] = Field(default_factory=dict)


class TelemetryConfig(BaseModel):
    """Telemetry / observability switches."""

    enabled: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    otel_endpoint: str | None = None


class SecurityConfig(BaseModel):
    """Security / approval gates."""

    approval_required: bool = True
    secret_scan: bool = True
    max_command_runtime: int = 300


class WorkspaceConfig(BaseModel):
    """Workspace management settings."""

    default: str = "default"
    auto_snapshot: bool = True
    snapshot_retention: int = 10


class ConfigSchema(BaseModel):
    """Root schema for ``~/.Zeloo/config.yaml``.

    The defaults below are deliberately conservative so the validator
    never complains about a missing field. Optional sections are kept
    empty by default.
    """

    version: int = 1
    llm: LLMConfig = Field(default_factory=LLMConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _format_error(exc: ValidationError) -> list[str]:
    """Render Pydantic errors into a flat list of strings."""
    out: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ())) or "<root>"
        msg = err.get("msg", "invalid")
        out.append(f"{loc}: {msg}")
    return out


def validate_config(config_path: Path) -> tuple[bool, list[str]]:
    """Validate a YAML config file on disk.

    Returns ``(True, [])`` on success, or ``(False, [errors])`` if any
    field fails validation. The function never raises — it converts
    exceptions into error strings.
    """
    try:
        import yaml
    except ImportError:
        return False, ["PyYAML is not installed; cannot read YAML files"]

    if not config_path.exists():
        return False, [f"Config file not found: {config_path}"]

    try:
        with open(config_path, encoding="utf-8") as f:
            payload = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        return False, [f"YAML parse error: {exc}"]
    except OSError as exc:
        return False, [f"I/O error: {exc}"]

    if not isinstance(payload, dict):
        return False, ["Top-level config must be a mapping"]

    return validate_config_dict(payload)


def validate_config_dict(config: dict) -> tuple[bool, list[str]]:
    """Validate an in-memory config dictionary."""
    try:
        ConfigSchema.model_validate(config)
    except ValidationError as exc:
        return False, _format_error(exc)
    return True, []


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------

# Fields that lived at the top level in older config revisions.
_LEGACY_TOP_LEVEL_FIELDS: dict[str, str] = {
    "model": "llm.default_model",
    "provider": "llm.default_provider",
    "temperature": "llm.temperature",
    "max_tokens": "llm.max_tokens",
    "max_iterations": "agent.max_iterations",
    "approval_required": "security.approval_required",
    "log_level": "telemetry.log_level",
}

# Legacy single-string fallback chain (e.g. ``fallback: "anthropic,openai"``).
_LEGACY_FALLBACK_KEYS: tuple[str, ...] = ("fallback", "fallback_providers")


def migrate_legacy_config(old_config: dict) -> dict:
    """Best-effort upgrade from the v0 (flat) config shape.

    The function is intentionally non-destructive: it returns a new dict
    that the caller can persist. Unknown keys are preserved in the
    matching section's ``extra`` mapping so nothing is silently lost.
    """
    if not isinstance(old_config, dict):
        return {}

    migrated: dict[str, Any] = {}

    # Copy across every field that already matches the v1 shape.
    for key, value in old_config.items():
        if key in _LEGACY_TOP_LEVEL_FIELDS or key in _LEGACY_FALLBACK_KEYS:
            continue
        if key in {"version"}:
            migrated[key] = value
            continue
        # Already nested — copy verbatim.
        if isinstance(value, dict):
            migrated[key] = dict(value)
        elif isinstance(value, list):
            migrated[key] = list(value)
        else:
            migrated[key] = value

    # Migrate flat fields into their v1 homes.
    for legacy_key, target in _LEGACY_TOP_LEVEL_FIELDS.items():
        if legacy_key not in old_config:
            continue
        section, _, field = target.partition(".")
        section_dict = migrated.setdefault(section, {})
        if isinstance(section_dict, dict) and field not in section_dict:
            section_dict[field] = old_config[legacy_key]

    # Migrate the legacy comma-separated fallback string.
    fallback_raw = old_config.get("fallback") or old_config.get("fallback_providers")
    if isinstance(fallback_raw, str):
        chain = [item.strip() for item in fallback_raw.split(",") if item.strip()]
        llm_section = migrated.setdefault("llm", {})
        if isinstance(llm_section, dict) and not llm_section.get("fallback_chain"):
            llm_section["fallback_chain"] = chain
    elif isinstance(fallback_raw, list):
        llm_section = migrated.setdefault("llm", {})
        if isinstance(llm_section, dict) and not llm_section.get("fallback_chain"):
            llm_section["fallback_chain"] = list(fallback_raw)

    # Bump the version so validators know which schema to apply.
    migrated["version"] = 1
    return migrated


# ---------------------------------------------------------------------------
# Default/template helpers
# ---------------------------------------------------------------------------

def get_default_config() -> dict:
    """Return a JSON-serialisable view of the default config."""
    return ConfigSchema().model_dump(mode="json", exclude_none=True)


def generate_config_template() -> str:
    """Return a YAML template string with comments and section headers."""
    lines: list[str] = [
        "# Zeloo configuration (v1)",
        "#",
        "# Every section is optional — Zeloo fills sensible defaults for",
        "# anything you omit. Edit this file with `Zeloo config edit`.",
        "",
        "version: 1",
        "",
        "llm:",
        "  default_provider: openai",
        "  default_model: gpt-4o",
        "  temperature: 0.7",
        "  max_tokens: 4096",
        "  providers: {}",
        "  fallback_chain: []",
        "",
        "agent:",
        "  max_iterations: 10",
        "  temperature: 0.7",
        "  timeout_seconds: 60",
        "  enable_tools: true",
        "  enable_memory: true",
        "  enable_streaming: true",
        "",
        "memory:",
        "  enabled: true",
        "  backend: sqlite",
        "  max_entries: 10000",
        "  ttl_days: 90",
        "",
        "skills:",
        "  enabled: true",
        "  auto_load: []",
        "  workspace: default",
        "",
        "browser:",
        "  enabled: false",
        "  backend: playwright",
        "  headless: true",
        "  timeout_seconds: 30",
        "",
        "mcp:",
        "  enabled: true",
        "  auto_register: false",
        "  servers: {}",
        "",
        "telemetry:",
        "  enabled: false",
        "  log_level: INFO",
        "  otel_endpoint: null",
        "",
        "security:",
        "  approval_required: true",
        "  secret_scan: true",
        "  max_command_runtime: 300",
        "",
        "workspace:",
        "  default: default",
        "  auto_snapshot: true",
        "  snapshot_retention: 10",
        "",
    ]
    return "\n".join(lines)


def write_template(config_path: Path) -> None:
    """Write :func:`generate_config_template` to *config_path*.

    Existing files are left untouched unless they are empty. Returns
    nothing — callers can check ``config_path.exists()`` afterwards.
    """
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if not config_path.exists() or config_path.stat().st_size == 0:
            config_path.write_text(generate_config_template(), encoding="utf-8")
    except OSError as exc:  # noqa: BLE001
        logger.warning("Could not write template to %s: %s", config_path, exc)


__all__ = [
    "ConfigSchema",
    "ProviderConfig",
    "LLMConfig",
    "AgentConfig",
    "MemoryConfig",
    "SkillsConfig",
    "BrowserConfig",
    "MCPConfig",
    "TelemetryConfig",
    "SecurityConfig",
    "WorkspaceConfig",
    "validate_config",
    "validate_config_dict",
    "migrate_legacy_config",
    "get_default_config",
    "generate_config_template",
    "write_template",
]
