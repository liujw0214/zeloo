"""Zeloo doctor subcommand — system diagnostics."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("doctor")
class DoctorCmd(Subcommand):
    name = "doctor"
    help = "Run comprehensive system diagnostic checks"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--fix", action="store_true",
            help="Automatically repair fixable issues",
        )
        parser.add_argument(
            "--json", action="store_true",
            help="Output results as JSON instead of human-readable text",
        )

    def run(self, args: argparse.Namespace) -> int:
        results: list[dict[str, Any]] = []
        checks = [
            ("python_version", self._check_python),
            ("config_file", self._check_config),
            ("zeloo_home", self._check_home),
            ("python_deps", self._check_deps),
            ("env_file", self._check_env),
            ("skills_dir", self._check_skills),
            ("db_writable", self._check_db_writable),
        ]

        for name, fn in checks:
            status, detail = fn()
            results.append({"check": name, "status": status, "detail": detail})

        if args.json:
            import json
            print(json.dumps(results, indent=2))
            return 0

        print("Zeloo Doctor — system diagnostic")
        print("=" * 52)
        for r in results:
            icon = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}.get(r["status"], "?")
            print(f"  [{icon:4}] {r['check']:20} {r['detail']}")
        print("=" * 52)

        failures = [r for r in results if r["status"] == "fail"]
        warns = [r for r in results if r["status"] == "warn"]
        print(
            f"Results: {len(results)} checks, "
            f"{len(failures)} failures, {len(warns)} warnings"
        )

        if args.fix and failures:
            self._auto_fix(failures)

        return 0 if not failures else 1

    def _check_python(self) -> tuple[str, str]:
        version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        ok = sys.version_info >= (3, 10)
        return ("ok" if ok else "fail", f"Python {version} (>= 3.10 required)")

    def _check_config(self) -> tuple[str, str]:
        from agent.zeloo_constants import get_zeloo_home
        cfg = get_zeloo_home() / "config.yaml"
        if cfg.is_file():
            return "ok", "config.yaml found"
        return "warn", "config.yaml not found (optional)"

    def _check_home(self) -> tuple[str, str]:
        from agent.zeloo_constants import get_zeloo_home
        home = get_zeloo_home()
        if home.is_dir():
            return "ok", f"zeloo_HOME={home}"
        return "fail", f"zeloo_HOME missing: {home}"

    def _check_deps(self) -> tuple[str, str]:
        missing = []
        for pkg, import_name in [
            ("openai", "openai"),
            ("httpx", "httpx"),
            ("pyyaml", "yaml"),
            ("python-dotenv", "dotenv"),
            ("tiktoken", "tiktoken"),
        ]:
            try:
                __import__(import_name)
            except ImportError:
                missing.append(pkg)
        if not missing:
            return "ok", "All core dependencies installed"
        return "fail", f"Missing: {', '.join(missing)}"

    def _check_env(self) -> tuple[str, str]:
        from agent.zeloo_constants import get_zeloo_home
        env = get_zeloo_home() / ".env"
        if env.is_file():
            content = env.read_text(encoding="utf-8")
            if "sk-" in content:
                return "ok", ".env present with API key"
            return "warn", ".env present but API key not configured"
        return "warn", ".env not found"

    def _check_skills(self) -> tuple[str, str]:
        from agent.zeloo_constants import get_zeloo_home
        skills = get_zeloo_home() / "skills"
        if skills.is_dir():
            count = len(list(skills.iterdir()))
            return "ok", f"skills/ exists ({count} items)"
        return "warn", "skills/ not found (optional)"

    def _check_db_writable(self) -> tuple[str, str]:
        from agent.zeloo_constants import get_zeloo_home
        db = get_zeloo_home() / "state.db"
        try:
            db.parent.mkdir(parents=True, exist_ok=True)
            if db.exists():
                db.touch()
            else:
                db.touch()
                db.unlink()
            return "ok", "state.db is writable"
        except OSError as exc:
            return "fail", f"state.db not writable: {exc}"

    def _auto_fix(self, failures: list[dict[str, Any]]) -> None:
        from agent.zeloo_constants import get_zeloo_home

        print("\nAuto-fix:")
        for r in failures:
            if r["check"] == "zeloo_home":
                home = get_zeloo_home()
                home.mkdir(parents=True, exist_ok=True)
                print(f"  [FIXED] Created {home}")
            elif r["check"] == "db_writable":
                db = get_zeloo_home() / "state.db"
                db.parent.mkdir(parents=True, exist_ok=True)
                db.touch()
                print("  [FIXED] Created state.db parent directory")
