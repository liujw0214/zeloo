"""Unit tests for ``zeloo_cli.config_schema``."""

from __future__ import annotations

from pathlib import Path

import pytest

from zeloo_cli.config_schema import (
    AgentConfig,
    BrowserConfig,
    ConfigSchema,
    LLMConfig,
    MCPConfig,
    MemoryConfig,
    ProviderConfig,
    SecurityConfig,
    SkillsConfig,
    TelemetryConfig,
    WorkspaceConfig,
    generate_config_template,
    get_default_config,
    migrate_legacy_config,
    validate_config,
    validate_config_dict,
    write_template,
)


# ---------------------------------------------------------------------------
# ProviderConfig
# ---------------------------------------------------------------------------


class TestProviderConfig:
    def test_default(self) -> None:
        p = ProviderConfig()
        assert p.enabled is True
        assert p.api_key is None
        assert p.model is None
        assert p.base_url is None
        assert p.organization is None
        assert p.extra == {}

    def test_with_values(self) -> None:
        p = ProviderConfig(api_key="sk-xxx", model="gpt-4o")
        assert p.api_key == "sk-xxx"
        assert p.model == "gpt-4o"

    def test_disabled(self) -> None:
        p = ProviderConfig(enabled=False)
        assert p.enabled is False

    def test_extra_dict(self) -> None:
        p = ProviderConfig(extra={"region": "us-east-1"})
        assert p.extra["region"] == "us-east-1"


# ---------------------------------------------------------------------------
# LLMConfig
# ---------------------------------------------------------------------------


class TestLLMConfig:
    def test_default(self) -> None:
        c = LLMConfig()
        assert c.default_provider == "openai"
        assert c.default_model == "gpt-4o"
        assert c.temperature == 0.7
        assert c.max_tokens == 4096
        assert c.providers == {}
        assert c.fallback_chain == []

    def test_with_providers(self) -> None:
        c = LLMConfig(providers={
            "openai": ProviderConfig(api_key="sk-1"),
            "anthropic": ProviderConfig(model="claude-3"),
        })
        assert "openai" in c.providers
        assert "anthropic" in c.providers
        assert c.providers["openai"].api_key == "sk-1"

    def test_fallback_chain_accepts_list(self) -> None:
        c = LLMConfig(fallback_chain=["anthropic", "openai", "google"])
        assert c.fallback_chain == ["anthropic", "openai", "google"]


# ---------------------------------------------------------------------------
# AgentConfig
# ---------------------------------------------------------------------------


class TestAgentConfig:
    def test_default(self) -> None:
        c = AgentConfig()
        assert c.max_iterations == 10
        assert c.temperature == 0.7
        assert c.timeout_seconds == 60
        assert c.enable_tools is True
        assert c.enable_memory is True
        assert c.enable_streaming is True

    def test_custom_values(self) -> None:
        c = AgentConfig(max_iterations=5, temperature=0.3, timeout_seconds=120)
        assert c.max_iterations == 5
        assert c.temperature == 0.3
        assert c.timeout_seconds == 120

    def test_disable_flags(self) -> None:
        c = AgentConfig(
            enable_tools=False, enable_memory=False, enable_streaming=False,
        )
        assert c.enable_tools is False
        assert c.enable_memory is False
        assert c.enable_streaming is False


# ---------------------------------------------------------------------------
# MemoryConfig / SkillsConfig / BrowserConfig / MCPConfig / TelemetryConfig
# ---------------------------------------------------------------------------


class TestMemoryConfig:
    def test_default(self) -> None:
        c = MemoryConfig()
        assert c.enabled is True
        assert c.backend == "sqlite"
        assert c.max_entries == 10_000
        assert c.ttl_days == 90


class TestSkillsConfig:
    def test_default(self) -> None:
        c = SkillsConfig()
        assert c.enabled is True
        assert c.auto_load == []
        assert c.workspace == "default"

    def test_auto_load_list(self) -> None:
        c = SkillsConfig(auto_load=["code-review", "debugging"])
        assert c.auto_load == ["code-review", "debugging"]


class TestBrowserConfig:
    def test_default(self) -> None:
        c = BrowserConfig()
        assert c.enabled is False
        assert c.backend == "playwright"
        assert c.headless is True
        assert c.timeout_seconds == 30


class TestMCPConfig:
    def test_default(self) -> None:
        c = MCPConfig()
        assert c.enabled is True
        assert c.auto_register is False
        assert c.servers == {}

    def test_servers_dict(self) -> None:
        c = MCPConfig(servers={"github": {"command": "npx", "args": ["-y", "x"]}})
        assert "github" in c.servers


class TestTelemetryConfig:
    def test_default(self) -> None:
        c = TelemetryConfig()
        assert c.enabled is False
        assert c.log_level == "INFO"
        assert c.otel_endpoint is None

    def test_log_levels(self) -> None:
        for lvl in ("DEBUG", "INFO", "WARNING", "ERROR"):
            c = TelemetryConfig(log_level=lvl)  # type: ignore[arg-type]
            assert c.log_level == lvl

    def test_invalid_log_level_raises(self) -> None:
        with pytest.raises(Exception):
            TelemetryConfig(log_level="VERBOSE")  # type: ignore[arg-type]


