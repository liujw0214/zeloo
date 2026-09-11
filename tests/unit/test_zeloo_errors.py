"""Tests for the unified Zeloo error hierarchy."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.zeloo_errors import (  # noqa: E402
    AuthError,
    ConfigError,
    CronError,
    ErrorCode,
    GatewayError,
    MCPError,
    MemoryError,
    NetworkError,
    ProviderError,
    SkillError,
    ToolError,
    ZelooError,
)


# --------------------------------------------------------------------------- #
# 1. ErrorCode enum
# --------------------------------------------------------------------------- #


def test_error_codes_are_strings():
    for code in ErrorCode:
        assert isinstance(code.value, str)
        assert code.value.startswith("E0")


def test_error_code_values_match_convention():
    assert ErrorCode.CONFIG.value == "E001"
    assert ErrorCode.AUTH.value == "E002"
    assert ErrorCode.NETWORK.value == "E003"
    assert ErrorCode.PROVIDER.value == "E004"
    assert ErrorCode.TOOL.value == "E005"
    assert ErrorCode.MEMORY.value == "E006"
    assert ErrorCode.SKILL.value == "E007"
    assert ErrorCode.CRON.value == "E008"
    assert ErrorCode.MCP.value == "E009"
    assert ErrorCode.GATEWAY.value == "E010"


def test_error_code_membership():
    assert "E001" in {c.value for c in ErrorCode}


def test_error_code_iteration_count():
    assert len(list(ErrorCode)) == 10


# --------------------------------------------------------------------------- #
# 2. ZelooError base behaviour
# --------------------------------------------------------------------------- #


def test_zeloo_error_is_exception():
    err = ZelooError("boom")
    assert isinstance(err, Exception)
    assert "boom" in str(err)


def test_zeloo_error_includes_code_in_str():
    err = ZelooError("bad", code=ErrorCode.NETWORK)
    assert "[E003]" in str(err)


def test_zeloo_error_to_dict_shape():
    err = ZelooError("oops", details={"k": "v"})
    data = err.to_dict()
    assert data == {
        "error_class": "ZelooError",
        "code": "E001",
        "message": "oops",
        "details": {"k": "v"},
    }


def test_zeloo_error_default_code_is_config():
    err = ZelooError("hi")
    assert err.code is ErrorCode.CONFIG


def test_zeloo_error_empty_message_uses_class_default():
    err = ZelooError()
    # Should not raise; default message is "".
    assert err.message == ""


def test_zeloo_error_with_code_override():
    err = ZelooError("x", code=ErrorCode.MCP)
    assert err.code is ErrorCode.MCP


def test_zeloo_error_details_default_is_empty_dict():
    err = ZelooError("x")
    assert err.details == {}


def test_zeloo_error_details_preserved_in_str():
    err = ZelooError("x", details={"url": "https://x"})
    assert "url" in str(err)


# --------------------------------------------------------------------------- #
# 3. Subclass correctness
# --------------------------------------------------------------------------- #


def test_config_error_default_code():
    err = ConfigError("bad config")
    assert err.code is ErrorCode.CONFIG
    assert isinstance(err, ZelooError)


def test_auth_error_default_code():
    err = AuthError("denied")
    assert err.code is ErrorCode.AUTH
    assert isinstance(err, ZelooError)


def test_network_error_default_code():
    err = NetworkError("timeout")
    assert err.code is ErrorCode.NETWORK


def test_provider_error_default_code():
    err = ProviderError("model down")
    assert err.code is ErrorCode.PROVIDER


def test_tool_error_default_code():
    err = ToolError("tool crashed")
    assert err.code is ErrorCode.TOOL


def test_memory_error_default_code():
    err = MemoryError("corrupt")
    assert err.code is ErrorCode.MEMORY


def test_skill_error_default_code():
    err = SkillError("invalid skill")
    assert err.code is ErrorCode.SKILL


def test_cron_error_default_code():
    err = CronError("schedule invalid")
    assert err.code is ErrorCode.CRON


def test_mcp_error_default_code():
    err = MCPError("protocol error")
    assert err.code is ErrorCode.MCP


def test_gateway_error_default_code():
    err = GatewayError("gateway down")
    assert err.code is ErrorCode.GATEWAY


# --------------------------------------------------------------------------- #
# 4. Catching, polymorphism and serialisation
# --------------------------------------------------------------------------- #


def test_catch_all_subclasses_via_base():
    for cls in (ConfigError, AuthError, NetworkError, ProviderError,
                ToolError, MemoryError, SkillError, CronError,
                MCPError, GatewayError):
        try:
            raise cls("oops")
        except ZelooError as caught:
            assert caught.code is not None
        else:
            raise AssertionError("expected to catch")


def test_to_dict_uses_subclass_name():
    err = ToolError("bad tool")
    data = err.to_dict()
    assert data["error_class"] == "ToolError"
    assert data["code"] == "E005"


def test_to_dict_is_json_safe():
    import json
    err = NetworkError("dns", details={"host": "x"})
    blob = json.dumps(err.to_dict())
    parsed = json.loads(blob)
    assert parsed["code"] == "E003"


def test_error_can_carry_complex_details():
    err = ProviderError("rate limited", details={"retry_after": 30})
    assert err.details["retry_after"] == 30


def test_error_message_inheritance_works():
    err = SkillError("missing frontmatter")
    assert "missing frontmatter" in str(err)
    assert "[E007]" in str(err)


def test_subclass_can_override_code():
    err = ConfigError("custom", code=ErrorCode.NETWORK)
    assert err.code is ErrorCode.NETWORK


def test_raising_zeloo_error_in_try_block():
    caught = None
    try:
        raise MemoryError("oops")
    except ZelooError as exc:
        caught = exc
    assert isinstance(caught, MemoryError)
    assert caught.code is ErrorCode.MEMORY
