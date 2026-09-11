"""Tests for environments config loader."""

import os

from environments import (
    ENV_FILES,
    ENV_NAMES,
    _deep_merge,
    _parse_simple_yaml,
    current_env_name,
    list_available_environments,
    load_all_environments,
    load_environment,
)


class TestParseSimpleYaml:
    def test_empty(self):
        assert _parse_simple_yaml("") == {}

    def test_flat_keys(self):
        text = """
        name: alice
        age: 30
        active: true
        """
        result = _parse_simple_yaml(text)
        assert result["name"] == "alice"
        assert result["age"] == 30
        assert result["active"] is True

    def test_nested_dict(self):
        text = """
        server:
          host: localhost
          port: 8080
        """
        result = _parse_simple_yaml(text)
        assert "server" in result
        assert result["server"]["host"] == "localhost"
        assert result["server"]["port"] == 8080

    def test_comments_ignored(self):
        text = """
        # This is a comment
        key: value
        """
        result = _parse_simple_yaml(text)
        assert result == {"key": "value"}

    def test_lists(self):
        text = """
        tools:
          - shell
          - file
        """
        result = _parse_simple_yaml(text)
        assert result["tools"] == ["shell", "file"]

    def test_null_value(self):
        result = _parse_simple_yaml("key: null")
        assert result["key"] is None

    def test_numeric_types(self):
        result = _parse_simple_yaml("a: 1.5\nb: 100\nc: 0")
        assert result["a"] == 1.5
        assert result["b"] == 100
        assert result["c"] == 0


class TestDeepMerge:
    def test_simple_override(self):
        base = {"a": 1, "b": 2}
        overlay = {"b": 3}
        _deep_merge(base, overlay)
        assert base == {"a": 1, "b": 3}

    def test_nested_merge(self):
        base = {"server": {"host": "x", "port": 80}}
        overlay = {"server": {"port": 8080}}
        _deep_merge(base, overlay)
        assert base == {"server": {"host": "x", "port": 8080}}

    def test_new_key(self):
        base = {"a": 1}
        overlay = {"b": 2}
        _deep_merge(base, overlay)
        assert base == {"a": 1, "b": 2}

    def test_type_replacement(self):
        base = {"x": {"a": 1}}
        overlay = {"x": [1, 2]}
        _deep_merge(base, overlay)
        assert base["x"] == [1, 2]


class TestCurrentEnvName:
    def test_default_is_dev(self):
        original = os.environ.get("zeloo_ENV")
        try:
            os.environ.pop("zeloo_ENV", None)
            assert current_env_name() == "dev"
        finally:
            if original is not None:
                os.environ["zeloo_ENV"] = original

    def test_explicit_env(self):
        original = os.environ.get("zeloo_ENV")
        try:
            os.environ["zeloo_ENV"] = "prod"
            assert current_env_name() == "prod"
        finally:
            if original is None:
                os.environ.pop("zeloo_ENV", None)
            else:
                os.environ["zeloo_ENV"] = original

    def test_unknown_falls_back_to_dev(self):
        original = os.environ.get("zeloo_ENV")
        try:
            os.environ["zeloo_ENV"] = "garbage"
            assert current_env_name() == "dev"
        finally:
            if original is None:
                os.environ.pop("zeloo_ENV", None)
            else:
                os.environ["zeloo_ENV"] = original


class TestLoadEnvironment:
    def test_load_dev(self):
        config = load_environment("dev")
        assert "model" in config
        assert "gpt" in config["model"].lower()

    def test_load_prod(self):
        config = load_environment("prod")
        assert "model" in config
        assert config["model"] == "gpt-4o"

    def test_load_test(self):
        config = load_environment("test")
        assert isinstance(config, dict)

    def test_unknown_raises(self):
        try:
            load_environment("nonexistent")
            raise AssertionError("Should have raised")
        except ValueError as exc:
            assert "Unknown environment" in str(exc)

    def test_load_all(self):
        configs = load_all_environments()
        assert set(configs.keys()) == set(ENV_NAMES)


