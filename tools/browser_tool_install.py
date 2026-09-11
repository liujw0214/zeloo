"""Browser installation detection and installation utilities.

This module provides functions to check if Playwright and browsers are installed,
and to install them if needed.

Example::

    from tools.browser_tool_install import (
        check_playwright_installed,
        check_chrome_installed,
        install_browsers
    )

    if not check_playwright_installed():
        print("Playwright not installed")
        install_browsers()
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InstallCheckResult:
    """Result of an installation check."""

    is_installed: bool
    version: str | None = None
    path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "is_installed": self.is_installed,
            "version": self.version,
            "path": self.path,
            "error": self.error,
        }


def check_playwright_installed() -> bool:
    """Check if Playwright Python package is installed.

    Returns:
        True if Playwright is installed, False otherwise.
    """
    try:
        import playwright

        return playwright is not None
    except ImportError:
        return False


def get_playwright_version() -> str | None:
    """Get the installed Playwright version.

    Returns:
        Version string if Playwright is installed, None otherwise.
    """
    try:
        import playwright

        return getattr(playwright, "__version__", None)
    except ImportError:
        return None


def check_chrome_installed() -> InstallCheckResult:
    """Check if Google Chrome or Chromium is installed on the system.

    Returns:
        InstallCheckResult with installation status and details.
    """
    result = InstallCheckResult(is_installed=False)

    if sys.platform == "win32":
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
        ]
        for path in chrome_paths:
            expanded_path = subprocess.run(
                ["cmd", "/c", "echo", path],
                capture_output=True,
                text=True,
            ).stdout.strip()
            if shutil.which(expanded_path) or _check_file_exists(expanded_path):
                result.is_installed = True
                result.path = expanded_path
                result.version = _get_file_version(expanded_path)
                return result

    elif sys.platform == "darwin":
        chrome_paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        for path in chrome_paths:
            if _check_file_exists(path):
                result.is_installed = True
                result.path = path
                return result

    else:
        chrome_paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ]
        for path in chrome_paths:
            if shutil.which(path):
                result.is_installed = True
                result.path = path
                result.version = _get_program_version(path)
                return result

    result.error = "Chrome/Chromium not found in standard locations"
    return result


def check_firefox_installed() -> InstallCheckResult:
    """Check if Mozilla Firefox is installed on the system.

    Returns:
        InstallCheckResult with installation status and details.
    """
    result = InstallCheckResult(is_installed=False)

    if sys.platform == "win32":
        firefox_paths = [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ]
        for path in firefox_paths:
            if _check_file_exists(path):
                result.is_installed = True
                result.path = path
                result.version = _get_file_version(path)
                return result

    elif sys.platform == "darwin":
        firefox_path = "/Applications/Firefox.app/Contents/MacOS/firefox"
        if _check_file_exists(firefox_path):
            result.is_installed = True
            result.path = firefox_path
            return result

    else:
        firefox_path = shutil.which("firefox")
        if firefox_path:
            result.is_installed = True
            result.path = firefox_path
            result.version = _get_program_version(firefox_path)
            return result

    result.error = "Firefox not found in standard locations"
    return result


def check_browsers_installed() -> dict[str, InstallCheckResult]:
    """Check all supported browsers for installation status.

    Returns:
        Dictionary mapping browser names to their installation status.
    """
    return {
        "chrome": check_chrome_installed(),
        "firefox": check_firefox_installed(),
    }


def _check_file_exists(path: str) -> bool:
    """Check if a file exists (cross-platform)."""
    import os

    expanded_path = os.path.expandvars(path)
    return os.path.exists(expanded_path)


def _get_file_version(path: str | None) -> str | None:
    """Get version from executable file (Windows)."""
    if path is None or sys.platform != "win32":
        return None

    try:
        import os

        expanded_path = os.path.expandvars(path)
        if not os.path.exists(expanded_path):
            return None

        if sys.platform == "win32":
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
            )
            try:
                version, _ = winreg.QueryValueEx(key, "Version")
                return version
            except FileNotFoundError:
                pass
            finally:
                winreg.CloseKey(key)
    except Exception as e:
        logger.debug("Failed to get file version: %s", e)

    return None


def _get_program_version(program_path: str | None) -> str | None:
    """Get version by running a program with --version flag."""
    if program_path is None:
        return None

    try:
        result = subprocess.run(
            [program_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            output = result.stdout.strip() or result.stderr.strip()
            parts = output.split()
            if len(parts) >= 2:
                return parts[1]
            return output[:50]
    except Exception:
        pass

    return None


def install_playwright() -> dict[str, Any]:
    """Install Playwright Python package via pip.

    Returns:
        Dictionary with success status and details.
    """
    result = {"success": False, "message": "", "error": None}

    try:
        logger.info("Installing Playwright package...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "playwright"],
            check=True,
            capture_output=True,
        )
        result["success"] = True
        result["message"] = "Playwright package installed successfully"
        logger.info("Playwright package installed")
    except subprocess.CalledProcessError as e:
        result["error"] = f"Failed to install Playwright: {e.stderr.decode() if e.stderr else str(e)}"
        logger.error(result["error"])
    except Exception as e:
        result["error"] = f"Unexpected error installing Playwright: {e}"
        logger.exception(result["error"])

    return result


def install_browsers(
    browsers: list[str] | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    """Install Playwright browsers.

    Args:
        browsers: List of browsers to install (chromium, firefox, webkit).
                  If None, installs all browsers.
        timeout: Installation timeout in seconds.

    Returns:
        Dictionary with success status and details.
    """
    result = {"success": False, "installed": [], "failed": [], "error": None}

    if not check_playwright_installed():
        install_result = install_playwright()
        if not install_result["success"]:
            return {
                "success": False,
                "installed": [],
                "failed": ["playwright"],
                "error": f"Cannot install browsers: {install_result['error']}",
            }

    try:
        import subprocess

        cmd = [sys.executable, "-m", "playwright", "install"]
        if browsers:
            cmd.extend(browsers)

        logger.info("Installing Playwright browsers: %s", browsers or "all")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate(timeout=timeout)

        if process.returncode == 0:
            result["success"] = True
            result["installed"] = browsers or ["chromium", "firefox", "webkit"]
            result["message"] = f"Successfully installed: {', '.join(result['installed'])}"
            logger.info("Playwright browsers installed successfully")
        else:
            error_output = stderr.decode() if stderr else "Unknown error"
            result["error"] = f"Installation failed: {error_output}"
            result["failed"] = browsers or ["chromium", "firefox", "webkit"]
            logger.error("Playwright browser installation failed: %s", error_output)

    except subprocess.TimeoutExpired:
        result["error"] = f"Installation timeout after {timeout} seconds"
        logger.error(result["error"])
    except Exception as e:
        result["error"] = f"Unexpected error during browser installation: {e}"
        logger.exception(result["error"])

    return result


def verify_installation() -> dict[str, Any]:
    """Verify that Playwright and at least one browser are properly installed.

    Returns:
        Dictionary with verification results for each component.
    """
    verification = {
        "playwright": check_playwright_installed(),
        "browsers": {},
        "ready": False,
        "errors": [],
    }

    if verification["playwright"]:
        verification["playwright_version"] = get_playwright_version()

        browser_status = check_browsers_installed()
        verification["browsers"] = {k: v.to_dict() for k, v in browser_status.items()}

        has_browser = any(v.is_installed for v in browser_status.values())
        verification["ready"] = has_browser

        if not has_browser:
            verification["errors"].append("No browsers installed. Run install_browsers() to install.")
    else:
        verification["errors"].append("Playwright not installed. Run install_playwright() first.")

    return verification


def get_installation_instructions() -> str:
    """Get platform-specific installation instructions.

    Returns:
        Formatted installation instructions as a string.
    """
    instructions = []

    instructions.append("# Playwright Browser Installation Guide\n")

    instructions.append("## Option 1: Install via pip (Recommended)")
    instructions.append("```bash")
    instructions.append("# Install Playwright Python package")
    instructions.append("pip install playwright")
    instructions.append("")
    instructions.append("# Install browsers (chromium, firefox, webkit)")
    instructions.append("playwright install")
    instructions.append("")
    instructions.append("# Or install specific browsers")
    instructions.append("playwright install chromium")
    instructions.append("```\n")

    if sys.platform == "win32":
        instructions.append("## Windows: Install Chrome/Chromium Manually")
        instructions.append("1. Download Chrome from: https://www.google.com/chrome/")
        instructions.append("2. Run the installer and follow the setup wizard")
        instructions.append("3. Verify installation in default location:")
        instructions.append('   C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe')
        instructions.append("")
    elif sys.platform == "darwin":
        instructions.append("## macOS: Install Chrome/Chromium")
        instructions.append("1. Download Chrome from: https://www.google.com/chrome/")
        instructions.append("2. Drag to Applications folder")
        instructions.append("3. Or install via Homebrew:")
        instructions.append("   brew install --cask google-chrome")
        instructions.append("")
    else:
        instructions.append("## Linux: Install Chrome/Chromium")
        instructions.append("# Debian/Ubuntu:")
        instructions.append("sudo apt-get install -y chromium-browser")
        instructions.append("")
        instructions.append("# Fedora/RHEL:")
        instructions.append("sudo dnf install -y chromium")
        instructions.append("")
        instructions.append("# Or use snap:")
        instructions.append("sudo snap install chromium")
        instructions.append("")

    instructions.append("## Verify Installation")
    instructions.append("```python")
    instructions.append("from tools.browser_tool_install import verify_installation")
    instructions.append("")
    instructions.append("result = verify_installation()")
    instructions.append("print(result)")
    instructions.append("```\n")

    return "\n".join(instructions)
