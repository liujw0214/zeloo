"""Fast startup path: version check, environment validation, pre-import checks.

Runs BEFORE heavy module imports to fail fast on common errors.
This module is intentionally minimal and synchronous to ensure
quick startup time and early failure detection.

All functions in this module are designed to be called at the
earliest possible point in the CLI startup sequence.
"""

from __future__ import annotations

import os
import sys
import warnings as _warnings
from pathlib import Path
from typing import Optional


MIN_PYTHON_VERSION = (3, 11)
SUPPORTED_PLATFORMS = ("win32", "darwin", "linux")


def try_fast_version() -> bool:
    """Fast path: return True and print version if --version/-V detected.

    Checks sys.argv for version flags and immediately returns True
    if found, allowing the caller to print version and exit without
    loading any additional modules.

    Returns:
        True if --version or -V was found in command line arguments,
        False otherwise.

    Example:
        >>> if try_fast_version():
        ...     print("zeloo version 1.0.0")
        ...     sys.exit(0)
    """
    for arg in sys.argv:
        if arg in ("--version", "-V", "--version-full"):
            return True
    return False


def get_version_info() -> str:
    """Get version information string for display.

    Attempts to import version from zeloo_cli package if available.
    Falls back to 'unknown' if version cannot be determined.

    Returns:
        Version string in format 'X.Y.Z' or 'unknown'.
    """
    try:
        from zeloo_cli import __version__
        return __version__
    except (ImportError, AttributeError):
        try:
            from zeloo_cli.__about__ import __version__
            return __version__
        except (ImportError, AttributeError):
            return "unknown"


def check_python_version() -> tuple[bool, str]:
    """Check Python version meets minimum requirement.

    Validates that the current Python interpreter version is at least
    the minimum required version defined in MIN_PYTHON_VERSION.

    Returns:
        Tuple of (success: bool, message: str).
        If success is False, message contains the error description.

    Example:
        >>> ok, msg = check_python_version()
        >>> if not ok:
        ...     print(f"Error: {msg}", file=sys.stderr)
        ...     sys.exit(1)
    """
    current_version = sys.version_info[:2]
    min_version_str = ".".join(map(str, MIN_PYTHON_VERSION))

    if current_version < MIN_PYTHON_VERSION:
        current_str = ".".join(map(str, current_version))
        message = f"Python {min_version_str}+ required, got {current_str}"
        return False, message

    return True, ""


def check_platform_compatibility() -> tuple[bool, str]:
    """Check if the current platform is supported.

    Validates that the operating system is one of the supported platforms.

    Returns:
        Tuple of (success: bool, message: str).
        If success is False, message contains the error description.
    """
    current_platform = sys.platform

    if current_platform not in SUPPORTED_PLATFORMS:
        supported = ", ".join(SUPPORTED_PLATFORMS)
        message = f"Unsupported platform: {current_platform}. Supported: {supported}"
        return False, message

    return True, ""


def check_project_root() -> bool:
    """Add project root to sys.path if not already present.

    Determines the project root by traversing from this module's location
    up to the parent directory. Adds it to sys.path if not present.

    Returns:
        True if project root was added or already present, False on error.
    """
    try:
        current = Path(__file__).parent.parent
        current_str = str(current.resolve())

        if current_str not in sys.path:
            sys.path.insert(0, current_str)
            return True

        return True
    except (OSError, RuntimeError):
        return False


def get_project_root() -> Optional[Path]:
    """Get the project root directory path.

    Returns:
        Path object pointing to project root, or None if unable to determine.
    """
    try:
        return Path(__file__).parent.parent.resolve()
    except (OSError, RuntimeError):
        return None


def check_critical_env() -> list[str]:
    """Check for missing critical environment variables.

    Validates presence of environment variables that are required
    for proper operation of the CLI application.

    Returns:
        List of warning messages for any missing critical variables.
        Empty list indicates all critical variables are present.
    """
    warnings: list[str] = []

    zeloo_home = os.environ.get("ZELOO_HOME")
    zeloo_home_path = Path.home() / ".Zeloo"

    if not zeloo_home and not zeloo_home_path.exists():
        warnings.append(
            "ZELOO_HOME not set and ~/.Zeloo not found. "
            "Consider setting ZELOO_HOME environment variable."
        )

    if not os.environ.get("PATH"):
        warnings.append("PATH environment variable not set")

    return warnings


def check_optional_env() -> dict[str, str]:
    """Check optional environment variables and return their values.

    Returns a dictionary of optional environment variables that may
    affect application behavior. Missing values are omitted.

    Returns:
        Dictionary mapping variable names to their values.
    """
    optional_vars = [
        "ZELOO_CONFIG",
        "ZELOO_PROFILE",
        "ZELOO_LOG_LEVEL",
        "ZELOO_CACHE_DIR",
        "ZELOO_DATA_DIR",
        "ZELOO_PLUGINS_DIR",
    ]

    result: dict[str, str] = {}
    for var in optional_vars:
        value = os.environ.get(var)
        if value is not None:
            result[var] = value

    return result


def fast_startup_checks() -> Optional[int]:
    """Run all fast checks. Returns exit code if should exit early, None to continue.

    Executes all startup validation checks in sequence:
    1. Version flag detection (exits 0 if found)
    2. Python version validation (exits 1 if fails)
    3. Platform compatibility check (exits 1 if fails)
    4. Project root setup
    5. Critical environment variable validation (warns but continues)

    Returns:
        None if startup should continue, exit code (0 or 1) if should exit early.
        Exit code 0 indicates successful early exit (e.g., version display).
        Exit code 1 indicates validation failure.

    Example:
        >>> exit_code = fast_startup_checks()
        >>> if exit_code is not None:
        ...     sys.exit(exit_code)
    """
    if try_fast_version():
        version = get_version_info()
        print(f"zeloo {version}")
        return 0

    ok, msg = check_python_version()
    if not ok:
        print(msg, file=sys.stderr)
        return 1

    ok, msg = check_platform_compatibility()
    if not ok:
        print(msg, file=sys.stderr)
        return 1

    if not check_project_root():
        _warnings.warn("Failed to add project root to sys.path", stacklevel=2)

    critical_warnings = check_critical_env()
    for warning_msg in critical_warnings:
        _warnings.warn(warning_msg, stacklevel=2)

    return None


def print_startup_banner(verbose: bool = False) -> None:
    """Print startup banner with version and environment info.

    Args:
        verbose: If True, include additional environment information.
    """
    version = get_version_info()
    print(f"Zeloo CLI v{version}")

    if verbose:
        print(f"Python: {sys.version.split()[0]}")
        print(f"Platform: {sys.platform}")

        optional_env = check_optional_env()
        if optional_env:
            print("Environment:")
            for key, value in optional_env.items():
                print(f"  {key}={value}")
