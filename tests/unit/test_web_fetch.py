"""Tests for the web_fetch tool."""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from tools.web_tools import web_fetch


class _FakeResponse:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self._status = status

    def raise_for_status(self) -> None:
        if self._status >= 400:
            raise RuntimeError(f"HTTP {self._status}")


def _fake_agent(aux_available: bool = False, extract_text: str | None = None):
    """Build a fake agent context for web_fetch."""
    agent = MagicMock()
    agent.auxiliary.is_available.return_value = aux_available
    if extract_text is not None:
        agent.auxiliary.extract_text.return_value = extract_text
    return agent


def test_web_fetch_returns_error_on_failure():
    with patch("tools.web_tools.httpx.get", side_effect=RuntimeError("boom")):
        result = web_fetch("http://example.com")
    assert "Error fetching" in result
    assert "boom" in result


def test_web_fetch_strips_html_without_auxiliary():
    html = "<html><body><h1>Title</h1><p>Content here</p></body></html>"
    fake_ctx = MagicMock()
    fake_ctx.get.return_value = None
    with patch("tools.web_tools.httpx.get", return_value=_FakeResponse(html)):
        with patch("run_agent._current_agent", fake_ctx):
            result = web_fetch("http://example.com")
    assert "Title" in result
    assert "Content here" in result
    assert "<html>" not in result


def test_web_fetch_uses_auxiliary_when_available():
    html = "<html><body>noise</body></html>"
    agent = _fake_agent(aux_available=True, extract_text="clean text")
    fake_ctx = MagicMock()
    fake_ctx.get.return_value = agent
    with patch("tools.web_tools.httpx.get", return_value=_FakeResponse(html)):
        with patch("run_agent._current_agent", fake_ctx):
            result = web_fetch("http://example.com")
    assert result == "clean text"
    agent.auxiliary.extract_text.assert_called_once_with(html)


def test_web_fetch_respects_max_chars():
    long_text = "x" * 5000
    fake_ctx = MagicMock()
    fake_ctx.get.return_value = None
    with patch("tools.web_tools.httpx.get", return_value=_FakeResponse(long_text)):
        with patch("run_agent._current_agent", fake_ctx):
            result = web_fetch("http://example.com", max_chars=100)
    assert len(result) <= 100 + len("\n...[truncated]")
    assert "truncated" in result


def test_web_fetch_falls_back_to_strip_when_auxiliary_missing_attr():
    html = "<p>fallback</p>"
    agent = MagicMock(spec=[])  # no auxiliary attr
    fake_ctx = MagicMock()
    fake_ctx.get.return_value = agent
    with patch("tools.web_tools.httpx.get", return_value=_FakeResponse(html)):
        with patch("run_agent._current_agent", fake_ctx):
            result = web_fetch("http://example.com")
    assert "fallback" in result


if __name__ == "__main__":
    test_web_fetch_returns_error_on_failure()
    test_web_fetch_strips_html_without_auxiliary()
    test_web_fetch_uses_auxiliary_when_available()
    test_web_fetch_respects_max_chars()
    test_web_fetch_falls_back_to_strip_when_auxiliary_missing_attr()
    print("All web_fetch tests passed!")