class TestListAvailable:
    def test_includes_three_envs(self):
        available = list_available_environments()
        assert "dev" in available
        assert "test" in available
        assert "prod" in available


class TestEnvFiles:
    def test_all_three_present(self):
        assert set(ENV_FILES.keys()) == set(ENV_NAMES)
        assert ENV_FILES["dev"] == "dev.yaml"
        assert ENV_FILES["test"] == "test.yaml"
        assert ENV_FILES["prod"] == "prod.yaml"


class TestBaseOverlayMerge:
    """base.yaml is loaded first; <env>.yaml is deep-merged over it."""

    def test_base_values_inherited(self):
        # provider and voice.backend only exist in base.yaml
        dev = load_environment("dev")
        assert dev["provider"] == "openai"
        assert dev["voice"]["backend"] == "console"

    def test_overlay_wins_over_base(self):
        # base sets self_evolution.background_review.enabled = false;
        # prod.yaml sets it to true
        prod = load_environment("prod")
        assert prod["self_evolution"]["background_review"]["enabled"] is True

    def test_dev_inherits_base_default(self):
        # dev.yaml does not set background_review.enabled, inherits base=false
        dev = load_environment("dev")
        assert dev["self_evolution"]["background_review"]["enabled"] is False

    def test_nested_overlay_merges_not_replaces(self):
        # base has gateway.platforms = {}; prod adds gateway.api.*
        prod = load_environment("prod")
        assert prod["gateway"]["platforms"] == {}
        assert prod["gateway"]["api"]["enabled"] is True


class TestEnvVarOverrides:
    """zeloo_* environment variables override config values."""

    def test_top_level_override(self):
        original = os.environ.get("zeloo_MODEL")
        try:
            os.environ["zeloo_MODEL"] = "gpt-4-turbo"
            cfg = load_environment("dev")
            assert cfg["model"] == "gpt-4-turbo"
        finally:
            if original is None:
                os.environ.pop("zeloo_MODEL", None)
            else:
                os.environ["zeloo_MODEL"] = original

    def test_nested_override_with_double_underscore(self):
        original = os.environ.get("zeloo_TERMINAL__BACKEND")
        try:
            os.environ["zeloo_TERMINAL__BACKEND"] = "remote"
            cfg = load_environment("dev")
            assert cfg["terminal"]["backend"] == "remote"
        finally:
            if original is None:
                os.environ.pop("zeloo_TERMINAL__BACKEND", None)
            else:
                os.environ["zeloo_TERMINAL__BACKEND"] = original

    def test_value_type_coerced(self):
        original = os.environ.get("zeloo_MAX_TOKENS")
        try:
            os.environ["zeloo_MAX_TOKENS"] = "9999"
            cfg = load_environment("dev")
            assert cfg["max_tokens"] == 9999
            assert isinstance(cfg["max_tokens"], int)
        finally:
            if original is None:
                os.environ.pop("zeloo_MAX_TOKENS", None)
            else:
                os.environ["zeloo_MAX_TOKENS"] = original

    def test_unknown_env_var_not_injected(self):
        original = os.environ.get("zeloo_DOES_NOT_EXIST")
        try:
            os.environ["zeloo_DOES_NOT_EXIST"] = "injected"
            cfg = load_environment("dev")
            assert "does_not_exist" not in cfg
        finally:
            if original is None:
                os.environ.pop("zeloo_DOES_NOT_EXIST", None)
            else:
                os.environ["zeloo_DOES_NOT_EXIST"] = original

    def test_zeloo_env_not_treated_as_override(self):
        # zeloo_ENV selects the environment, must not become a config key
        original = os.environ.get("zeloo_ENV")
        try:
            os.environ["zeloo_ENV"] = "prod"
            cfg = load_environment("dev")
            assert "env" not in cfg
        finally:
            if original is None:
                os.environ.pop("zeloo_ENV", None)
            else:
                os.environ["zeloo_ENV"] = original