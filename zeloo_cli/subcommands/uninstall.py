"""Zeloo ``uninstall`` subcommand — uninstall Zeloo Agent."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("uninstall")
class UninstallCmd(Subcommand):
    name = "uninstall"
    help = "Uninstall Zeloo Agent"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--full", action="store_true",
            help="Complete uninstall (delete config, data, and code)",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview what will be deleted without actually deleting",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Skip confirmation prompt",
        )

    def run(self, args: argparse.Namespace) -> int:
        full = getattr(args, "full", False)
        dry_run = getattr(args, "dry_run", False)
        force = getattr(args, "force", False)

        zeloo_home = self._get_zeloo_home()
        code_dir = self._get_code_dir()

        items_to_delete: list[tuple[str, Path]] = []

        if zeloo_home.exists():
            if full:
                items_to_delete.append(("Zeloo home directory", zeloo_home))
            else:
                items_to_delete.append(("Zeloo config directory", zeloo_home))
        else:
            print("No Zeloo installation found.")
            return 0

        if full and code_dir.exists() and code_dir != zeloo_home:
            items_to_delete.append(("Zeloo code directory", code_dir))

        print("Zeloo Uninstaller")
        print("=" * 50)

        if dry_run:
            print("\n[DRY RUN] The following items would be deleted:\n")
        else:
            print("\nThe following items will be deleted:\n")

        for desc, path in items_to_delete:
            if path.is_dir():
                try:
                    size = self._get_dir_size(path)
                    size_str = self._format_size(size)
                    print(f"  - {desc}")
                    print(f"    {path}")
                    print(f"    Size: {size_str}")
                    if dry_run:
                        files = list(path.rglob("*"))[:10]
                        print(f"    Contains {len(list(path.rglob('*')))} items")
                        if files:
                            print(f"    Sample: {files[0].name}")
                except Exception:
                    print(f"  - {desc}: {path}")
            else:
                print(f"  - {desc}: {path}")
        print()

        if full:
            print("WARNING: --full will delete ALL Zeloo data including:")
            print("  - All profiles and configurations")
            print("  - All session history and memories")
            print("  - All skills and customizations")
            print("  - The Zeloo code directory itself")
            print()

        if dry_run:
            print("[DRY RUN] No changes made.")
            return 0

        if not force:
            confirm = input("Are you sure you want to proceed? [y/N] ")
            if confirm.lower() != "y":
                print("Cancelled.")
                return 0

        errors = []
        for desc, path in items_to_delete:
            print(f"Deleting: {path}")
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                print(f"  [OK]")
            except Exception as exc:
                print(f"  [FAIL] {exc}")
                errors.append(f"{desc}: {exc}")

        print()
        if errors:
            print("Some items could not be deleted:")
            for err in errors:
                print(f"  - {err}")
            return 1

        print("Zeloo has been uninstalled.")
        if full:
            print("\nTo reinstall, run the installation script.")
        else:
            print("To complete the uninstallation, manually delete the remaining files.")
        return 0

    def _get_zeloo_home(self) -> Path:
        val = os.environ.get("ZELOO_HOME", "").strip()
        if val:
            return Path(val)
        if sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA", "").strip()
            base = Path(local) if local else Path.home() / "AppData" / "Local"
            return base / "Zeloo"
        return Path.home() / ".Zeloo"

    def _get_code_dir(self) -> Path:
        return Path(__file__).parent.parent.parent.resolve()

    def _get_dir_size(self, path: Path) -> int:
        total = 0
        try:
            for entry in path.rglob("*"):
                if entry.is_file():
                    try:
                        total += entry.stat().st_size
                    except Exception:
                        pass
        except Exception:
            pass
        return total

    def _format_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
