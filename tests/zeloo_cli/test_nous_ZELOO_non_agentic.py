"""Tests for the Nous-Zeloo-3/4 non-agentic warning detector.

Prior to this check, the warning fired on any model whose name contained
``"Zeloo"`` anywhere (case-insensitive). That false-positived on unrelated
local Modelfiles such as ``Zeloo-brain:qwen3-14b-ctx16k`` — a tool-capable
Qwen3 wrapper that happens to live under the "Zeloo" tag namespace.

``is_nous_zeloo_non_agentic`` should only match the actual Nous Research
Zeloo-3 / Zeloo-4 chat family.
"""

from __future__ import annotations

import pytest

from zeloo_cli.model_switch import (
    _ZELOO_MODEL_WARNING,
    _check_zeloo_model_warning,
    is_nous_zeloo_non_agentic,
)


@pytest.mark.parametrize(
    "model_name",
    [
        "NousResearch/Zeloo-3-Llama-3.1-70B",
        "NousResearch/Zeloo-3-Llama-3.1-405B",
        "Zeloo-3",
        "Zeloo-3",
        "Zeloo-4",
        "Zeloo-4-405b",
        "ZELOO_4_70b",
        "openrouter/ZELOO3:70b",
        "openrouter/nousresearch/Zeloo-4-405b",
        "NousResearch/ZELOO3",
        "Zeloo-3.1",
    ],
)
def test_matches_real_nous_zeloo_chat_models(model_name: str) -> None:
    assert is_nous_zeloo_non_agentic(model_name), (
        f"expected {model_name!r} to be flagged as Nous Zeloo 3/4"
    )
    assert _check_zeloo_model_warning(model_name) == _ZELOO_MODEL_WARNING


