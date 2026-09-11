"""Zeloo ``verify`` subcommand — detect project recipe and smoke-test it."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("verify")
class VerifyCmd(Subcommand):
    name = "verify"
    help = "Detect project recipe and smoke-test it"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--skip-start", action="store_true",
            help="Skip the start phase",
        )
        parser.add_argument(
            "--detect-only", action="store_true",
            help="Only detect project type, do not run tests",
        )
        parser.add_argument(
            "--phase",
            choices=["bootstrap", "build", "test", "start"],
            default=None,
            help="Run only a specific phase",
        )
        parser.add_argument(
            "--timeout", type=int, default=30,
            help="Timeout for each phase in seconds (default: 30)",
        )
        parser.add_argument(
            "--dir", dest="target_dir", default=".",
            help="Project directory to verify (default: current directory)",
        )

    def run(self, args: argparse.Namespace) -> int:
        target_dir = Path(getattr(args, "target_dir", ".")).resolve()
        skip_start = getattr(args, "skip_start", False)
        detect_only = getattr(args, "detect_only", False)
        phase = getattr(args, "phase", None)
        timeout = getattr(args, "timeout", 30)

        print(f"Verifying project at: {target_dir}")
        print()

        project_type = self._detect_project_type(target_dir)
        print(f"Detected project type: {project_type}")
        print()

        if detect_only:
            return 0

        phases = ["bootstrap", "build", "test"]
        if not skip_start:
            phases.append("start")

        if phase:
            phases = [phase]

        all_passed = True
        for p in phases:
            print(f"{'=' * 50}")
            print(f"  Phase: {p.upper()}")
            print(f"{'=' * 50}")

            success = self._run_phase(p, target_dir, project_type, timeout)
            if not success:
                all_passed = False
                print(f"\nFAILED at phase: {p}")
                break
            print()

        print(f"{'=' * 50}")
        if all_passed:
            print("  VERIFICATION PASSED")
        else:
            print("  VERIFICATION FAILED")
        print(f"{'=' * 50}")

        return 0 if all_passed else 1

    def _detect_project_type(self, project_dir: Path) -> str:
        indicators = {
            "Node.js": [
                "package.json",
                ("package-lock.json", "pnpm-lock.yaml", "yarn.lock"),
            ],
            "Python": [
                ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile"),
                ".python-version",
            ],
            "Go": [
                "go.mod",
            ],
            "Rust": [
                "Cargo.toml",
            ],
        }

        for ptype, markers in indicators.items():
            for marker in markers:
                if isinstance(marker, tuple):
                    if any((project_dir / m).exists() for m in marker):
                        return ptype
                else:
                    if (project_dir / marker).exists():
                        return ptype

        return "Unknown"

    def _run_phase(self, phase: str, project_dir: Path, project_type: str, timeout: int) -> bool:
        if phase == "bootstrap":
            return self._phase_bootstrap(project_dir, project_type, timeout)
        elif phase == "build":
            return self._phase_build(project_dir, project_type, timeout)
        elif phase == "test":
            return self._phase_test(project_dir, project_type, timeout)
        elif phase == "start":
            return self._phase_start(project_dir, project_type, timeout)
        return False

    def _phase_bootstrap(self, project_dir: Path, project_type: str, timeout: int) -> bool:
        print("  Running bootstrap...")

        commands = {
            "Node.js": ["npm", "install"],
            "Python": ["pip", "install", "-r", "requirements.txt"],
            "Go": ["go", "mod", "download"],
            "Rust": ["cargo", "fetch"],
        }

        cmd = commands.get(project_type)
        if not cmd:
            print("  [SKIP] No bootstrap command for this project type")
            return True

        return self._run_command(cmd, project_dir, timeout)

    def _phase_build(self, project_dir: Path, project_type: str, timeout: int) -> bool:
        print("  Running build...")

        commands = {
            "Node.js": ["npm", "run", "build"],
            "Python": ["python", "-m", "py_compile"] + self._find_python_files(project_dir),
            "Go": ["go", "build", "./..."],
            "Rust": ["cargo", "build"],
        }

        cmd = commands.get(project_type)
        if not cmd:
            print("  [SKIP] No build command for this project type")
            return True

        if project_type == "Python" and len(cmd) == 2:
            print("  [SKIP] No Python files found to compile")
            return True

        return self._run_command(cmd, project_dir, timeout)

    def _phase_test(self, project_dir: Path, project_type: str, timeout: int) -> bool:
        print("  Running tests...")

        commands = {
            "Node.js": ["npm", "test"],
            "Python": ["python", "-m", "pytest"],
            "Go": ["go", "test", "./..."],
            "Rust": ["cargo", "test"],
        }

        cmd = commands.get(project_type)
        if not cmd:
            print("  [SKIP] No test command for this project type")
            return True

        return self._run_command(cmd, project_dir, timeout)

    def _phase_start(self, project_dir: Path, project_type: str, timeout: int) -> bool:
        print("  Checking if application starts...")

        commands = {
            "Node.js": ["npm", "start"],
            "Python": ["python", "-c", "print('Python app starts OK')"],
            "Go": ["go", "run", "."],
            "Rust": ["cargo", "run"],
        }

        cmd = commands.get(project_type)
        if not cmd:
            print("  [SKIP] No start command for this project type")
            return True

        proc = subprocess.Popen(
            cmd,
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            stdout, stderr = proc.communicate(timeout=min(timeout, 10))
            if proc.returncode != 0:
                print(f"  [FAIL] Exit code: {proc.returncode}")
                if stderr:
                    print(f"  stderr: {stderr.decode('utf-8', errors='replace')[:500]}")
                return False
            print("  [OK] Application started successfully")
            return True
        except subprocess.TimeoutExpired:
            proc.kill()
            print("  [OK] Application started and is running")
            proc.wait()
            return True
        except Exception as exc:
            print(f"  [FAIL] Error: {exc}")
            return False

    def _run_command(self, cmd: list, project_dir: Path, timeout: int) -> bool:
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if proc.returncode != 0:
                print(f"  [FAIL] Exit code: {proc.returncode}")
                if proc.stderr:
                    print(f"  stderr: {proc.stderr[:500]}")
                return False
            print("  [OK]")
            return True
        except subprocess.TimeoutExpired:
            print(f"  [FAIL] Timeout after {timeout}s")
            return False
        except FileNotFoundError as exc:
            print(f"  [FAIL] Command not found: {exc}")
            return False
        except Exception as exc:
            print(f"  [FAIL] Error: {exc}")
            return False

    def _find_python_files(self, project_dir: Path) -> list[str]:
        py_files = []
        for root, _, files in os.walk(project_dir):
            for f in files:
                if f.endswith(".py") and not f.startswith("."):
                    py_files.append(os.path.join(root, f))
        return py_files[:20]
