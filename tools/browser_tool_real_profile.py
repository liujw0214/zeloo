"""Browser with real Chrome user profile.

Launch Chrome using the user's actual Chrome profile (cookies, history,
extensions, etc.). This is required when bot detection is aggressive
enough to reject headless / anonymous Chromium builds.

The module never shells out automatically; it only *resolves* the
profile directory and *plans* the launch arguments. Actual process
spawning is the caller's responsibility (so it can plug into the
project's approval / sandbox layers).

Example::

    browser = RealProfileBrowser(browser="chrome")
    profile = browser.find_profile_dir("chrome")
    plan = await browser.launch(headless=False)
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


# Common per-OS profile directories for each supported browser. Values
# are templates; the first existing candidate wins.
_PROFILE_CANDIDATES: dict[str, dict[str, list[str]]] = {
    "chrome": {
        "Windows": [
            r"%LOCALAPPDATA%\Google\Chrome\User Data",
            r"%USERPROFILE%\AppData\Local\Google\Chrome\User Data",
        ],
        "Darwin": [
            "~/Library/Application Support/Google/Chrome",
        ],
        "Linux": [
            "~/.config/google-chrome",
            "~/.config/chromium",
        ],
    },
    "edge": {
        "Windows": [
            r"%LOCALAPPDATA%\Microsoft\Edge\User Data",
        ],
        "Darwin": [
            "~/Library/Application Support/Microsoft Edge",
        ],
        "Linux": [
            "~/.config/microsoft-edge",
        ],
    },
    "brave": {
        "Windows": [
            r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data",
        ],
        "Darwin": [
            "~/Library/Application Support/BraveSoftware/Brave-Browser",
        ],
        "Linux": [
            "~/.config/BraveSoftware/Brave-Browser",
        ],
    },
    "chromium": {
        "Windows": [
            r"%LOCALAPPDATA%\Chromium\User Data",
        ],
        "Darwin": [
            "~/Library/Application Support/Chromium",
        ],
        "Linux": [
            "~/.config/chromium",
        ],
    },
}

# Browser executable locations, keyed by browser/OS.
_EXECUTABLE_CANDIDATES: dict[str, dict[str, list[str]]] = {
    "chrome": {
        "Windows": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
        ],
        "Darwin": [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ],
        "Linux": [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ],
    },
    "edge": {
        "Windows": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ],
        "Darwin": [
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ],
        "Linux": [
            "/usr/bin/microsoft-edge",
            "/usr/bin/microsoft-edge-stable",
        ],
    },
    "brave": {
        "Windows": [
            r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        ],
        "Darwin": [
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ],
        "Linux": [
            "/usr/bin/brave-browser",
            "/usr/bin/brave",
        ],
    },
    "chromium": {
        "Windows": [
            r"%LOCALAPPDATA%\Chromium\Application\chrome.exe",
        ],
        "Darwin": [
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ],
        "Linux": [
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ],
    },
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class LaunchPlan:
    """The resolved launch parameters for a real-profile browser.

    Attributes:
        browser: Browser key (chrome/edge/brave/chromium).
        executable: Resolved path to the browser binary.
        profile_dir: Resolved path to the user profile directory.
        args: Full argument list (without executable).
        working_dir: Optional working directory for the subprocess.
        env: Optional environment overrides.
        session_id: Stable identifier for this plan.
    """

    browser: str
    executable: str
    profile_dir: str
    args: list[str]
    working_dir: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def command_line(self) -> list[str]:
        """Return the full argv ready for ``subprocess.Popen``."""
        return [self.executable, *self.args]


class RealProfileError(RuntimeError):
    """Raised when the browser or profile cannot be located."""


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class RealProfileBrowser:
    """Browser that uses a real Chromium user profile.

    The class encapsulates *resolution* of the profile directory and
    executable path, plus the argument list needed to launch the
    browser. Subclasses (or tests) can override :meth:`launch` to
    actually spawn the process.

    Attributes:
        browser: Browser identifier (one of ``SUPPORTED_BROWSERS``).
        profile_dir: Explicit profile directory override.
    """

    SUPPORTED_BROWSERS: list[str] = ["chrome", "edge", "brave", "chromium"]

    def __init__(
        self,
        browser: str = "chrome",
        profile_dir: str | Path | None = None,
        profile_name: str = "Default",
    ) -> None:
        """Initialize the launcher.

        Args:
            browser: One of ``SUPPORTED_BROWSERS``.
            profile_dir: Override the auto-detected profile directory.
            profile_name: Sub-directory within the profile to use.
        """
        browser_norm = browser.lower().strip()
        if browser_norm not in self.SUPPORTED_BROWSERS:
            raise ValueError(
                f"Unsupported browser {browser!r}. "
                f"Choose one of: {', '.join(self.SUPPORTED_BROWSERS)}"
            )

        self.browser: str = browser_norm
        self.profile_dir: Path | None = (
            Path(profile_dir).expanduser() if profile_dir else None
        )
        self.profile_name: str = profile_name
        self._executable: str | None = None
        self._last_plan: LaunchPlan | None = None

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _expand(path: str) -> str:
        """Expand ``%VAR%`` (Windows) and ``~``/``$VAR`` (POSIX) markers."""
        expanded = os.path.expandvars(os.path.expanduser(path))
        return expanded

    def find_profile_dir(self, browser: str | None = None) -> Path | None:
        """Locate the user's default profile directory.

        Args:
            browser: Override for :attr:`browser`.

        Returns:
            The first existing candidate path, or ``None`` if nothing
            matched.
        """
        target = (browser or self.browser).lower()
        if target not in _PROFILE_CANDIDATES:
            raise RealProfileError(f"Unknown browser {target!r}")

        if self.profile_dir is not None and self.profile_dir.exists():
            return self.profile_dir

        system = platform.system() or ""
        candidates = _PROFILE_CANDIDATES[target].get(system, [])
        for raw in candidates:
            try:
                expanded = Path(self._expand(raw))
            except Exception:  # pragma: no cover - defensive
                continue
            if expanded.exists():
                self.profile_dir = expanded
                return expanded
        return None

    def find_executable(self, browser: str | None = None) -> str | None:
        """Locate the browser binary, falling back to ``PATH`` lookup."""
        target = (browser or self.browser).lower()
        if target not in _EXECUTABLE_CANDIDATES:
            raise RealProfileError(f"Unknown browser {target!r}")

        system = platform.system() or ""
        for raw in _EXECUTABLE_CANDIDATES[target].get(system, []):
            try:
                expanded = self._expand(raw)
            except Exception:  # pragma: no cover - defensive
                continue
            if Path(expanded).exists():
                self._executable = expanded
                return expanded

        # Last-ditch: ask the OS PATH for the binary name.
        names = {
            "chrome": ["google-chrome", "chrome", "chromium"],
            "edge": ["msedge", "microsoft-edge"],
            "brave": ["brave-browser", "brave"],
            "chromium": ["chromium", "chromium-browser"],
        }
        for name in names.get(target, []):
            found = shutil.which(name)
            if found:
                self._executable = found
                return found
        return None

    # ------------------------------------------------------------------
    # Argument synthesis
    # ------------------------------------------------------------------

    def build_launch_args(
        self,
        *,
        headless: bool = False,
        remote_debugging_port: int = 9222,
        start_url: str = "about:blank",
        extra_args: list[str] | None = None,
        no_first_run: bool = True,
        disable_default_apps: bool = True,
    ) -> list[str]:
        """Compose the Chromium argument list.

        Args:
            headless: Use new headless mode when True.
            remote_debugging_port: CDP debug port (0 disables).
            start_url: Initial page to open.
            extra_args: Caller-supplied extra switches.
            no_first_run: Skip the first-run wizard.
            disable_default_apps: Don't restore the default apps.

        Returns:
            The complete argv tail (no executable prefix).
        """
        profile = self.profile_dir or self.find_profile_dir()
        args: list[str] = []
        if profile:
            args.append(f"--user-data-dir={str(profile)}")
            args.append(f"--profile-directory={self.profile_name}")
        if headless:
            args.append("--headless=new")
        if remote_debugging_port:
            args.append(f"--remote-debugging-port={int(remote_debugging_port)}")
        if no_first_run:
            args.append("--no-first-run")
        if disable_default_apps:
            args.append("--disable-default-apps")
        if extra_args:
            args.extend(extra_args)
        if start_url:
            args.append(start_url)
        return args

    # ------------------------------------------------------------------
    # Launch (planning + optional subprocess)
    # ------------------------------------------------------------------

    async def launch(
        self,
        *,
        headless: bool = False,
        remote_debugging_port: int = 9222,
        start_url: str = "about:blank",
        extra_args: list[str] | None = None,
        spawn: bool = False,
        wait_for_debug_port: bool = False,
        wait_timeout: float = 15.0,
    ) -> dict[str, Any]:
        """Plan (and optionally spawn) the browser launch.

        Args:
            headless: Run in new headless mode.
            remote_debugging_port: CDP port to expose.
            start_url: Initial URL.
            extra_args: Extra Chromium switches.
            spawn: If True, actually start the subprocess.
            wait_for_debug_port: If True, poll the debug port until it
                accepts connections (only when ``spawn`` is True).
            wait_timeout: Maximum wait time for the debug port.

        Returns:
            Dict containing the resolved plan. When ``spawn`` is True
            also includes ``pid`` and ``debug_url`` keys.
        """
        exe = self._executable or self.find_executable()
        if not exe:
            raise RealProfileError(
                f"Could not find executable for browser {self.browser!r}. "
                "Set CHROME_PATH / EDGE_PATH / BRAVE_PATH or install the browser."
            )
        profile = self.profile_dir or self.find_profile_dir()
        if not profile:
            logger.warning(
                "real_profile_missing browser=%s — launching without --user-data-dir",
                self.browser,
            )

        args = self.build_launch_args(
            headless=headless,
            remote_debugging_port=remote_debugging_port,
            start_url=start_url,
            extra_args=extra_args,
        )

        plan = LaunchPlan(
            browser=self.browser,
            executable=exe,
            profile_dir=str(profile) if profile else "",
            args=args,
        )
        self._last_plan = plan

        result: dict[str, Any] = {
            "session_id": plan.session_id,
            "browser": plan.browser,
            "executable": plan.executable,
            "profile_dir": plan.profile_dir,
            "args": list(plan.args),
            "spawned": False,
        }

        if not spawn:
            return result

        try:
            proc = subprocess.Popen(  # noqa: S603 — caller opted in
                plan.command_line(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=platform.system() != "Windows",
            )
        except OSError as exc:
            raise RealProfileError(f"Failed to launch {exe}: {exc}") from exc

        result["spawned"] = True
        result["pid"] = int(proc.pid)

        debug_url = ""
        if remote_debugging_port and wait_for_debug_port:
            debug_url = await self._wait_for_debug_port(
                remote_debugging_port, wait_timeout
            )
            result["debug_url"] = debug_url

        # Hand the process off to the caller through the plan metadata.
        result["process_handle"] = proc
        return result

    async def _wait_for_debug_port(self, port: int, timeout: float) -> str:
        """Poll ``http://localhost:<port>/json/version`` until it answers."""
        import socket

        deadline = asyncio.get_event_loop().time() + max(0.0, float(timeout))
        url = f"http://127.0.0.1:{port}/json/version"
        while asyncio.get_event_loop().time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    return url
            except OSError:
                await asyncio.sleep(0.2)
        return ""

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """Return a diagnostic summary (no I/O)."""
        return {
            "browser": self.browser,
            "profile_dir": str(self.profile_dir) if self.profile_dir else None,
            "profile_name": self.profile_name,
            "resolved_executable": self._executable,
            "supported_browsers": list(self.SUPPORTED_BROWSERS),
            "platform": platform.system(),
        }
