"""Trajectory replay — re-execute past agent turns for debugging/learning."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ReplayMode(StrEnum):
    """Replay execution modes."""

    STEP = "step"           # Pause after each tool call
    FAST = "fast"           # Run to completion without pause
    DRY_RUN = "dry_run"     # Simulate without executing side effects
    INSPECT = "inspect"     # Just analyze and report


@dataclass
class ReplayStep:
    """A single step in a trajectory replay."""

    step_index: int
    step_type: str  # 'tool_call' | 'assistant_message' | 'tool_result'
    content: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplayResult:
    """Result of replaying a trajectory."""

    trajectory_id: str
    mode: ReplayMode
    total_steps: int
    successful_steps: int
    failed_steps: int
    total_duration_ms: float
    original_outcome: str
    replayed_outcome: str | None = None
    divergence_points: list[int] = field(default_factory=list)
    steps: list[ReplayStep] = field(default_factory=list)


class TrajectoryReplay:
    """Re-execute agent trajectories for debugging and learning.

    Supports:
    - step: pause between steps for inspection
    - fast: full re-execution
    - dry_run: simulate without side effects
    - inspect: just analyze
    """

    def __init__(self, mode: ReplayMode = ReplayMode.INSPECT) -> None:
        self.mode = mode

    def replay(
        self,
        trajectory: dict[str, Any],
        executor: Any | None = None,
    ) -> ReplayResult:
        """Replay a single trajectory.

        Args:
            trajectory: Trajectory dict with messages, tool_calls, tool_results.
            executor: Optional executor for tool calls (for fast/step modes).
        """
        start_time = time.time()
        trajectory_id = trajectory.get("trajectory_id", "unknown")
        original_outcome = trajectory.get("outcome", "unknown")

        steps: list[ReplayStep] = []
        successful = 0
        failed = 0
        divergence_points: list[int] = []

        messages = trajectory.get("messages", [])
        tool_calls = trajectory.get("tool_calls", [])
        tool_results = trajectory.get("tool_results", [])

        for i, msg in enumerate(messages):
            step = ReplayStep(
                step_index=i,
                step_type="assistant_message",
                content=msg,
            )
            steps.append(step)
            successful += 1

        for i, tc in enumerate(tool_calls):
            step = ReplayStep(
                step_index=len(messages) + i,
                step_type="tool_call",
                content=tc,
            )
            step_start = time.time()

            if self.mode == ReplayMode.STEP:
                logger.info(
                    "Step %d: Would call %s with %s",
                    step.step_index,
                    tc.get("function", {}).get("name"),
                    tc.get("function", {}).get("arguments", "")[:80],
                )

            elif self.mode in (ReplayMode.FAST, ReplayMode.DRY_RUN):
                if executor is not None and self.mode == ReplayMode.FAST:
                    try:
                        result = executor.execute(tc)
                        step.metadata["result"] = result
                        successful += 1
                    except Exception as e:
                        step.metadata["error"] = str(e)
                        failed += 1
                        divergence_points.append(step.step_index)
                elif self.mode == ReplayMode.DRY_RUN:
                    step.metadata["dry_run"] = True
                    successful += 1
                else:
                    successful += 1

            step.duration_ms = (time.time() - step_start) * 1000
            steps.append(step)

        for i, tr in enumerate(tool_results):
            step = ReplayStep(
                step_index=len(messages) + len(tool_calls) + i,
                step_type="tool_result",
                content=tr,
            )
            steps.append(step)

        total_duration = (time.time() - start_time) * 1000

        result = ReplayResult(
            trajectory_id=trajectory_id,
            mode=self.mode,
            total_steps=len(steps),
            successful_steps=successful,
            failed_steps=failed,
            total_duration_ms=total_duration,
            original_outcome=original_outcome,
            divergence_points=divergence_points,
            steps=steps,
        )

        logger.info(
            "Replayed trajectory %s in %s mode: %d/%d steps successful",
            trajectory_id,
            self.mode.value,
            successful,
            len(steps),
        )
        return result

    def compare(
        self,
        trajectory_a: dict[str, Any],
        trajectory_b: dict[str, Any],
    ) -> dict[str, Any]:
        """Compare two trajectories and identify divergence points."""
        msgs_a = trajectory_a.get("messages", [])
        msgs_b = trajectory_b.get("messages", [])

        divergences: list[int] = []
        for i in range(min(len(msgs_a), len(msgs_b))):
            if msgs_a[i] != msgs_b[i]:
                divergences.append(i)

        return {
            "trajectory_a_id": trajectory_a.get("trajectory_id"),
            "trajectory_b_id": trajectory_b.get("trajectory_id"),
            "a_length": len(msgs_a),
            "b_length": len(msgs_b),
            "divergence_count": len(divergences),
            "divergence_points": divergences,
        }


__all__ = [
    "ReplayMode",
    "ReplayStep",
    "ReplayResult",
    "TrajectoryReplay",
]