class TestSecurityConfig:
    def test_default(self) -> None:
        c = SecurityConfig()
        assert c.approval_required is True
        assert c.secret_scan is True
        assert c.max_command_runtime == 300


class TestWorkspaceConfig:
    def test_default(self) -> None:
        c = WorkspaceConfig()
        assert c.default == "default"
        assert c.auto_snapshot is True
        assert c.snapshot_retention == 10


# ---------------------------------------------------------------------------
# ConfigSchema (root)
# ---------------------------------------------------------------------------


class TestConfigSchema:
    def test_default(self) -> None:
        s = ConfigSchema()
        assert s.version == 1
        assert s.llm.default_provider == "openai"
        assert s.agent.temperature == 0.7
        assert s.memory.enabled is True
        assert s.browser.enabled is False

    def test_from_nested_dict(self) -> None:
        d = {
            "llm": {
                "default_provider": "anthropic",
                "default_model": "claude-3-5-sonnet",
            }
        }
        s = ConfigSchema(**d)
        assert s.llm.default_provider == "anthropic"
        assert s.llm.default_model == "claude-3-5-sonnet"

    def test_full_override(self) -> None:
        s = ConfigSchema.model_validate({
            "llm": {"default_provider": "deepseek", "default_model": "deepseek-chat"},
            "agent": {"max_iterations": 25, "temperature": 0.2},
            "memory": {"max_entries": 5000, "ttl_days": 30},
            "browser": {"enabled": True, "headless": False},
            "telemetry": {"enabled": True, "log_level": "DEBUG"},
        })
        assert s.llm.default_provider == "deepseek"
        assert s.agent.max_iterations == 25
        assert s.memory.max_entries == 5000
        assert s.browser.enabled is True
        assert s.telemetry.log_level == "DEBUG"

    def test_invalid_top_level_type(self) -> None:
        with pytest.raises(Exception):
            ConfigSchema.model_validate({"version": "not-a-number"})


# ---------------------------------------------------------------------------
# validate_config_dict
# ---------------------------------------------------------------------------


class TestValidateConfigDict:
    def test_validate_empty_dict_valid(self) -> None:
        ok, errors = validate_config_dict({})
        assert ok is True
        assert errors == []

    def test_validate_dict_valid(self) -> None:
        d = {"llm": {"default_provider": "openai"}}
        ok, errors = validate_config_dict(d)
        assert ok is True
        assert errors == []

    def test_validate_dict_invalid_section_type(self) -> None:
        d = {"llm": "not-a-dict"}
        ok, errors = validate_config_dict(d)
        assert ok is False
        assert len(errors) > 0

    def test_validate_dict_invalid_field_type(self) -> None:
        d = {"agent": {"max_iterations": "not-an-int"}}
        ok, errors = validate_config_dict(d)
        assert ok is False
        assert len(errors) > 0

    def test_validate_dict_invalid_telemetry_log_level(self) -> None:
        d = {"telemetry": {"log_level": "VERBOSE"}}
        ok, errors = validate_config_dict(d)
        assert ok is False
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# validate_config (file path)
# ---------------------------------------------------------------------------


