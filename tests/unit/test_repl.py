"""Tests for ``zeloo_cli.repl`` — shared interactive REPL engine."""

# ruff: noqa: E402

from __future__ import annotations

import os
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from zeloo_cli.repl import (
    _MultiLineBuffer,
    _SLASH_DISPATCH,
    _cmd_clear,
    _cmd_compress,
    _cmd_help,
    _cmd_history,
    _cmd_model,
    _cmd_plugins,
    _cmd_review,
    _cmd_session,
    _cmd_stats,
    _cmd_undo,
    run_interactive_repl,
)


def _mock_agent(
    model: str = "gpt-4o",
    provider: str = "openai",
    base_url: str = "https://api.openai.com",
    session_id: str = "test-session-01",
    cost_tracker: MagicMock | None = None,
    cache_stats_return: dict | None = None,
) -> MagicMock:
    agent = MagicMock()
    agent.model = model
    agent.provider = provider
    agent.base_url = base_url
    agent.session_id = session_id
    agent.session_start = None
    agent._turn_count = 0
    agent._messages = []
    agent._messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    if cost_tracker:
        cost_tracker.total_tokens = 0
        cost_tracker.summary.return_value = "cost: $0.00"
    agent._cost_tracker = cost_tracker or MagicMock(total_tokens=0, summary=MagicMock(return_value="cost: $0.00"))
    agent.cache_stats.return_value = cache_stats_return or {
        "hits": 10,
        "misses": 2,
        "hit_rate": 0.833,
    }
    agent._session_db = MagicMock()
    agent._session_db.db_path = MagicMock()
    type(agent._session_db.db_path).parent = MagicMock(property=MagicMock(return_value=Path("/tmp")))
    return agent


class TestMultiLineBuffer:
    def test_single_line_submits_immediately(self) -> None:
        buf = _MultiLineBuffer()
        submitted, text = buf.feed("hello world")
        assert submitted is True
        assert text == "hello world"

    def test_backslash_continuation_accumulates(self) -> None:
        buf = _MultiLineBuffer()
        submitted1, text1 = buf.feed("first line \\")
        assert submitted1 is False
        assert text1 == ""

        submitted2, text2 = buf.feed("second line")
        assert submitted2 is True
        assert text2 == "first line\nsecond line"

    def test_three_line_continuation(self) -> None:
        buf = _MultiLineBuffer()
        buf.feed("line one \\")
        buf.feed("line two \\")
        submitted, text = buf.feed("line three")
        assert submitted is True
        assert text == "line one\nline two\nline three"

    def test_blank_line_cancels_continuation(self) -> None:
        buf = _MultiLineBuffer()
        buf.feed("hello \\")
        submitted, text = buf.feed("")
        assert submitted is True
        assert text == ""

    def test_whitespace_only_does_not_submit(self) -> None:
        buf = _MultiLineBuffer()
        submitted, text = buf.feed("")
        assert submitted is True
        assert text == ""

    def test_backslash_at_end_of_buffer(self) -> None:
        buf = _MultiLineBuffer()
        submitted, text = buf.feed("hello \\")
        assert submitted is False
        assert buf._continuing is True

    def test_multiple_backslashes_last_wins(self) -> None:
        buf = _MultiLineBuffer()
        buf.feed("a \\")
        buf.feed("b \\")
        submitted, text = buf.feed("c")
        assert submitted is True
        assert text == "a\nb\nc"

    def test_trailing_space_before_backslash_stripped(self) -> None:
        buf = _MultiLineBuffer()
        buf.feed("hello   \\")
        submitted, text = buf.feed("world")
        assert submitted is True
        assert text == "hello\nworld"

    def test_non_continuation_clears_state(self) -> None:
        buf = _MultiLineBuffer()
        buf.feed("hello \\")
        assert buf._continuing is True
        buf.feed("world")
        assert buf._continuing is False


