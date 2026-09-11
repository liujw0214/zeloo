"""Suppress mouse tracking residue in terminal.

Send ANSI escape codes to disable mouse tracking before TUI starts,
preventing ghost mouse cursor from appearing in terminal scrollback.

This module handles terminal mouse tracking cleanup for both POSIX
systems (using ANSI escape codes) and Windows (using console API).
"""

from __future__ import annotations

import os
import sys
from typing import Optional


DISABLE_MOUSE_TRACKING = (
    "\x1b[?1003l"
    "\x1b[?1006l"
    "\x1b[?1015l"
    "\x1b[?1000l"
    "\x1b[?1002l"
)


def suppress_mouse_residue() -> bool:
    """Send ANSI codes to disable mouse tracking.

    Must be called BEFORE any terminal output when starting TUI.
    This function attempts to disable all mouse tracking modes
    that may leave visual artifacts in the terminal.

    Returns:
        True if codes were sent successfully, False if not applicable
        or if operation failed.

    Note:
        This function requires stdout to be a valid TTY with a fileno().
        If stdout is redirected or not available, returns False.
    """
    if not hasattr(sys.stdout, "fileno"):
        return False

    if not sys.stdout.isatty() and not sys.stderr.isatty():
        return False

    try:
        fd = sys.stdout.fileno()
    except (AttributeError, OSError):
        return False

    if fd < 0:
        return False

    try:
        os.write(fd, DISABLE_MOUSE_TRACKING.encode())
        return True
    except OSError:
        return False


def suppress_mouse_residue_early() -> bool:
    """Early suppression: write to /dev/tty or CONOUT$ on Windows.

    Use when stdout might be redirected or unavailable.
    This function directly accesses the terminal device to send
    the disable codes, bypassing stdout/stderr.

    Returns:
        True if codes were sent successfully, False otherwise.
    """
    if sys.platform == "win32":
        return _suppress_windows_early()
    else:
        return _suppress_posix_early()


def _suppress_windows_early() -> bool:
    """Send mouse tracking disable codes using Windows Console API.

    Opens the console output device directly (CONOUT$) and writes
    the ANSI escape sequence to disable mouse tracking.

    Returns:
        True if successful, False on any error.
    """
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        GENERIC_WRITE = 0x40000000
        FILE_SHARE_WRITE = 0x2
        OPEN_EXISTING = 3
        CONOUT = -12

        h = kernel32.CreateFileW(
            "CONOUT$",
            GENERIC_WRITE,
            FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None
        )

        if h == -1 or h == wintypes.HANDLE(-1).value:
            return False

        try:
            encoded = DISABLE_MOUSE_TRACKING.encode("utf-8")
            written = ctypes.c_ulong()
            success = kernel32.WriteFile(
                h,
                encoded,
                len(encoded),
                ctypes.byref(written),
                None
            )
            return bool(success)
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        return False


def _suppress_posix_early() -> bool:
    """Send mouse tracking disable codes using /dev/tty.

    Opens the controlling terminal device directly and writes
    the ANSI escape sequence to disable mouse tracking.

    Returns:
        True if successful, False otherwise.
    """
    try:
        fd = os.open("/dev/tty", os.O_WRONLY)
        try:
            os.write(fd, DISABLE_MOUSE_TRACKING.encode())
            return True
        finally:
            os.close(fd)
    except OSError:
        return False


def check_mouse_tracking_active() -> bool:
    """Check if mouse tracking might be active in the terminal.

    This is a heuristic check that attempts to detect if mouse
    tracking mode is potentially enabled. It's not 100% reliable
    but can help diagnose cursor residue issues.

    Returns:
        True if mouse tracking is possibly active, False otherwise.
    """
    if not hasattr(sys.stdout, "isatty"):
        return False

    if not sys.stdout.isatty() and not sys.stderr.isatty():
        return False

    return True


def get_terminal_type() -> str:
    """Get the terminal type identifier.

    Attempts to determine the terminal emulator being used
    based on common environment variables.

    Returns:
        Terminal type string (e.g., 'xterm-256color', 'tmux', 'windows'),
        or 'unknown' if unable to determine.
    """
    term = os.environ.get("TERM", "")
    if term:
        if "tmux" in term or "screen" in term:
            return "tmux"
        elif "xterm" in term:
            return "xterm"
        elif "linux" in term:
            return "linux"

    if sys.platform == "win32":
        return "windows"
    elif sys.platform == "darwin":
        return "macos"

    return "unknown"


def send_raw_sequence(fd: int, sequence: str) -> bool:
    """Send a raw escape sequence to a file descriptor.

    Utility function for sending arbitrary ANSI escape sequences
    to a terminal file descriptor.

    Args:
        fd: File descriptor to write to.
        sequence: Escape sequence string to send.

    Returns:
        True if successful, False otherwise.
    """
    try:
        os.write(fd, sequence.encode())
        return True
    except OSError:
        return False


def enable_mouse_tracking() -> bool:
    """Enable mouse tracking mode in terminal.

    Sends ANSI codes to enable common mouse tracking modes.
    This is the inverse of suppress_mouse_residue().

    Returns:
        True if codes were sent successfully, False otherwise.
    """
    if not hasattr(sys.stdout, "fileno"):
        return False

    try:
        fd = sys.stdout.fileno()
        if fd < 0:
            return False
    except (AttributeError, OSError):
        return False

    enable_sequence = (
        "\x1b[?1003h"
        "\x1b[?1006h"
    )

    try:
        os.write(fd, enable_sequence.encode())
        return True
    except OSError:
        return False


def get_mouse_mode_status() -> dict[str, bool]:
    """Get status of various mouse tracking modes.

    Returns a dictionary indicating which mouse tracking modes
    are currently enabled. Note: This is informational only,
    as terminals don't typically provide a way to query this.

    Returns:
        Dictionary with mouse mode names as keys (all False by default,
        as actual detection requires terminal-specific queries).
    """
    return {
        "x10_mouse": False,
        "vt200_mouse": False,
        "normal_mouse": False,
        "button_event_mouse": False,
        "any_event_mouse": False,
    }
