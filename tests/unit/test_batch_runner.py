"""Unit tests for scripts/batch_runner.py — prompt loading, batch run, errors."""

# ruff: noqa: E402
from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

import scripts.batch_runner as br

# ── Helpers ──────────────────────────────────────────────────────────


class _MonkeyPatch:
    """Minimal monkeypatch to avoid a pytest dependency."""

    def __init__(self) -> None:
        self._undos: list = []

    def setattr(self, obj, name, value) -> None:
        old = getattr(obj, name)
        self._undos.append(lambda: setattr(obj, name, old))
        setattr(obj, name, value)

    def undo(self) -> None:
        for fn in reversed(self._undos):
            fn()
        self._undos.clear()


def test_load_prompts_from_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "prompts.txt"
        p.write_text("hello\n\nworld\n  \nfoo\n", encoding="utf-8")
        prompts = br._load_prompts(str(p))
    assert prompts == ["hello", "world", "foo"], prompts


def test_load_prompts_missing_file_exits() -> None:
    try:
        br._load_prompts("/nonexistent/path/prompts.txt")
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected SystemExit(1) for missing file")


def test_load_prompts_from_stdin() -> None:
    mp = _MonkeyPatch()
    mp.setattr(sys, "stdin", io.StringIO("line1\n\nline2\n"))
    try:
        prompts = br._load_prompts("-")
    finally:
        mp.undo()
    assert prompts == ["line1", "line2"], prompts


def test_run_batch_success() -> None:
    mock_agent = MagicMock()
    mock_agent.run_conversation.side_effect = ["resp1", "resp2"]

    with patch("scripts.batch_runner.AIAgent", return_value=mock_agent) as mock_cls:
        results = br.run_batch(["p1", "p2"], model="gpt-4o", provider="openai")

    mock_cls.assert_called_once()
    assert mock_agent.run_conversation.call_count == 2
    mock_agent.close.assert_called_once()

    assert len(results) == 2
    assert results[0]["index"] == 1
    assert results[0]["prompt"] == "p1"
    assert results[0]["response"] == "resp1"
    assert results[0]["error"] is None
    assert "elapsed_seconds" in results[0]
    assert results[1]["index"] == 2


def test_run_batch_handles_errors() -> None:
    mock_agent = MagicMock()
    mock_agent.run_conversation.side_effect = [RuntimeError("boom"), "ok"]

    with patch("scripts.batch_runner.AIAgent", return_value=mock_agent):
        results = br.run_batch(["bad", "good"])

    assert len(results) == 2
    assert results[0]["error"] == "boom"
    assert results[0]["response"] == ""
    assert results[1]["error"] is None
    assert results[1]["response"] == "ok"
    mock_agent.close.assert_called_once()


def test_run_batch_sleep_between_prompts() -> None:
    mock_agent = MagicMock()
    mock_agent.run_conversation.return_value = "r"

    with patch("scripts.batch_runner.AIAgent", return_value=mock_agent), \
         patch("scripts.batch_runner.time.sleep") as mock_sleep:
        br.run_batch(["a", "b", "c"], sleep_seconds=1.5)

    # sleep called twice (between a-b and b-c), not after c
    assert mock_sleep.call_count == 2
    mock_sleep.assert_called_with(1.5)


def test_run_batch_empty_prompts() -> None:
    mock_agent = MagicMock()
    with patch("scripts.batch_runner.AIAgent", return_value=mock_agent):
        results = br.run_batch([])
    assert results == []
    mock_agent.close.assert_called_once()


def test_run_batch_passes_params_to_agent() -> None:
    mock_agent = MagicMock()
    with patch("scripts.batch_runner.AIAgent", return_value=mock_agent) as mock_cls:
        br.run_batch(
            ["p"],
            model="gpt-3.5-turbo",
            provider="deepseek",
            base_url="https://api.deepseek.com/v1",
            api_key="sk-test",
            max_iterations=10,
            temperature=0.5,
        )

    kwargs = mock_cls.call_args.kwargs
    assert kwargs["model"] == "gpt-3.5-turbo"
    assert kwargs["provider"] == "deepseek"
    assert kwargs["base_url"] == "https://api.deepseek.com/v1"
    assert kwargs["api_key"] == "sk-test"
    assert kwargs["max_iterations"] == 10
    assert kwargs["temperature"] == 0.5
    assert kwargs["platform"] == "cli"


def test_main_empty_prompts_returns_zero() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "empty.txt"
        p.write_text("\n\n  \n", encoding="utf-8")
        mp = _MonkeyPatch()
        mp.setattr(sys, "argv", ["batch_runner.py", "--input", str(p)])
        try:
            rc = br.main()
        finally:
            mp.undo()
    assert rc == 0


if __name__ == "__main__":
    test_load_prompts_from_file()
    test_load_prompts_missing_file_exits()
    test_load_prompts_from_stdin()
    test_run_batch_success()
    test_run_batch_handles_errors()
    test_run_batch_sleep_between_prompts()
    test_run_batch_empty_prompts()
    test_run_batch_passes_params_to_agent()
    test_main_empty_prompts_returns_zero()
    print("All batch_runner tests passed!")
