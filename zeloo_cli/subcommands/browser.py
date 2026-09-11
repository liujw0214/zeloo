"""Zeloo ``browser`` subcommand — browser process management helpers.

Helps the user manage the browser process that holds the "real profile" (the
agent's real browser profile used for browsing with real cookies/sessions).

close-profile: terminates the Chromium-based browser process tree that holds
the real profile, so Zeloo can safely copy/use the profile. DESTRUCTIVE — any
unsaved tabs in that browser are lost.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("browser")
class BrowserCmd(Subcommand):
    name = "browser"
    help = "Browser process management (close real-profile browser)"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="browser_action", help="Browser action")

        close = sub.add_parser(
            "close-profile",
            help="Close the browser holding the real profile "
                 "(loses unsaved tabs — run only after user approval)",
        )
        close.add_argument(
            "--browser",
            choices=["chrome", "edge", "brave", "chromium"],
            default=None,
            help="Browser to close (auto-detected by default)",
        )
        close.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be closed without actually closing",
        )

        sub.add_parser(
            "list-browsers",
            help="List available Chromium-based browsers on this system",
        )
        sub.add_parser(
            "check-profile",
            help="Check if the real browser profile directory is accessible",
        )

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "browser_action", None)
        if action is None:
            self._print_help()
            return 1
        if action == "close-profile":
            return self._close_profile(args)
        if action == "list-browsers":
            return self._list_browsers(args)
        if action == "check-profile":
            return self._check_profile(args)
        self._print_help()
        return 1

    def _print_help(self) -> None:
        print("Usage: zeloo browser [close-profile|list-browsers|check-profile]")
        print("  close-profile   Close the browser holding the real profile")
        print("  list-browsers  Show available Chromium-based browsers")
        print("  check-profile   Check if real profile directory is accessible")

    def _detect_browser(self) -> str | None:
        for candidate in ["chrome", "msedge", "brave", "chromium"]:
            if shutil.which(candidate):
                return candidate
        return None

    def _profile_data_dir(self, browser: str) -> str | None:
        home = Path.home()
        if sys.platform == "darwin":
            if browser == "chrome":
                return str(home / "Library" / "Application Support" / "Google" / "Chrome")
            if browser == "msedge":
                return str(home / "Library" / "Application Support" / "Microsoft Edge")
            if browser == "brave":
                return str(home / "Library" / "Application Support" / "BraveSoftware")
        elif sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA", "")
            base = Path(local) if local else home / "AppData" / "Local"
            if browser == "chrome":
                return str(base / "Google" / "Chrome" / "User Data")
            if browser == "msedge":
                return str(base / "Microsoft" / "Edge" / "User Data")
            if browser == "brave":
                return str(base / "BraveSoftware" / "Brave-Browser" / "User Data")
            if browser == "chromium":
                return str(base / "Chromium" / "User Data")
        else:
            if browser == "chrome":
                return str(home / ".config" / "google-chrome")
            if browser == "msedge":
                return str(home / ".config" / "microsoft-edge")
            if browser == "brave":
                return str(home / ".config" / "Brave-Browser")
            if browser == "chromium":
                return str(home / ".config" / "chromium")
        return None

    def _list_browsers(self, _args: argparse.Namespace) -> int:
        print("\nAvailable Chromium-based browsers:")
        found = False
        for candidate in ["google-chrome", "chrome", "msedge", "microsoft-edge", "brave", "chromium", "firefox"]:
            path = shutil.which(candidate)
            if path:
                print(f"  {candidate:<20}{path}")
                found = True
        if not found:
            print("  No browsers found in PATH")
            print("  (install Chrome, Edge, Brave or Chromium)")
        return 0

    def _check_profile(self, _args: argparse.Namespace) -> int:
        browser = self._detect_browser()
        if browser is None:
            print("No Chromium browser found in PATH.")
            return 1

        profile_path = self._profile_data_dir(browser)
        if profile_path is None:
            print(f"Cannot resolve profile path for: {browser}")
            return 1

        p = Path(profile_path)
        print(f"\nBrowser:     {browser}")
        print(f"Profile dir:  {profile_path}")
        if p.exists():
            size = self._dir_size(p)
            print(f"Exists:       YES ({self._human_size(size)})")
            return 0
        else:
            print(f"Exists:       NO")
            return 1

    def _close_profile(self, args) -> int:
        browser = args.browser or self._detect_browser()
        if browser is None:
            print("No Chromium browser found in PATH.", file=sys.stderr)
            print("Install Chrome, Edge, Brave or Chromium first.", file=sys.stderr)
            return 1

        profile_path = self._profile_data_dir(browser)
        if profile_path is None:
            print(f"Cannot resolve profile path for browser: {browser}", file=sys.stderr)
            return 1

        if args.dry_run:
            print(f"[dry-run] Would close: {browser}")
            print(f"[dry-run] Profile dir: {profile_path}")
            return 0

        p = Path(profile_path)
        if not p.exists():
            print(f"Profile directory does not exist: {profile_path}", file=sys.stderr)
            return 1

        if sys.platform == "win32":
            return self._close_windows(browser)
        elif sys.platform == "darwin":
            return self._close_macos(browser)
        else:
            return self._close_linux(browser)

    def _close_windows(self, browser: str) -> int:
        print(f"Closing {browser}...")
        proc_patterns = {
            "chrome": ["chrome.exe"],
            "msedge": ["msedge.exe"],
            "brave": ["brave.exe"],
            "chromium": ["chromium.exe"],
        }
        patterns = proc_patterns.get(browser, [])

        closed_any = False
        for pattern in patterns:
            try:
                result = subprocess.run(
                    ["taskkill", "/IM", pattern, "/F"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode == 0:
                    print(f"  Closed: {pattern}")
                    closed_any = True
            except Exception as exc:
                print(f"  Failed to close {pattern}: {exc}")

        if closed_any:
            print(f"✓ Browser closed successfully")
            return 0
        else:
            print(f"No {browser} process found", file=sys.stderr)
            return 1

    def _close_macos(self, browser: str) -> int:
        bundle_ids = {
            "chrome": "com.google.Chrome",
            "msedge": "com.microsoft.edgemac",
            "brave": "com.brave.Browser",
            "chromium": "org.chromium.Chromium",
        }
        bundle_id = bundle_ids.get(browser)
        if not bundle_id:
            print(f"Unknown browser: {browser}", file=sys.stderr)
            return 1

        print(f"Closing {browser}...")
        try:
            result = subprocess.run(
                ["osascript", "-e", f'tell application id "{bundle_id}" to quit'],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                print(f"✓ Browser closed successfully")
                return 0
            else:
                print(f"Failed: {result.stderr.strip()}", file=sys.stderr)
                return 1
        except Exception as exc:
            print(f"osascript error: {exc}", file=sys.stderr)
            return 1

    def _close_linux(self, browser: str) -> int:
        print(f"Closing {browser}...")
        try:
            result = subprocess.run(
                ["pkill", "-f", browser],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode in (0, 1):
                print(f"✓ Browser close signal sent")
                return 0
            else:
                print(f"pkill error: {result.stderr.strip()}", file=sys.stderr)
                return 1
        except Exception as exc:
            print(f"Failed: {exc}", file=sys.stderr)
            return 1

    def _dir_size(self, path: Path) -> int:
        total = 0
        try:
            for f in path.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        except PermissionError:
            pass
        return total

    def _human_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if abs(size) < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


from pathlib import Path
