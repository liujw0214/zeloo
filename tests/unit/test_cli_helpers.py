"""Tests for CLI subcommand helpers."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from cli import _cmd_status, _get_nested, _set_nested


def test_get_nested_simple_key():
    assert _get_nested({"a": 1}, "a") == 1


def test_get_nested_dot_path():
    cfg = {"model": {"provider": "openai", "name": "gpt-4o"}}
    assert _get_nested(cfg, "model.provider") == "openai"


def test_get_nested_missing_returns_none():
    assert _get_nested({"a": 1}, "b") is None
    assert _get_nested({"a": {"b": 1}}, "a.c") is None


def test_set_nested_creates_intermediate_dicts():
    cfg = {}
    _set_nested(cfg, "a.b.c", "42")
    assert cfg == {"a": {"b": {"c": 42}}}


def test_set_nested_parses_int():
    cfg = {}
    _set_nested(cfg, "max_tokens", "4096")
    assert cfg["max_tokens"] == 4096


def test_set_nested_parses_float():
    cfg = {}
    _set_nested(cfg, "temperature", "0.7")
    assert cfg["temperature"] == 0.7


def test_set_nested_parses_bool_true():
    cfg = {}
    _set_nested(cfg, "enabled", "true")
    assert cfg["enabled"] is True


def test_set_nested_parses_bool_false():
    cfg = {}
    _set_nested(cfg, "enabled", "false")
    assert cfg["enabled"] is False


def test_set_nested_keeps_string():
    cfg = {}
    _set_nested(cfg, "model", "gpt-4o")
    assert cfg["model"] == "gpt-4o"


def test_set_nested_overwrites_existing():
    cfg = {"a": {"b": 1}}
    _set_nested(cfg, "a.b", "99")
    assert cfg["a"]["b"] == 99


def test_round_trip_get_set():
    cfg = {}
    _set_nested(cfg, "gateway.api.port", "9113")
    assert _get_nested(cfg, "gateway.api.port") == 9113


def test_cmd_status_outputs_model_info(capsys):
    args = argparse.Namespace()
    with patch("cli.load_config", return_value={"model": "gpt-4o", "provider": "openai"}):
        with patch("cli.load_env_file", return_value={}):
            _cmd_status(args)
    out = capsys.readouterr().out
    assert "gpt-4o" in out
    assert "openai" in out
    assert "Profile" in out


if __name__ == "__main__":
    test_get_nested_simple_key()
    test_get_nested_dot_path()
    test_get_nested_missing_returns_none()
    test_set_nested_creates_intermediate_dicts()
    test_set_nested_parses_int()
    test_set_nested_parses_float()
    test_set_nested_parses_bool_true()
    test_set_nested_parses_bool_false()
    test_set_nested_keeps_string()
    test_set_nested_overwrites_existing()
    test_round_trip_get_set()
    test_cmd_status_outputs_model_info()
    print("All CLI helper tests passed!")
