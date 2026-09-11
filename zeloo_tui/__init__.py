"""Zeloo TUI — Textual-based terminal UI for the agent runtime.

This package is a thin consumer of the ``tui_gateway`` event stream; it
never invokes the LLM directly. See ``docs/55-tui-rendering.md`` for
the architecture overview.

Public surface
--------------

* :func:`is_textual_available` — feature probe
* :func:`make_app` — factory that returns a configured Textual App
  (passive observer or interactive chat) without monkey-patching
* :func:`launch` — convenience wrapper that builds the app and runs it
* :func:`run_with_demo` — context manager that starts the demo emitter
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)


def is_textual_available() -> bool:
    """Return True iff the ``textual`` package is importable."""
    try:
        import textual  # noqa: F401
        return True
    except ImportError:
        return False


@contextmanager
def run_with_demo() -> Any:
    """Start the synthetic event emitter for ``--demo`` runs.

    Yields nothing; cleans up the daemon thread on exit. Use as::

        with run_with_demo():
            app.run()
    """
    from zeloo_tui.cli import start_demo_emitter

    if not is_textual_available():
        yield
        return
    start_demo_emitter()
    try:
        yield
    finally:
        # The emitter is a daemon thread — it dies with the process.
        # We don't join() because textual's run loop should control
        # the lifetime; cleanup is best-effort.
        pass


def _install_on_exit_hook(app: Any, callback: Callable[[], None]) -> None:
    """Install a callback fired after the textual App's ``on_unmount``.

    The original implementation monkey-patched ``type(app).on_unmount``
    which leaks across instances. We instead replace the bound method
    on this single instance only.
    """
    original = app.on_unmount

    async def _wrapped() -> None:
        await original()
        try:
            callback()
        except Exception:  # noqa: BLE001
            logger.exception("on_exit callback raised")

    app.on_unmount = _wrapped  # type: ignore[method-assign]


def make_app(*, chat_mode: bool = False, log_level: str = "WARNING") -> Any:
    """Construct the configured Textual App instance.

    Args:
        chat_mode: When True, return the interactive
            :class:`ZelooTUIChatApp` (history + slash completion);
            otherwise return the passive observer
            :class:`ZelooTUIApp`.
        log_level: Passed through to the App for its logger.
    """
    if chat_mode:
        from zeloo_tui.chat_app import ZelooTUIChatApp

        return ZelooTUIChatApp(log_level=log_level)

    from zeloo_tui.app import ZelooTUIApp

    return ZelooTUIApp(log_level=log_level)


def launch(
    *,
    demo: bool = False,
    log_level: str = "WARNING",
    chat_mode: bool = False,
    on_exit: Callable[[], None] | None = None,
) -> int:
    """Launch the Zeloo textual UI.

    Args:
        demo: When True, inject a synthetic event stream so the UI is
            usable without configuring an LLM key.
        log_level: Logging verbosity for the textual logger.
        chat_mode: When True, use the interactive chat App (history +
            slash completion) instead of the passive observer.
        on_exit: Optional callback invoked just before the textual app
            exits (useful for tests).

    Returns:
        Process-style exit code. 0 on clean exit, 1 if textual is
        unavailable.
    """
    if not is_textual_available():
        return _print_install_hint()

    ctx = run_with_demo() if demo else _nullcontext()
    with ctx:
        app = make_app(chat_mode=chat_mode, log_level=log_level)
        if on_exit is not None:
            _install_on_exit_hook(app, on_exit)
        app.run()
    return 0


@contextmanager
def _nullcontext() -> Any:
    yield


def _print_install_hint() -> int:
    print(
        "The TUI requires the 'textual' package.\n"
        "Install with:  uv pip install textual\n"
        "or:            pip install textual"
    )
    return 1


__all__ = [
    "is_textual_available",
    "make_app",
    "launch",
    "run_with_demo",
]