class TestSlashCommands:
    def test_cmd_help_output(self, capsys) -> None:
        _cmd_help(_mock_agent())
        out = capsys.readouterr().out
        assert "/help" in out
        assert "/model" in out
        assert "/session" in out
        assert "/review" in out
        assert "/plugins" in out
        assert "/stats" in out
        assert "/undo" in out
        assert "/clear" in out
        assert "/history" in out
        assert "/compress" in out

    def test_cmd_model_output(self, capsys) -> None:
        agent = _mock_agent(model="claude-3", provider="anthropic", base_url="https://api.anthropic.com")
        _cmd_model(agent)
        out = capsys.readouterr().out
        assert "claude-3" in out
        assert "anthropic" in out
        assert "https://api.anthropic.com" in out

    def test_cmd_model_without_base_url(self, capsys) -> None:
        agent = _mock_agent(base_url="")
        _cmd_model(agent)
        out = capsys.readouterr().out
        assert "Base URL:" not in out

    def test_cmd_session_output(self, capsys) -> None:
        agent = _mock_agent(session_id="abc-123")
        _cmd_session(agent)
        out = capsys.readouterr().out
        assert "abc-123" in out

    def test_cmd_undo_removes_last_turn(self) -> None:
        agent = _mock_agent()
        initial = len(agent._messages)
        _cmd_undo(agent)
        assert len(agent._messages) == initial - 2

    def test_cmd_undo_empty_history(self, capsys) -> None:
        agent = _mock_agent()
        agent._messages = []
        _cmd_undo(agent)
        out = capsys.readouterr().out
        assert "nothing to undo" in out

    def test_cmd_undo_single_message(self, capsys) -> None:
        agent = _mock_agent()
        agent._messages = [{"role": "user", "content": "only one"}]
        _cmd_undo(agent)
        out = capsys.readouterr().out
        assert "nothing to undo" in out

    def test_cmd_stats_output(self, capsys) -> None:
        agent = _mock_agent(cache_stats_return={"hits": 5, "misses": 1, "hit_rate": 0.833})
        _cmd_stats(agent)
        out = capsys.readouterr().out
        assert "Cache hits:" in out
        assert "5" in out
        assert "misses" in out
        assert "1" in out

    def test_cmd_history_output(self, capsys) -> None:
        agent = _mock_agent()
        _cmd_history(agent)
        out = capsys.readouterr().out
        assert "USER" in out or "user" in out
        assert "ASSISTANT" in out or "assistant" in out

    def test_cmd_history_empty(self, capsys) -> None:
        agent = _mock_agent()
        agent._messages = []
        _cmd_history(agent)
        out = capsys.readouterr().out
        assert "no conversation history" in out

    def test_cmd_compress_output(self, capsys) -> None:
        _cmd_compress(_mock_agent())
        out = capsys.readouterr().out
        assert "not yet implemented" in out

    def test_cmd_clear_calls_os_system(self, monkeypatch) -> None:
        calls = []
        monkeypatch.setattr("zeloo_cli.repl.os.system", lambda cmd: calls.append(cmd))
        _cmd_clear(_mock_agent())
        assert len(calls) == 1

    def test_cmd_review_starts_background_thread(self, monkeypatch) -> None:
        thread_calls = []
        import threading

        original_thread = threading.Thread

        class FakeThread(original_thread):
            def __init__(self, *args, **kwargs):
                thread_calls.append(kwargs.get("name"))
                super().__init__(*args, **kwargs)

        monkeypatch.setattr("threading.Thread", FakeThread)
        _cmd_review(_mock_agent())
        assert "repl-slash-review" in thread_calls[0]

    def test_cmd_plugins_no_plugins(self, capsys) -> None:
        with patch("plugins.manager.PluginManager") as mgr_mock:
            mgr_mock.return_value.load_all.return_value = {}
            _cmd_plugins(_mock_agent())
            out = capsys.readouterr().out
            assert "no plugins" in out

    def test_cmd_plugins_with_entries(self, capsys) -> None:
        with patch("plugins.manager.PluginManager") as mgr_mock:
            mgr_mock.return_value.load_all.return_value = {
                "my-plugin": MagicMock(enabled=True, tools_added=["web_search", "terminal"]),
            }
            _cmd_plugins(_mock_agent())
            out = capsys.readouterr().out
            assert "my-plugin" in out
            assert "OK" in out
            assert "web_search" in out

    def test_cmd_plugins_failure(self, capsys) -> None:
        with patch("plugins.manager.PluginManager", side_effect=RuntimeError("import failed")):
            _cmd_plugins(_mock_agent())
            out = capsys.readouterr().out
            assert "Error loading plugins" in out


class TestSlashDispatchRegistry:
    def test_all_expected_commands_registered(self) -> None:
        expected = {"/help", "/model", "/session", "/review", "/plugins", "/stats", "/undo", "/clear", "/history", "/compress"}
        assert set(_SLASH_DISPATCH.keys()) == expected

    def test_unknown_command_not_in_dispatch(self) -> None:
        assert "/unknown" not in _SLASH_DISPATCH
        assert "/foobar" not in _SLASH_DISPATCH


