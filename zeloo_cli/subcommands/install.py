"""Zeloo install subcommand — guided setup and repair."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("install")
class InstallCmd(Subcommand):
    name = "install"
    help = "Initialize Zeloo environment and guided setup"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--repair", action="store_true",
            help="Attempt to repair an existing broken installation",
        )
        parser.add_argument(
            "--minimal", action="store_true",
            help="Skip optional dependency checks",
        )

    def run(self, args: argparse.Namespace) -> int:
        home = Path.home() / ".Zeloo"
        home.mkdir(exist_ok=True)

        (home / "profile").mkdir(exist_ok=True)
        (home / "memory").mkdir(exist_ok=True)
        (home / "skills").mkdir(exist_ok=True)
        (home / "archive").mkdir(exist_ok=True)

        # Stamp the install method so dep_ensure() can find this
        # install script the next time the user runs ``zeloo doctor``.
        try:
            from zeloo_cli.dep_ensure import stamp_install_method
            stamp_install_method("git", home=home, extra={"source": "zeloo install"})
        except Exception:  # noqa: BLE001
            pass

        if args.repair:
            self._repair(home)
            return 0

        self._create_config(home)
        self._create_memory(home)

        if not args.minimal:
            self._check_dependencies()

        print(f"\nZeloo ready at: {home}")
        print("Next steps:")
        print(f"  1. Edit {home}/.env and add your OPENAI_API_KEY")
        print("  2. Run: Zeloo chat")
        print()
        print("Tip: install shell completion with `zeloo completion install bash`")
        print("     (or zsh/fish/powershell). See `zeloo --help` for more.")
        return 0

    def _create_config(self, home: Path) -> None:
        env_path = home / ".env"
        if env_path.exists():
            return
        env_path.write_text(
            f"# Zeloo Environment Configuration\n\n"
            f"OPENAI_API_KEY=sk-your-key-here\n"
            f"zeloo_MODEL=gpt-4o\n"
            f"zeloo_PROVIDER=openai\n"
            f"zeloo_HOME={home}\n",
            encoding="utf-8",
        )

    def _create_memory(self, home: Path) -> None:
        memory_dir = home / "memory" / "default"
        memory_dir.mkdir(parents=True, exist_ok=True)
        user_md = memory_dir / "USER.md"
        if not user_md.exists():
            user_md.write_text(
                "# User Profile\n\n"
                "[Write your background, preferences, and context here]\n",
                encoding="utf-8",
            )

    def _check_dependencies(self) -> None:
        # Rich progress bar (Hermes Agent parity).
        from zeloo_cli.rich_render import make_progress

        deps = [
            ("openai", "openai"),
            ("httpx", "httpx"),
            ("pyyaml", "yaml"),
            ("python-dotenv", "dotenv"),
        ]
        missing: list[str] = []
        with make_progress(transient=True) as progress:
            task = progress.add_task("Checking dependencies", total=len(deps))
            for pkg, import_name in deps:
                try:
                    __import__(import_name)
                    progress.update(task, advance=1, description=f"[OK] {pkg}")
                except ImportError:
                    missing.append(pkg)
                    progress.update(task, advance=1, description=f"[MISSING] {pkg}")

        if missing:
            from zeloo_cli.rich_render import make_console

            console = make_console()
            console.print(f"\n[red]Missing:[/red] {', '.join(missing)}")
            console.print(f"Install with: {sys.executable} -m pip install {' '.join(missing)}")

        # ── Round 67: also probe external (non-Python) tools.
        try:
            from zeloo_cli.dep_ensure import KNOWN_DEPS, ensure_dependency, is_available

            print("\nExternal tools (Hermes parity):")
            for name in KNOWN_DEPS:
                if KNOWN_DEPS[name].optional:
                    continue
                if is_available(name):
                    print(f"  [OK] {name}")
                else:
                    ok = ensure_dependency(name, interactive=False)
                    tag = "[OK]" if ok else "[MISSING]"
                    print(f"  {tag} {name}")
        except Exception as exc:  # noqa: BLE001
            print(f"(dep_ensure skipped: {exc})")

    def _repair(self, home: Path) -> None:
        print("Running installation repair...")
        fixes = 0

        for subdir in ("profile", "memory", "skills", "archive"):
            p = home / subdir
            if not p.exists():
                p.mkdir(parents=True, exist_ok=True)
                print(f"  [FIXED] Created missing directory: {subdir}")
                fixes += 1

        env = home / ".env"
        if not env.exists():
            self._create_config(home)
            print("  [FIXED] Created missing .env file")
            fixes += 1

        print(f"\nRepair complete. {fixes} issue(s) fixed.")
