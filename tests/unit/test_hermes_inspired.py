"""Tests for Round 56: Hermes-inspired frontends.

Coverage:

* Setup wizard: non-interactive path (CI / script), provider catalogue,
  answers → config dict round-trip
* Skin engine: built-in skins load, user skin overlays built-in,
  render_banner / render_prompt produce ANSI-coded strings, list_skins
  enumerates built-in + user, set_skin_value writes YAML
* TUI history: walk back / forward, draft restoration, dedup
* TUI completion: slash command filtering
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from zeloo_cli.setup_wizard import (
    PROVIDER_CATALOG,
    WizardAnswers,
    apply_wizard_answers,
    run_setup_wizard,
)
from zeloo_cli.skin_engine import (
    BUILTIN_SKINS,
    Skin,
    list_skins,
    load_skin,
    render_banner,
    render_prompt,
    render_status,
    reset_skin_cache,
    set_skin_value,
)
from zeloo_tui.history import (
    SLASH_COMMANDS,
    InputHistory,
    filter_slash_commands,
)

# ── setup wizard ──────────────────────────────────────────────────


class TestWizardAnswers:
    def test_default_answers(self) -> None:
        a = WizardAnswers()
        assert a.provider == "openai"
        assert a.model == "gpt-4o"
        assert a.max_iterations == 25
        assert a.temperature == 0.0
        assert a.enable_memory is True

    def test_to_config_dict(self) -> None:
        a = WizardAnswers(
            provider="anthropic",
            model="claude-3-5-sonnet-20241022",
            max_iterations=10,
            enable_mcp=False,
        )
        cfg = a.to_config_dict()
        assert cfg["provider"] == "anthropic"
        assert cfg["model"] == "claude-3-5-sonnet-20241022"
        assert cfg["max_iterations"] == 10
        assert cfg["features"]["mcp"] is False
        assert cfg["features"]["memory"] is True

    def test_provider_catalogue_has_expected_keys(self) -> None:
        for name in ("openai", "anthropic", "xai", "openrouter", "deepseek", "google"):
            catalog = PROVIDER_CATALOG[name]
            assert "default_model" in catalog
            assert "env_var" in catalog
            assert "models" in catalog
            assert len(catalog["models"]) > 0


class TestSetupWizardNonInteractive:
    """``run_setup_wizard`` in non-TTY mode returns the default answers.

    Used by CI / docker entrypoints where stdin isn't a TTY — the
    wizard must not block or raise, it just returns a default-filled
    ``WizardAnswers``.
    """

    def test_returns_defaults_in_non_tty(self, tmp_path: Path) -> None:
        answers = run_setup_wizard(home=tmp_path, isatty=False)
        assert answers.provider == "openai"
        assert answers.model == "gpt-4o"
        assert answers.max_iterations == 25

    def test_apply_writes_files(self, tmp_path: Path) -> None:
        answers = WizardAnswers(
            provider="anthropic",
            model="claude-3-5-sonnet-20241022",
            api_key="sk-test",
            max_iterations=15,
        )
        cfg_path, env_path = apply_wizard_answers(
            answers, home=tmp_path, overwrite=True
        )
        assert cfg_path.exists()
        assert env_path.exists()
        cfg = yaml.safe_load(cfg_path.read_text())
        assert cfg["provider"] == "anthropic"
        assert cfg["model"] == "claude-3-5-sonnet-20241022"
        env_content = env_path.read_text()
        assert "ANTHROPIC_API_KEY=sk-test" in env_content
        assert "zeloo_PROVIDER=anthropic" in env_content

    def test_apply_refuses_overwrite_without_flag(self, tmp_path: Path) -> None:
        # Pre-populate the home
        (tmp_path / "config.yaml").write_text("provider: openai\n")
        answers = WizardAnswers()
        with pytest.raises(FileExistsError):
            apply_wizard_answers(answers, home=tmp_path, overwrite=False)

    def test_apply_additive_overwrite(self, tmp_path: Path) -> None:
        # Existing user-only keys should survive a re-run.
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("user_key: keep_me\n")
        env_path = tmp_path / ".env"
        env_path.write_text("USER_TOKEN=xyz\n")
        answers = WizardAnswers(provider="openai", model="gpt-4o", api_key="sk-x")
        apply_wizard_answers(answers, home=tmp_path, overwrite=True)
        cfg = yaml.safe_load(cfg_path.read_text())
        # The wizard's keys overlay the existing ones
        assert cfg["provider"] == "openai"
        # Non-managed user keys are preserved
        assert cfg["user_key"] == "keep_me"
        env_content = env_path.read_text()
        assert "USER_TOKEN=xyz" in env_content
        assert "OPENAI_API_KEY=sk-x" in env_content


# ── skin engine ──────────────────────────────────────────────────


class TestSkinEngine:
    def setup_method(self) -> None:
        reset_skin_cache()

    def test_builtin_skins_load(self) -> None:
        for name in ("default", "plain", "starlight", "solarized"):
            skin = load_skin(name)
            assert skin.name == name
            assert isinstance(skin, Skin)

    def test_unknown_falls_back_to_default(self) -> None:
        skin = load_skin("does-not-exist")
        assert skin.name == "default"

    def test_user_skin_overlays_builtin(self, tmp_path: Path) -> None:
        # Override the default skin's prompt symbol via a user file
        # at the canonical location.
        from zeloo_cli import skin_engine

        # Patch the helper to use our tmp dir
        original = skin_engine._user_skins_dir

        try:
            skin_engine._user_skins_dir = lambda: tmp_path
            (tmp_path / "default.yaml").write_text(
                "prompt:\n  symbol: 'ZELOO> '\n"
            )
            reset_skin_cache()
            skin = load_skin("default")
            assert skin.prompt.symbol == "ZELOO> "
            # Built-in banner is preserved
            assert skin.banner.glyph == "⚡"
        finally:
            skin_engine._user_skins_dir = original

    def test_render_banner_contains_glyph(self) -> None:
        out = render_banner()
        assert "⚡" in out
        assert "Zeloo" in out

    def test_render_prompt_strips_ansi_when_disabled(self) -> None:
        # The ``plain`` skin has colors.enabled=False, so the prompt
        # has no ANSI escape codes.
        prompt = render_prompt(BUILTIN_SKINS["plain"])
        assert "\x1b[" not in prompt

    def test_render_status_levels(self) -> None:
        skin = BUILTIN_SKINS["default"]
        assert "ok" in render_status("success", "ok", skin).lower() or "\x1b[" in render_status("success", "ok", skin)
        # Unknown level is passed through uncoloured
        assert "custom" in render_status("nope", "custom-level", skin)

    def test_set_skin_value_persists(self, tmp_path: Path) -> None:
        from zeloo_cli import skin_engine

        original = skin_engine._user_skins_dir
        try:
            skin_engine._user_skins_dir = lambda: tmp_path
            reset_skin_cache()
            path = set_skin_value("colors.prompt", "magenta", skin_name="default")
            assert path.exists()
            data = yaml.safe_load(path.read_text())
            assert data["colors"]["prompt"] == "magenta"
        finally:
            skin_engine._user_skins_dir = original
            reset_skin_cache()

    def test_list_skins(self, tmp_path: Path) -> None:
        from zeloo_cli import skin_engine

        original = skin_engine._user_skins_dir
        try:
            skin_engine._user_skins_dir = lambda: tmp_path
            (tmp_path / "custom.yaml").write_text("banner:\n  glyph: '★'\n")
            names = [s["name"] for s in list_skins()]
            assert "default" in names
            assert "plain" in names
            assert "custom" in names
        finally:
            skin_engine._user_skins_dir = original


# ── TUI history + completion ─────────────────────────────────────


class TestInputHistory:
    def test_empty_up_returns_none(self) -> None:
        h = InputHistory()
        assert h.up("draft") is None

    def test_push_and_up(self) -> None:
        h = InputHistory()
        h.push("hello")
        h.push("world")
        assert h.up("draft") == "world"
        assert h.up(h.draft) == "hello"
        # At the top, up stays put
        assert h.up(h.draft) == "hello"

    def test_down_walks_back_to_draft(self) -> None:
        h = InputHistory()
        h.push("a")
        h.push("b")
        h.up("X")  # → "b"
        h.up("X")  # → "a"
        # Now down once
        assert h.down("Y") == "b"
        # Down off the bottom restores the original draft
        assert h.down("Y") == "X"
        # Past the bottom is a no-op
        assert h.down("Y") is None

    def test_dedup_consecutive(self) -> None:
        h = InputHistory()
        h.push("foo")
        h.push("foo")
        h.push("foo")
        assert h.entries == ["foo"]

    def test_max_size_caps_entries(self) -> None:
        h = InputHistory(max_size=3)
        for i in range(5):
            h.push(f"line-{i}")
        assert h.entries == ["line-2", "line-3", "line-4"]
        assert len(h.entries) == h.max_size

    def test_whitespace_only_lines_skipped(self) -> None:
        h = InputHistory()
        h.push("   ")
        h.push("")
        h.push("\t")
        assert h.entries == []

    def test_reset(self) -> None:
        h = InputHistory()
        h.push("a")
        h.up("draft")
        h.reset()
        assert h.cursor == -1
        assert h.draft == ""


class TestCompletion:
    def test_slash_commands_catalog_non_empty(self) -> None:
        assert len(SLASH_COMMANDS) > 0
        # Every entry has the three required keys
        for c in SLASH_COMMANDS:
            assert {"name", "description", "example"} <= set(c.keys())

    def test_filter_prefix(self) -> None:
        matches = filter_slash_commands("/h")
        names = [m["name"] for m in matches]
        assert "/help" in names

    def test_filter_skin(self) -> None:
        matches = filter_slash_commands("/skin")
        assert len(matches) == 1
        assert matches[0]["name"] == "/skin"

    def test_filter_no_slash_returns_empty(self) -> None:
        assert filter_slash_commands("hello") == []

    def test_filter_unknown_returns_empty(self) -> None:
        assert filter_slash_commands("/zzz") == []