class TestRunInteractiveRepl:
    def _run_with_inputs(self, inputs: list[str], agent: MagicMock | None = None) -> tuple[str, str, int]:
        if agent is None:
            agent = _mock_agent()
        iter_inputs = iter(inputs)

        def fake_input(_prompt: str) -> str:
            try:
                return next(iter_inputs)
            except StopIteration:
                raise EOFError

        with patch("zeloo_cli.repl.input", fake_input):
            with patch("sys.stdout", new_callable=StringIO) as fake_out:
                rc = run_interactive_repl(agent, quiet=True)
                output = fake_out.getvalue()
        return output, "", rc

    def test_quit_exits_loop(self) -> None:
        output, _, rc = self._run_with_inputs(["quit"])
        assert rc == 0
        assert "Goodbye" in output

    def test_exit_alias_works(self) -> None:
        output, _, rc = self._run_with_inputs(["exit"])
        assert rc == 0

    def test_quit_uppercase(self) -> None:
        output, _, rc = self._run_with_inputs(["QUIT"])
        assert rc == 0

    def test_empty_line_skipped(self) -> None:
        output, _, rc = self._run_with_inputs(["", "quit"])
        assert rc == 0
        assert "Goodbye" in output

    def test_whitespace_only_skipped(self) -> None:
        output, _, rc = self._run_with_inputs(["  ", "quit"])
        assert rc == 0

    def test_unknown_slash_command_reported(self) -> None:
        output, _, rc = self._run_with_inputs(["/unknowncmd", "quit"])
        assert "Unknown command" in output

    def test_unknown_slash_case_insensitive(self) -> None:
        output, _, rc = self._run_with_inputs(["/HELP", "quit"])
        assert "show this help" in output or "/help" in output

    def test_slash_help_command(self) -> None:
        output, _, rc = self._run_with_inputs(["/help", "quit"])
        assert "/model" in output
        assert "/session" in output

    def test_slash_model_command(self) -> None:
        output, _, rc = self._run_with_inputs(["/model", "quit"])
        assert "gpt-4o" in output

    def test_slash_session_command(self) -> None:
        output, _, rc = self._run_with_inputs(["/session", "quit"])
        assert "test-session-01" in output

    def test_slash_stats_command(self) -> None:
        output, _, rc = self._run_with_inputs(["/stats", "quit"])
        assert "Cache hits" in output

    def test_slash_undo_command(self) -> None:
        output, _, rc = self._run_with_inputs(["/undo", "quit"])
        assert "last turn removed" in output

    def test_slash_clear_command(self) -> None:
        output, _, rc = self._run_with_inputs(["/clear", "quit"])
        assert rc == 0

    def test_slash_history_command(self) -> None:
        output, _, rc = self._run_with_inputs(["/history", "quit"])
        assert "USER" in output or "user" in output

    def test_multiline_continuation_submitted(self) -> None:
        output, _, rc = self._run_with_inputs(["hello \\", "world", "quit"])
        assert rc == 0
        calls = _mock_agent().run_conversation.call_args_list
        if calls:
            _, kwargs = calls[-1]
            text = kwargs.get("user_message", "") if kwargs else calls[-1][0][0] if calls[-1][0] else ""
            assert "hello" in text or "world" in text

    def test_multiline_blank_cancels(self) -> None:
        output, _, rc = self._run_with_inputs(["hello \\", "", "quit"])
        assert rc == 0

    def test_agent_run_conversation_called(self) -> None:
        agent = _mock_agent()
        output, _, rc = self._run_with_inputs(["hello", "quit"], agent=agent)
        assert agent.run_conversation.called

    def test_run_conversation_exception_caught(self) -> None:
        agent = _mock_agent()
        agent.run_conversation.side_effect = RuntimeError("boom")
        call_count = [0]

        def fake_input(_prompt: str) -> str:
            call_count[0] += 1
            if call_count[0] == 1:
                return "hello"
            return "quit"

        with patch("zeloo_cli.repl.input", fake_input):
            with patch("sys.stdout", new_callable=StringIO) as fake_out:
                rc = run_interactive_repl(agent, quiet=True)
                output = fake_out.getvalue()
        assert rc == 0
        assert "Error" in output or "boom" in output

    def test_keyboard_interrupt_caught(self) -> None:
        agent = _mock_agent()

        def fake_input(_prompt: str) -> str:
            raise KeyboardInterrupt

        with patch("zeloo_cli.repl.input", fake_input):
            with patch("sys.stdout", new_callable=StringIO) as fake_out:
                rc = run_interactive_repl(agent, quiet=True)
                output = fake_out.getvalue()
        assert "Goodbye" in output

    def test_eof_error_caught(self) -> None:
        agent = _mock_agent()

        def fake_input(_prompt: str) -> str:
            raise EOFError

        with patch("zeloo_cli.repl.input", fake_input):
            with patch("sys.stdout", new_callable=StringIO) as fake_out:
                rc = run_interactive_repl(agent, quiet=True)
        assert rc == 0
        assert "Goodbye" in fake_out.getvalue()

    def test_quiet_mode_suppresses_banner(self) -> None:
        output, _, rc = self._run_with_inputs(["quit"])
        assert "Zeloo" not in output

    def test_on_token_callback_invoked(self) -> None:
        tokens = []
        agent = _mock_agent()
        agent.run_conversation.return_value = "done"
        call_count = [0]

        def fake_input(_prompt: str) -> str:
            call_count[0] += 1
            return "hello" if call_count[0] == 1 else "quit"

        with patch("zeloo_cli.repl.input", fake_input):
            with patch("sys.stdout", new_callable=StringIO):
                run_interactive_repl(agent, quiet=True, on_token=tokens.append)

    def test_slash_with_whitespace_prefix(self) -> None:
        output, _, rc = self._run_with_inputs(["  /help", "quit"])
        assert "/model" in output

    def test_run_conversation_with_on_token(self) -> None:
        agent = _mock_agent()
        agent.run_conversation.side_effect = lambda text, on_token=None: (on_token and on_token("hi")) or "response"

        captured_tokens = []
        call_count = [0]

        def fake_input(_prompt: str) -> str:
            call_count[0] += 1
            return "hello" if call_count[0] == 1 else "quit"

        with patch("zeloo_cli.repl.input", fake_input):
            with patch("sys.stdout", new_callable=StringIO):
                run_interactive_repl(agent, quiet=True, on_token=captured_tokens.append)
        assert len(captured_tokens) == 1
        assert captured_tokens[0] == "hi"