class TestValidateConfigFile:
    def test_validate_file_missing(self, tmp_path: Path) -> None:
        ok, errors = validate_config(tmp_path / "does_not_exist.yaml")
        assert ok is False
        assert len(errors) > 0

    def test_validate_file_valid(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "llm:\n  default_provider: openai\n  default_model: gpt-4o\n",
            encoding="utf-8",
        )
        ok, errors = validate_config(cfg)
        assert ok is True
        assert errors == []

    def test_validate_file_invalid_yaml(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text("llm: : : :\n  bad: yaml: ::\n", encoding="utf-8")
        ok, errors = validate_config(cfg)
        assert ok is False
        assert len(errors) > 0

    def test_validate_file_empty(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text("", encoding="utf-8")
        ok, errors = validate_config(cfg)
        # Empty file yields {} which is valid.
        assert ok is True
        assert errors == []


# ---------------------------------------------------------------------------
# migrate_legacy_config
# ---------------------------------------------------------------------------


class TestMigrateLegacyConfig:
    def test_empty_returns_empty(self) -> None:
        assert migrate_legacy_config({}) == {"version": 1}

    def test_non_dict_returns_empty(self) -> None:
        assert migrate_legacy_config("not a dict") == {}  # type: ignore[arg-type]
        assert migrate_legacy_config(None) == {}  # type: ignore[arg-type]

    def test_flat_to_nested(self) -> None:
        old = {
            "model": "gpt-4o",
            "provider": "openai",
            "temperature": 0.5,
        }
        migrated = migrate_legacy_config(old)
        assert "llm" in migrated
        assert migrated["llm"]["default_model"] == "gpt-4o"
        assert migrated["llm"]["default_provider"] == "openai"
        assert migrated["llm"]["temperature"] == 0.5
        assert migrated["version"] == 1

    def test_fallback_string_to_list(self) -> None:
        old = {"fallback": "anthropic,openai,deepseek"}
        migrated = migrate_legacy_config(old)
        assert "llm" in migrated
        chain = migrated["llm"]["fallback_chain"]
        assert isinstance(chain, list)
        assert chain == ["anthropic", "openai", "deepseek"]

    def test_fallback_string_strips_whitespace(self) -> None:
        old = {"fallback": "anthropic , openai ,  deepseek"}
        migrated = migrate_legacy_config(old)
        chain = migrated["llm"]["fallback_chain"]
        assert chain == ["anthropic", "openai", "deepseek"]

    def test_fallback_string_empty_parts_dropped(self) -> None:
        old = {"fallback": "anthropic,,openai,"}
        migrated = migrate_legacy_config(old)
        chain = migrated["llm"]["fallback_chain"]
        assert chain == ["anthropic", "openai"]

    def test_fallback_providers_key(self) -> None:
        old = {"fallback_providers": "openai,anthropic"}
        migrated = migrate_legacy_config(old)
        assert migrated["llm"]["fallback_chain"] == ["openai", "anthropic"]

    def test_fallback_list_passed_through(self) -> None:
        old = {"fallback": ["anthropic", "openai"]}
        migrated = migrate_legacy_config(old)
        assert migrated["llm"]["fallback_chain"] == ["anthropic", "openai"]

    def test_legacy_top_level_fields_migrated(self) -> None:
        old = {
            "max_iterations": 30,
            "approval_required": False,
            "log_level": "DEBUG",
            "max_tokens": 8192,
        }
        migrated = migrate_legacy_config(old)
        assert migrated["agent"]["max_iterations"] == 30
        assert migrated["security"]["approval_required"] is False
        assert migrated["telemetry"]["log_level"] == "DEBUG"
        assert migrated["llm"]["max_tokens"] == 8192

    def test_existing_nested_section_preserved(self) -> None:
        old = {
            "llm": {"default_provider": "anthropic"},
            "model": "gpt-4o",  # legacy flat field
        }
        migrated = migrate_legacy_config(old)
        # Pre-existing nested values win.
        assert migrated["llm"]["default_provider"] == "anthropic"
        # Legacy field still fills the empty slot.
        assert migrated["llm"]["default_model"] == "gpt-4o"

    def test_version_bumped(self) -> None:
        old = {"llm": {"default_provider": "openai"}}
        migrated = migrate_legacy_config(old)
        assert migrated["version"] == 1


# ---------------------------------------------------------------------------
# get_default_config / generate_config_template / write_template
# ---------------------------------------------------------------------------


class TestDefaultConfig:
    def test_get_default_returns_dict(self) -> None:
        d = get_default_config()
        assert isinstance(d, dict)
        assert "llm" in d
        assert "agent" in d

    def test_default_llm_section(self) -> None:
        d = get_default_config()
        assert d["llm"]["default_provider"] == "openai"
        assert d["llm"]["default_model"] == "gpt-4o"

    def test_default_agent_section(self) -> None:
        d = get_default_config()
        assert d["agent"]["max_iterations"] == 10

    def test_default_memory_section(self) -> None:
        d = get_default_config()
        assert d["memory"]["enabled"] is True


class TestGenerateTemplate:
    def test_generate_template_returns_string(self) -> None:
        template = generate_config_template()
        assert isinstance(template, str)
        assert len(template) > 0

    def test_template_contains_llm_section(self) -> None:
        template = generate_config_template()
        assert "llm:" in template
        assert "provider" in template.lower()

    def test_template_contains_agent_section(self) -> None:
        template = generate_config_template()
        assert "agent:" in template

    def test_template_contains_memory_section(self) -> None:
        template = generate_config_template()
        assert "memory:" in template

    def test_template_contains_browser_section(self) -> None:
        template = generate_config_template()
        assert "browser:" in template

    def test_template_contains_mcp_section(self) -> None:
        template = generate_config_template()
        assert "mcp:" in template

    def test_template_starts_with_version(self) -> None:
        template = generate_config_template()
        assert template.startswith("# Zeloo configuration")
        assert "version: 1" in template


class TestWriteTemplate:
    def test_write_template_creates_file(self, tmp_path: Path) -> None:
        target = tmp_path / "config.yaml"
        write_template(target)
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert "version: 1" in content

    def test_write_template_does_not_overwrite(
        self, tmp_path: Path,
    ) -> None:
        target = tmp_path / "config.yaml"
        target.write_text("# existing\n", encoding="utf-8")
        write_template(target)
        # Existing non-empty file is preserved.
        assert target.read_text(encoding="utf-8") == "# existing\n"

    def test_write_template_creates_missing_directory(
        self, tmp_path: Path,
    ) -> None:
        target = tmp_path / "nested" / "deeper" / "config.yaml"
        write_template(target)
        assert target.exists()
