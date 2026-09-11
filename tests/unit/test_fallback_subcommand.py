"""Unit tests for ``zeloo_cli.subcommands.fallback``."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

from zeloo_cli.subcommands.fallback import (
    FallbackCommand,
    resolve_pattern,
    run as fallback_run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(**kwargs) -> argparse.Namespace:
    """Build a minimal argparse.Namespace for the fallback subcommand."""
    defaults: dict = {
        "fallback_action": None,
        "name": None,
        "providers": None,
        "conditions": None,
        "model_pattern": None,
        "chain_name": None,
        "retry_count": 2,
        "retry_delay": 1.0,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


@pytest.fixture
def mock_manager() -> MagicMock:
    """Build a fully-mocked ``FallbackConfigManager``."""
    mgr = MagicMock()
    mgr.load = MagicMock()
    mgr.save = MagicMock()
    mgr.add_chain = MagicMock()
    mgr.remove_chain = MagicMock(return_value=True)
    mgr.list_chains = MagicMock(return_value=[])
    mgr.validate_all = MagicMock(return_value={"valid": True, "errors": []})
    mgr._chains = {}  # noqa: SLF001
    mgr._model_configs = {}  # noqa: SLF001
    return mgr


# ---------------------------------------------------------------------------
# Class instantiation & metadata
# ---------------------------------------------------------------------------


class TestFallbackCommandInit:
    def test_init(self) -> None:
        cmd = FallbackCommand()
        assert cmd is not None
        assert isinstance(cmd, FallbackCommand)

    def test_name(self) -> None:
        assert FallbackCommand.name == "fallback"

    def test_help_non_empty(self) -> None:
        assert isinstance(FallbackCommand.help, str)
        assert len(FallbackCommand.help) > 0

    def test_configure_parser_builds_subactions(self) -> None:
        parser = argparse.ArgumentParser()
        FallbackCommand.configure_parser(parser)
        # Sanity check: parser is callable, no exception raised.

    def test_run_module_entry_point(self, mock_manager: MagicMock) -> None:
        with patch(
            "agent.fallback_config.FallbackConfigManager",
            return_value=mock_manager,
        ):
            rc = fallback_run(_make_args(fallback_action="list"))
        assert rc == 0


# ---------------------------------------------------------------------------
# list action
# ---------------------------------------------------------------------------


class TestListAction:
    @patch("agent.fallback_config.FallbackConfigManager")
    def test_list_empty_chains(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        mock_mgr_class.return_value = mock_manager
        cmd = FallbackCommand()
        rc = cmd.run(_make_args(fallback_action="list"))
        assert rc == 0
        mock_manager.load.assert_called_once()

    @patch("agent.fallback_config.FallbackConfigManager")
    def test_list_with_chains(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        from agent.fallback_config import FallbackChain

        chain = FallbackChain(
            name="vision", providers=["anthropic", "openai"],
            enabled=True, conditions={"requires_vision": True},
        )
        mock_manager._chains = {"vision": chain}  # noqa: SLF001
        mock_manager.list_chains.return_value = [chain]
        mock_mgr_class.return_value = mock_manager

        cmd = FallbackCommand()
        rc = cmd.run(_make_args(fallback_action="list"))
        assert rc == 0

    @patch("agent.fallback_config.FallbackConfigManager")
    def test_list_with_model_bindings(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        from agent.fallback_config import (
            FallbackChain, ModelFallbackConfig,
        )

        chain = FallbackChain(name="default", providers=["openai"])
        binding = ModelFallbackConfig(
            model_pattern="gpt-4*", chain_name="default",
            retry_count=3, retry_delay=0.5,
        )
        mock_manager._chains = {"default": chain}  # noqa: SLF001
        mock_manager._model_configs = {"gpt-4*": binding}  # noqa: SLF001
        mock_mgr_class.return_value = mock_manager

        cmd = FallbackCommand()
        rc = cmd.run(_make_args(fallback_action="list"))
        assert rc == 0


# ---------------------------------------------------------------------------
# add action
# ---------------------------------------------------------------------------


class TestAddAction:
    @patch("agent.fallback_config.FallbackConfigManager")
    def test_add_basic(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        mock_mgr_class.return_value = mock_manager
        cmd = FallbackCommand()
        rc = cmd.run(_make_args(
            fallback_action="add",
            name="fast",
            providers="openai,anthropic,deepseek",
        ))
        assert rc == 0
        mock_manager.add_chain.assert_called_once()
        # Verify the chain passed to add_chain has the right name & providers.
        chain = mock_manager.add_chain.call_args[0][0]
        assert chain.name == "fast"
        assert chain.providers == ["openai", "anthropic", "deepseek"]

    @patch("agent.fallback_config.FallbackConfigManager")
    def test_add_with_conditions(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        mock_mgr_class.return_value = mock_manager
        cmd = FallbackCommand()
        rc = cmd.run(_make_args(
            fallback_action="add",
            name="vision",
            providers="anthropic",
            conditions="requires_vision=true,max_latency_ms=2000",
        ))
        assert rc == 0
        chain = mock_manager.add_chain.call_args[0][0]
        assert chain.conditions["requires_vision"] is True
        assert chain.conditions["max_latency_ms"] == 2000

    @patch("agent.fallback_config.FallbackConfigManager")
    def test_add_empty_providers_errors(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        mock_mgr_class.return_value = mock_manager
        cmd = FallbackCommand()
        rc = cmd.run(_make_args(
            fallback_action="add",
            name="empty",
            providers=",,,",
        ))
        assert rc != 0
        mock_manager.add_chain.assert_not_called()

    @patch("agent.fallback_config.FallbackConfigManager")
    def test_add_strips_whitespace(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        mock_mgr_class.return_value = mock_manager
        cmd = FallbackCommand()
        cmd.run(_make_args(
            fallback_action="add",
            name="spaced",
            providers=" openai , anthropic , deepseek ",
        ))
        chain = mock_manager.add_chain.call_args[0][0]
        assert chain.providers == ["openai", "anthropic", "deepseek"]

    @patch("agent.fallback_config.FallbackConfigManager")
    def test_add_propagates_value_error(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        mock_manager.add_chain.side_effect = ValueError("duplicate name")
        mock_mgr_class.return_value = mock_manager
        cmd = FallbackCommand()
        rc = cmd.run(_make_args(
            fallback_action="add",
            name="dup",
            providers="openai",
        ))
        assert rc != 0


# ---------------------------------------------------------------------------
# remove action
# ---------------------------------------------------------------------------


class TestRemoveAction:
    @patch("agent.fallback_config.FallbackConfigManager")
    def test_remove_existing(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        mock_mgr_class.return_value = mock_manager
        cmd = FallbackCommand()
        rc = cmd.run(_make_args(
            fallback_action="remove", name="oldchain",
        ))
        assert rc == 0
        mock_manager.remove_chain.assert_called_once_with("oldchain")

    @patch("agent.fallback_config.FallbackConfigManager")
    def test_remove_missing(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        mock_manager.remove_chain.side_effect = KeyError("oldchain")
        mock_mgr_class.return_value = mock_manager
        cmd = FallbackCommand()
        rc = cmd.run(_make_args(
            fallback_action="remove", name="missing",
        ))
        assert rc != 0

    @patch("agent.fallback_config.FallbackConfigManager")
    def test_remove_invalid_name(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        mock_manager.remove_chain.side_effect = ValueError("invalid name")
        mock_mgr_class.return_value = mock_manager
        cmd = FallbackCommand()
        rc = cmd.run(_make_args(
            fallback_action="remove", name="",
        ))
        assert rc != 0


# ---------------------------------------------------------------------------
# set-model action
# ---------------------------------------------------------------------------


class TestSetModelAction:
    @patch("agent.fallback_config.FallbackConfigManager")
    def test_set_model_existing_chain(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        from agent.fallback_config import FallbackChain

        mock_manager._chains = {  # noqa: SLF001
            "default": FallbackChain(name="default", providers=["openai"]),
        }
        mock_mgr_class.return_value = mock_manager

        cmd = FallbackCommand()
        rc = cmd.run(_make_args(
            fallback_action="set-model",
            model_pattern="gpt-4*",
            chain_name="default",
            retry_count=3,
            retry_delay=0.5,
        ))
        assert rc == 0
        # Verify the binding was stored under the right key.
        assert "gpt-4*" in mock_manager._model_configs  # noqa: SLF001
        binding = mock_manager._model_configs["gpt-4*"]  # noqa: SLF001
        assert binding.chain_name == "default"
        assert binding.retry_count == 3
        assert binding.retry_delay == 0.5

    @patch("agent.fallback_config.FallbackConfigManager")
    def test_set_model_missing_chain_errors(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        mock_manager._chains = {}  # noqa: SLF001
        mock_mgr_class.return_value = mock_manager

        cmd = FallbackCommand()
        rc = cmd.run(_make_args(
            fallback_action="set-model",
            model_pattern="gpt-4*",
            chain_name="nonexistent",
        ))
        assert rc != 0


# ---------------------------------------------------------------------------
# validate action
# ---------------------------------------------------------------------------


class TestValidateAction:
    @patch("agent.fallback_config.FallbackConfigManager")
    def test_validate_healthy_chains(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        from agent.fallback_config import FallbackChain

        mock_manager._chains = {  # noqa: SLF001
            "a": FallbackChain(name="a", providers=["openai", "anthropic"]),
            "b": FallbackChain(name="b", providers=["groq"]),
        }
        mock_mgr_class.return_value = mock_manager

        cmd = FallbackCommand()
        rc = cmd.run(_make_args(fallback_action="validate"))
        assert rc == 0
        mock_manager.load.assert_called_once()

    @patch("agent.fallback_config.FallbackConfigManager")
    def test_validate_with_unknown_provider(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        from agent.fallback_config import FallbackChain

        mock_manager._chains = {  # noqa: SLF001
            "x": FallbackChain(name="x", providers=["notarealprovider"]),
        }
        mock_mgr_class.return_value = mock_manager

        cmd = FallbackCommand()
        rc = cmd.run(_make_args(fallback_action="validate"))
        # "warn" status still produces problems → exit code 1.
        assert rc != 0

    @patch("agent.fallback_config.FallbackConfigManager")
    def test_validate_empty_provider_list(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        from agent.fallback_config import FallbackChain

        mock_manager._chains = {  # noqa: SLF001
            "empty": FallbackChain(name="empty", providers=[]),
        }
        mock_mgr_class.return_value = mock_manager

        cmd = FallbackCommand()
        rc = cmd.run(_make_args(fallback_action="validate"))
        assert rc != 0

    @patch("agent.fallback_config.FallbackConfigManager")
    def test_validate_binding_references_missing_chain(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        from agent.fallback_config import (
            FallbackChain, ModelFallbackConfig,
        )

        mock_manager._chains = {  # noqa: SLF001
            "a": FallbackChain(name="a", providers=["openai"]),
        }
        mock_manager._model_configs = {  # noqa: SLF001
            "gpt-4*": ModelFallbackConfig(
                model_pattern="gpt-4*", chain_name="ghost",
            ),
        }
        mock_mgr_class.return_value = mock_manager

        cmd = FallbackCommand()
        rc = cmd.run(_make_args(fallback_action="validate"))
        assert rc != 0


# ---------------------------------------------------------------------------
# No action / unknown action
# ---------------------------------------------------------------------------


class TestUnknownAction:
    @patch("agent.fallback_config.FallbackConfigManager")
    def test_unknown_action_returns_error(
        self, mock_mgr_class: MagicMock, mock_manager: MagicMock,
    ) -> None:
        mock_mgr_class.return_value = mock_manager
        cmd = FallbackCommand()
        rc = cmd.run(_make_args(fallback_action="bogus-action"))
        assert rc != 0


# ---------------------------------------------------------------------------
# resolve_pattern (module-level helper)
# ---------------------------------------------------------------------------


class TestResolvePattern:
    def test_exact_match(self) -> None:
        chains = {"gpt-4o": "default", "claude": "anthropic"}
        assert resolve_pattern("gpt-4o", chains) == "default"

    def test_glob_match(self) -> None:
        chains = {"gpt-4*": "openai", "claude-*": "anthropic"}
        assert resolve_pattern("gpt-4o-mini", chains) == "openai"
        assert resolve_pattern("claude-3-5-sonnet", chains) == "anthropic"

    def test_no_match_returns_none(self) -> None:
        chains = {"gpt-4*": "openai"}
        assert resolve_pattern("llama-3", chains) is None

    def test_empty_patterns_returns_none(self) -> None:
        assert resolve_pattern("gpt-4o", {}) is None

    def test_first_match_wins(self) -> None:
        # Insertion order matters for pattern priority.
        chains = {"gpt-*": "first", "gpt-4*": "second"}
        assert resolve_pattern("gpt-4o", chains) == "first"


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


class TestParseConditions:
    def test_none(self) -> None:
        assert FallbackCommand._parse_conditions(None) == {}

    def test_empty_string(self) -> None:
        assert FallbackCommand._parse_conditions("") == {}

    def test_single_string_value(self) -> None:
        assert FallbackCommand._parse_conditions("region=us-east-1") == {
            "region": "us-east-1",
        }

    def test_int_value(self) -> None:
        assert FallbackCommand._parse_conditions("max_retries=3") == {
            "max_retries": 3,
        }

    def test_float_value(self) -> None:
        assert FallbackCommand._parse_conditions("threshold=0.5") == {
            "threshold": 0.5,
        }

    def test_bool_values(self) -> None:
        assert FallbackCommand._parse_conditions("enabled=true,disabled=false") == {
            "enabled": True, "disabled": False,
        }

    def test_mixed_values(self) -> None:
        out = FallbackCommand._parse_conditions(
            "flag=true,count=5,name=alpha,ratio=0.25",
        )
        assert out == {
            "flag": True,
            "count": 5,
            "name": "alpha",
            "ratio": 0.25,
        }

    def test_pairs_without_equals_dropped(self) -> None:
        # "orphan" has no =, must be silently skipped.
        out = FallbackCommand._parse_conditions("a=1,orphan,b=2")
        assert out == {"a": 1, "b": 2}


class TestKnownProviders:
    def test_known_providers_includes_common(self) -> None:
        known = FallbackCommand._known_providers()
        assert "openai" in known
        assert "anthropic" in known
        # Either 'google' or 'gemini' should be present (the runtime
        # registry uses one of these labels).
        assert ("google" in known) or ("gemini" in known)
        assert "groq" in known
        assert "deepseek" in known
        assert "mistral" in known

    def test_known_providers_is_non_empty(self) -> None:
        known = FallbackCommand._known_providers()
        assert isinstance(known, set)
        assert len(known) > 0

    def test_known_providers_contains_string(self) -> None:
        known = FallbackCommand._known_providers()
        # All entries must be strings.
        for entry in known:
            assert isinstance(entry, str)


class TestValidateProvider:
    def test_known_provider(self) -> None:
        status, notes = FallbackCommand._validate_provider(
            "openai", {"openai", "anthropic"},
        )
        assert status == "ok"

    def test_unknown_provider(self) -> None:
        status, notes = FallbackCommand._validate_provider(
            "mystery", {"openai"},
        )
        assert status == "warn"
        assert "not registered" in notes

    def test_empty_provider(self) -> None:
        status, notes = FallbackCommand._validate_provider("", {"openai"})
        assert status == "warn"
        assert "empty" in notes