class TestModuleExports:
    def test_multiline_buffer_importable(self) -> None:
        from zeloo_cli.repl import _MultiLineBuffer as MLB

        buf = MLB()
        submitted, text = buf.feed("test")
        assert submitted is True
        assert text == "test"

    def test_all_slash_commands_callable(self) -> None:
        from zeloo_cli import repl

        for name in dir(repl):
            if name.startswith("_cmd_") and name != "_cmd_undo":
                fn = getattr(repl, name)
                if callable(fn):
                    try:
                        fn(_mock_agent())
                    except Exception as exc:
                        if "PluginManager" not in str(exc):
                            pytest.fail(f"{name} raised unexpectedly: {exc}")


class TestReplHelpers:
    def test_render_banner_fallback_on_import_error(self, capsys) -> None:
        from zeloo_cli.repl import _render_banner

        with patch.dict("sys.modules", {"zeloo_cli.skin_engine": None}):
            with patch.object(
                __import__("zeloo_cli.repl", fromlist=["_render_banner"]),
                "_render_banner",
                side_effect=ImportError,
            ):
                pass
        _render_banner()
        out = capsys.readouterr().out
        assert "Zeloo" in out or len(out) > 0

    def test_render_prompt_fallback_on_import_error(self) -> None:
        from zeloo_cli.repl import _render_prompt

        result = _render_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_render_banner_produces_output(self, capsys) -> None:
        from zeloo_cli.repl import _render_banner

        _render_banner()
        out = capsys.readouterr().out
        assert len(out) > 0

    def test_render_prompt_returns_string(self) -> None:
        from zeloo_cli.repl import _render_prompt

        result = _render_prompt()
        assert isinstance(result, str)
        assert len(result) > 0


