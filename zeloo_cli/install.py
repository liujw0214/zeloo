"""Zeloo CLI install — guided installation and setup."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def install(
    target: str = "default",
    interactive: bool = True,
    skip_dependencies: bool = False,
) -> None:
    """Guide the user through installing and configuring Zeloo.

    Args:
        target: Installation target ("default" or "minimal").
        interactive: If True, prompt for user input.
        skip_dependencies: If True, skip dependency checks.
    """
    home = Path.home() / ".Zeloo"
    home.mkdir(exist_ok=True)

    (home / "profile").mkdir(exist_ok=True)
    (home / "memory").mkdir(exist_ok=True)
    (home / "skills").mkdir(exist_ok=True)
    (home / "archive").mkdir(exist_ok=True)

    _install_example_config(home)
    _install_example_memory(home)

    if not skip_dependencies:
        _check_dependencies()

    print(f"Zeloo installed at: {home}")
    print("Next steps:")
    print(f"  1. Edit {home}/.env and add your OPENAI_API_KEY")
    print("  2. Run: Zeloo chat")


def _install_example_config(home: Path) -> None:
    env_path = home / ".env"
    if not env_path.exists():
        content = (
            "# Zeloo Environment Configuration\n"
            "# Copy this to ~/.Zeloo/.env and fill in your values\n\n"
            "OPENAI_API_KEY=sk-your-key-here\n"
            "zeloo_MODEL=gpt-4o\n"
            "zeloo_PROVIDER=openai\n"
            "zeloo_HOME=" + str(home) + "\n"
        )
        env_path.write_text(content, encoding="utf-8")


def _install_example_memory(home: Path) -> None:
    memory_dir = home / "memory"
    (memory_dir / "default").mkdir(exist_ok=True)
    user_md = memory_dir / "default" / "USER.md"
    if not user_md.exists():
        user_md.write_text(
            "# User Profile\n\n[Write your background, preferences, and context here]\n",
            encoding="utf-8",
        )


def _check_dependencies() -> None:
    print("\nChecking dependencies...")
    missing = []

    for pkg, import_name in [
        ("openai", "openai"),
        ("httpx", "httpx"),
        ("pyyaml", "yaml"),
        ("python-dotenv", "dotenv"),
    ]:
        try:
            __import__(import_name)
            print(f"  [OK] {pkg}")
        except ImportError:
            print(f"  [MISSING] {pkg}")
            missing.append(pkg)

    if missing:
        print(f"\nMissing packages: {', '.join(missing)}")
        print(f"Install with: pip install {' '.join(missing)}")


def self_upgrade() -> None:
    """Upgrade Zeloo to the latest version via pip."""
    print("Upgrading Zeloo...")
    result = os.system(f"{sys.executable} -m pip install --upgrade Zeloo")
    if result == 0:
        print("Upgrade complete!")
    else:
        print("Upgrade failed. Check your pip installation.")


def uninstall(confirm: bool = True) -> None:
    """Remove Zeloo from the system."""
    home = Path.home() / ".Zeloo"
    if not home.exists():
        print("Zeloo is not installed.")
        return

    if confirm:
        response = input(f"Remove {home} and all Zeloo data? [y/N] ")
        if response.lower() != "y":
            print("Cancelled.")
            return

    shutil.rmtree(home)
    print(f"Removed {home}")
