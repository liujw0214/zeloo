"""SWE-bench style evaluation runner for the Zeloo agent.

Runs the agent against a set of coding tasks (issue + test patch) and
reports pass/fail statistics. Each task provides:
  - A repository to work in (or a temp workspace)
  - An issue description (the user prompt)
  - A test patch that defines success criteria

The runner executes the agent, applies the test patch, runs the tests,
and records the outcome. Designed to integrate with ``mini-swe-agent``
as the task source.

Usage::

    python mini_swe_runner.py --tasks tasks.jsonl --workspace ./swe_work
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SWETask:
    """A single SWE-bench style evaluation task."""

    task_id: str
    issue: str
    test_patch: str
    repo: str | None = None
    base_commit: str | None = None
    setup_commands: list[str] = field(default_factory=list)
    test_command: str = "pytest"


@dataclass
class SWEResult:
    """The outcome of running a single SWE task."""

    task_id: str
    success: bool
    agent_output: str
    test_output: str
    error: str | None = None


class SWERunner:
    """Run SWE-bench style tasks against the Zeloo agent."""

    def __init__(
        self,
        workspace: Path,
        agent_entrypoint: str = "python run_agent.py",
        timeout: int = 600,
    ) -> None:
        self.workspace = workspace
        self.agent_entrypoint = agent_entrypoint
        self.timeout = timeout

    def load_tasks(self, path: Path) -> list[SWETask]:
        """Load task definitions from a JSONL file."""
        tasks: list[SWETask] = []
        if not path.exists():
            logger.error("Tasks file not found: %s", path)
            return tasks

        with path.open(encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    tasks.append(
                        SWETask(
                            task_id=obj.get("task_id", f"task_{line_no}"),
                            issue=obj.get("issue", ""),
                            test_patch=obj.get("test_patch", ""),
                            repo=obj.get("repo"),
                            base_commit=obj.get("base_commit"),
                            setup_commands=obj.get("setup_commands", []),
                            test_command=obj.get("test_command", "pytest"),
                        )
                    )
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed task at line %d", line_no)

        logger.info("Loaded %d task(s) from %s", len(tasks), path)
        return tasks

    def run_task(self, task: SWETask) -> SWEResult:
        """Execute a single SWE task end-to-end."""
        task_dir = self.workspace / task.task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        # Run setup commands
        for cmd in task.setup_commands:
            try:
                subprocess.run(
                    cmd, shell=True, cwd=str(task_dir), check=True, timeout=120
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                return SWEResult(
                    task_id=task.task_id,
                    success=False,
                    agent_output="",
                    test_output="",
                    error=f"Setup command failed: {e}",
                )

        # Run the agent with the issue as the prompt
        try:
            result = subprocess.run(
                f'{self.agent_entrypoint} "{task.issue}"',
                shell=True,
                cwd=str(task_dir),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            agent_output = result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return SWEResult(
                task_id=task.task_id,
                success=False,
                agent_output="",
                test_output="",
                error="Agent execution timed out",
            )

        # Apply the test patch
        patch_path = task_dir / "test_patch.diff"
        patch_path.write_text(task.test_patch, encoding="utf-8")
        try:
            subprocess.run(
                ["git", "apply", str(patch_path)],
                cwd=str(task_dir),
                check=True,
                capture_output=True,
                text=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            return SWEResult(
                task_id=task.task_id,
                success=False,
                agent_output=agent_output,
                test_output="",
                error=f"Failed to apply test patch: {e}",
            )

        # Run the tests
        try:
            test_result = subprocess.run(
                task.test_command,
                shell=True,
                cwd=str(task_dir),
                capture_output=True,
                text=True,
                timeout=300,
            )
            test_output = test_result.stdout + test_result.stderr
            success = test_result.returncode == 0
        except subprocess.TimeoutExpired:
            return SWEResult(
                task_id=task.task_id,
                success=False,
                agent_output=agent_output,
                test_output="Test execution timed out",
            )

        return SWEResult(
            task_id=task.task_id,
            success=success,
            agent_output=agent_output,
            test_output=test_output,
        )

    def run_all(self, tasks: list[SWETask]) -> dict[str, Any]:
        """Run all tasks and return aggregate results."""
        results: list[SWEResult] = []
        for task in tasks:
            logger.info("Running task: %s", task.task_id)
            result = self.run_task(task)
            results.append(result)
            status = "PASS" if result.success else "FAIL"
            logger.info("Task %s: %s", task.task_id, status)

        passed = sum(1 for r in results if r.success)
        summary = {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "pass_rate": passed / max(len(results), 1),
            "results": [
                {
                    "task_id": r.task_id,
                    "success": r.success,
                    "error": r.error,
                }
                for r in results
            ],
        }
        return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="SWE-bench evaluation runner")
    parser.add_argument(
        "--tasks",
        type=Path,
        required=True,
        help="Path to JSONL file with task definitions",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("./swe_work"),
        help="Workspace directory for task execution",
    )
    parser.add_argument(
        "--agent",
        type=str,
        default="python run_agent.py",
        help="Agent entrypoint command",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Timeout per task in seconds",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON file for results (default: stdout)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )

    workspace = args.workspace
    workspace.mkdir(parents=True, exist_ok=True)

    runner = SWERunner(
        workspace=workspace,
        agent_entrypoint=args.agent,
        timeout=args.timeout,
    )

    tasks = runner.load_tasks(args.tasks)
    if not tasks:
        print("No tasks to run.", file=sys.stderr)
        return 1

    summary = runner.run_all(tasks)
    output = json.dumps(summary, indent=2, ensure_ascii=False)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(f"Results written to {args.output}")
    else:
        print(output)

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