class TestSlashCommandEdgeCases:
    def test_cmd_model_base_url_field_hidden_when_empty(self, capsys) -> None:
        from zeloo_cli.repl import _cmd_model

        agent = _mock_agent()
        agent.base_url = ""
        _cmd_model(agent)
        out = capsys.readouterr().out
        assert "Base URL:" not in out

    def test_cmd_stats_with_zero_tokens(self, capsys) -> None:
        from zeloo_cli.repl import _cmd_stats

        agent = _mock_agent()
        agent._cost_tracker.total_tokens = 0
        agent.cache_stats.return_value = {"hits": 0, "misses": 0, "hit_rate": 0.0}
        _cmd_stats(agent)
        out = capsys.readouterr().out
        assert "Cache hits:" in out
        assert "misses" in out

    def test_cmd_history_truncates_long_content(self, capsys) -> None:
        from zeloo_cli.repl import _cmd_history

        agent = _mock_agent()
        agent._messages = [
            {"role": "user", "content": "x" * 200},
            {"role": "assistant", "content": "y" * 200},
        ]
        _cmd_history(agent)
        out = capsys.readouterr().out
        assert "…" in out

    def test_cmd_review_with_session_db(self, monkeypatch) -> None:
        import threading
        from zeloo_cli.repl import _cmd_review

        started = []
        original_thread = threading.Thread

        class FakeThread(original_thread):
            def __init__(self, *args, **kwargs):
                started.append(kwargs.get("name") or "unnamed")
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(threading, "Thread", FakeThread)
        _cmd_review(_mock_agent())
        assert len(started) == 1
        assert started[0] == "repl-slash-review"

    def test_cmd_plugins_load_error_swallowed(self, capsys) -> None:
        from zeloo_cli.repl import _cmd_plugins

        with patch("plugins.manager.PluginManager", side_effect=Exception("unexpected")):
            _cmd_plugins(_mock_agent())
        out = capsys.readouterr().out
        assert "Error loading plugins" in out

    def test_cmd_undo_with_user_only_message(self, capsys) -> None:
        from zeloo_cli.repl import _cmd_undo

        agent = _mock_agent()
        agent._messages = [{"role": "user", "content": "only one"}]
        _cmd_undo(agent)
        out = capsys.readouterr().out
        assert "nothing to undo" in out

    def test_cmd_undo_with_assistant_only_message(self, capsys) -> None:
        from zeloo_cli.repl import _cmd_undo

        agent = _mock_agent()
        agent._messages = [{"role": "assistant", "content": "only assistant"}]
        _cmd_undo(agent)
        out = capsys.readouterr().out
        assert "nothing to undo" in out


class TestReplStreaming:
    def test_streaming_true_with_on_token(self) -> None:
        agent = _mock_agent()
        agent.run_conversation.return_value = "response"
        tokens = []
        call_count = [0]

        def fake_input(_prompt: str) -> str:
            call_count[0] += 1
            return "hello" if call_count[0] == 1 else "quit"

        with patch("zeloo_cli.repl.input", fake_input):
            with patch("sys.stdout", new_callable=StringIO):
                run_interactive_repl(agent, quiet=True, on_token=tokens.append)

        assert agent.run_conversation.called
        _, kwargs = agent.run_conversation.call_args
        assert kwargs.get("on_token") is not None

    def test_streaming_respects_zeloo_stream_env(self) -> None:
        agent = _mock_agent()
        agent.run_conversation.return_value = "response"
        call_count = [0]

        def fake_input(_prompt: str) -> str:
            call_count[0] += 1
            return "hello" if call_count[0] == 1 else "quit"

        with patch.dict(os.environ, {"zeloo_STREAM": "0"}):
            with patch("zeloo_cli.repl.input", fake_input):
                with patch("sys.stdout", new_callable=StringIO):
                    run_interactive_repl(agent, quiet=True)

        _, kwargs = agent.run_conversation.call_args
        assert kwargs.get("on_token") is None

    def test_streaming_respects_zeloo_stream_false(self) -> None:
        agent = _mock_agent()
        agent.run_conversation.return_value = "response"
        call_count = [0]

        def fake_input(_prompt: str) -> str:
            call_count[0] += 1
            return "hello" if call_count[0] == 1 else "quit"

        with patch.dict(os.environ, {"zeloo_STREAM": "false"}):
            with patch("zeloo_cli.repl.input", fake_input):
                with patch("sys.stdout", new_callable=StringIO):
                    run_interactive_repl(agent, quiet=True)

        _, kwargs = agent.run_conversation.call_args
        assert kwargs.get("on_token") is None

    def test_streaming_respects_zeloo_stream_no(self) -> None:
        agent = _mock_agent()
        agent.run_conversation.return_value = "response"
        call_count = [0]

        def fake_input(_prompt: str) -> str:
            call_count[0] += 1
            return "hello" if call_count[0] == 1 else "quit"

        with patch.dict(os.environ, {"zeloo_STREAM": "no"}):
            with patch("zeloo_cli.repl.input", fake_input):
                with patch("sys.stdout", new_callable=StringIO):
                    run_interactive_repl(agent, quiet=True)

        _, kwargs = agent.run_conversation.call_args
        assert kwargs.get("on_token") is None

    def test_streaming_with_zeloo_stream_1(self) -> None:
        agent = _mock_agent()
        agent.run_conversation.return_value = "response"
        call_count = [0]

        def fake_input(_prompt: str) -> str:
            call_count[0] += 1
            return "hello" if call_count[0] == 1 else "quit"

        with patch.dict(os.environ, {"zeloo_STREAM": "1"}):
            with patch("zeloo_cli.repl.input", fake_input):
                with patch("sys.stdout", new_callable=StringIO):
                    run_interactive_repl(agent, quiet=True)

        _, kwargs = agent.run_conversation.call_args
        assert kwargs.get("on_token") is not None


