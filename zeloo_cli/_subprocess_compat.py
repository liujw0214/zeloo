"""Subprocess compatibility layer for cross-platform process spawning.

Handles differences between Windows/macOS/Linux for subprocess spawning,
providing consistent behavior for creating detached processes and hiding
console windows on Windows platforms.

This module is designed to be imported early in the startup sequence
(before heavy dependencies) to ensure subprocess operations work correctly
across all supported platforms.
"""

from __future__ import annotations

import os
import sys
import subprocess
import signal
from typing import Any, Sequence


if sys.platform == "win32":
    CREATE_NO_WINDOW = 0x08000000
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    DETACHED_PROCESS = 0x00000008
else:
    CREATE_NO_WINDOW = 0
    CREATE_NEW_PROCESS_GROUP = 0
    DETACHED_PROCESS = 0


def _get_platform_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Apply platform-specific subprocess flags to kwargs."""
    kwargs = kwargs.copy()
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)
        kwargs.setdefault("startupinfo", _create_startupinfo())
    return kwargs


def _create_startupinfo() -> subprocess.STARTUPINFO:
    """Create STARTUPINFO with hidden window flag for Windows."""
    if sys.platform != "win32":
        return None
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        return startupinfo
    except (AttributeError, OSError):
        return None


def run(
    args: str | Sequence[str],
    **kwargs: Any
) -> subprocess.CompletedProcess[bytes]:
    """Cross-platform subprocess.run with hidden console on Windows.

    Executes the command described by args and waits for it to complete,
    then returns a CompletedProcess instance with hidden console window
    support on Windows platforms.

    Args:
        args: Command to execute, either as string or sequence of arguments.
        **kwargs: Additional keyword arguments passed to subprocess.run.

    Returns:
        CompletedProcess instance with returncode, stdout, and stderr attributes.

    Example:
        >>> result = run(["echo", "hello"], capture_output=True)
        >>> print(result.stdout.decode())
    """
    merged_kwargs = _get_platform_kwargs(kwargs)
    return subprocess.run(args, **merged_kwargs)


def Popen(
    args: str | Sequence[str],
    **kwargs: Any
) -> subprocess.Popen[bytes]:
    """Cross-platform subprocess.Popen with hidden console on Windows.

    Creates a new process and returns a Popen object for interacting with it.
    Automatically applies Windows-specific flags to hide console windows.

    Args:
        args: Command to execute, either as string or sequence of arguments.
        **kwargs: Additional keyword arguments passed to subprocess.Popen.

    Returns:
        Popen object for the spawned process.

    Example:
        >>> proc = Popen(["python", "--version"], stdout=subprocess.PIPE)
        >>> output, _ = proc.communicate()
    """
    merged_kwargs = _get_platform_kwargs(kwargs)
    return subprocess.Popen(args, **merged_kwargs)


def detach(
    args: str | Sequence[str],
    **kwargs: Any
) -> int:
    """Spawn a fully detached process (daemonize on Unix, no window on Windows).

    Creates a subprocess that is completely detached from the parent process,
    allowing it to run independently. On Unix systems, the child process is
    dissociated from the controlling terminal. On Windows, the console window
    is hidden.

    Args:
        args: Command to execute, either as string or sequence of arguments.
        **kwargs: Additional keyword arguments passed to subprocess.Popen.

    Returns:
        Process ID (PID) of the spawned process on success, -1 on failure.

    Example:
        >>> pid = detach(["python", "-m", "http.server", "8080"])
        >>> if pid > 0:
        ...     print(f"Started server with PID: {pid}")
    """
    kwargs = kwargs.copy()

    if sys.platform == "win32":
        kwargs.setdefault("creationflags", CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS)
        kwargs.setdefault("startupinfo", _create_startupinfo())
        kwargs.setdefault("stdin", subprocess.DEVNULL)
        kwargs.setdefault("stdout", subprocess.DEVNULL)
        kwargs.setdefault("stderr", subprocess.DEVNULL)
    else:
        kwargs.setdefault("stdin", subprocess.DEVNULL)
        kwargs.setdefault("stdout", subprocess.DEVNULL)
        kwargs.setdefault("stderr", subprocess.DEVNULL)

        def setsid() -> None:
            try:
                os.setsid()
            except OSError:
                pass

        kwargs["preexec_fn"] = setsid

    try:
        process = subprocess.Popen(args, **kwargs)
        return process.pid
    except OSError:
        return -1


def suppress_console() -> bool:
    """Attempt to suppress the console window on Windows (pythonw compatibility).

    Uses Windows API calls to hide the console window by modifying the
    extended window styles. This is useful when running Python scripts
    that should not display a console window.

    Returns:
        True if console suppression was attempted successfully or
        platform is not Windows, False if the operation failed.

    Note:
        This function requires ctypes and Windows API access.
        On non-Windows platforms, it returns True immediately.
    """
    if sys.platform != "win32":
        return True

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        SW_HIDE = 0
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        SWP_NOACTIVATE = 0x0010
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_HIDEWINDOW = 0x0080

        GetConsoleWindow = kernel32.GetConsoleWindow
        SetWindowLong = user32.SetWindowLongW
        SetWindowPos = user32.SetWindowPos

        hwnd = GetConsoleWindow()
        if hwnd:
            SetWindowLong(hwnd, GWL_EXSTYLE, WS_EX_TOOLWINDOW)
            SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_HIDEWINDOW | SWP_NOACTIVATE)

        return True
    except (OSError, ImportError, AttributeError):
        return False


def is_windows() -> bool:
    """Check if the current platform is Windows.

    Returns:
        True if running on Windows, False otherwise.
    """
    return sys.platform == "win32"


def get_platform_name() -> str:
    """Get human-readable platform name.

    Returns:
        String describing the platform: 'windows', 'darwin', or 'linux'.
    """
    if sys.platform == "win32":
        return "windows"
    elif sys.platform == "darwin":
        return "darwin"
    else:
        return "linux"