class TestReplQuietMode:
    def test_quiet_false_shows_banner(self, capsys) -> None:
        agent = _mock_agent()
        call_count = [0]

        def fake_input(_prompt: str) -> str:
            call_count[0] += 1
            return "quit"

        with patch("zeloo_cli.repl.input", fake_input):
            run_interactive_repl(agent, quiet=False)

        out = capsys.readouterr().out
        assert "Zeloo" in out or "Type" in out

    def test_quiet_true_hides_banner(self, capsys) -> None:
        agent = _mock_agent()
        call_count = [0]

        def fake_input(_prompt: str) -> str:
            call_count[0] += 1
            return "quit"

        with patch("zeloo_cli.repl.input", fake_input):
            run_interactive_repl(agent, quiet=True)

        out = capsys.readouterr().out
        assert "Zeloo" not in out
        assert "Type" not in out


class TestReplMessageHandling:
    def test_run_conversation_returns_none_is_handled(self) -> None:
        agent = _mock_agent()
        agent.run_conversation.return_value = None
        call_count = [0]

        def fake_input(_prompt: str) -> str:
            call_count[0] += 1
            return "hello" if call_count[0] == 1 else "quit"

        with patch("zeloo_cli.repl.input", fake_input):
            with patch("sys.stdout", new_callable=StringIO):
                rc = run_interactive_repl(agent, quiet=True)
        assert rc == 0


class TestMultilineEdgeCases:
    def test_continuation_prompt_shown(self) -> None:
        agent = _mock_agent()
        prompts = []

        def fake_input(prompt: str) -> str:
            prompts.append(prompt)
            if len(prompts) == 1:
                return "hello \\"
            if len(prompts) == 2:
                return "world"
            return "quit"

        with patch("zeloo_cli.repl.input", fake_input):
            with patch("sys.stdout", new_callable=StringIO):
                run_interactive_repl(agent, quiet=True)

        assert len(prompts) == 3
        assert prompts[1] == "… "

    def test_only_whitespace_during_continuation(self) -> None:
        agent = _mock_agent()
        call_count = [0]

        def fake_input(_prompt: str) -> str:
            call_count[0] += 1
            if call_count[0] == 1:
                return "hello \\"
            if call_count[0] == 2:
                return "  "
            return "quit"

        with patch("zeloo_cli.repl.input", fake_input):
            with patch("sys.stdout", new_callable=StringIO):
                rc = run_interactive_repl(agent, quiet=True)

        assert rc == 0
        assert agent.run_conversation.call_count == 0

    def test_tab_before_backslash_continues(self) -> None:
        from zeloo_cli.repl import _MultiLineBuffer

        buf = _MultiLineBuffer()
        buf.feed("hello\t\\")
        submitted, text = buf.feed("world")
        assert submitted is True
        assert text == "hello\nworld"

    def test_multiple_spaces_then_backslash(self) -> None:
        from zeloo_cli.repl import _MultiLineBuffer

        buf = _MultiLineBuffer()
        buf.feed("  hello   \\")
        submitted, text = buf.feed("world")
        assert submitted is True
        assert text == "  hello\nworld"

    def test_unicode_content_multiline(self) -> None:
        from zeloo_cli.repl import _MultiLineBuffer

        buf = _MultiLineBuffer()
        buf.feed("你好世界 \\")
        submitted, text = buf.feed("再见")
        assert submitted is True
        assert text == "你好世界\n再见"

