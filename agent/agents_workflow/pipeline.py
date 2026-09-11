"""Pipeline — multi-stage agent processing pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PipelineStage:
    """A single stage in a pipeline."""

    name: str
    agent_name: str
    processor: Callable[[Any], Any] | None = None
    condition: Callable[[Any], bool] | None = None
    on_error: str | None = None

    def process(self, input_data: Any) -> Any:
        if self.processor:
            return self.processor(input_data)
        return input_data

    def should_run(self, ctx: dict[str, Any]) -> bool:
        if self.condition is None:
            return True
        try:
            return self.condition(ctx)
        except Exception:
            return True


@dataclass
class Pipeline:
    """Multi-stage agent processing pipeline.

    Each stage receives the output of the previous stage as input,
    allowing complex multi-step workflows.
    """

    name: str
    stages: list[PipelineStage] = field(default_factory=list)

    def add_stage(
        self,
        name: str,
        agent_name: str,
        processor: Callable[[Any], Any] | None = None,
        condition: Callable[[dict[str, Any]], bool] | None = None,
    ) -> Pipeline:
        """Add a stage to the pipeline (fluent interface)."""
        self.stages.append(
            PipelineStage(
                name=name,
                agent_name=agent_name,
                processor=processor,
                condition=condition,
            )
        )
        return self

    def execute(
        self,
        agents: dict[str, Any],
        initial_input: Any,
    ) -> dict[str, Any]:
        """Execute the pipeline and return stage results."""
        results: dict[str, Any] = {"initial_input": initial_input}
        context: dict[str, Any] = {}
        current_input = initial_input
        stage_outputs: list[Any] = []

        for stage in self.stages:
            if not stage.should_run(context):
                logger.info("Stage '%s' skipped (condition=false)", stage.name)
                continue

            agent = agents.get(stage.agent_name)
            if not agent:
                logger.error("Agent '%s' not found for stage '%s'", stage.agent_name, stage.name)
                results[stage.name] = {"error": f"Agent '{stage.agent_name}' not found"}
                continue

            try:
                logger.info("Executing stage: %s (agent=%s)", stage.name, stage.agent_name)
                processed = stage.process(current_input)
                output = agent.run_conversation(processed)
                stage_outputs.append(output)
                current_input = output
                context[stage.name] = output
                results[stage.name] = {"output": output, "status": "success"}

            except Exception as e:
                logger.error("Stage '%s' failed: %s", stage.name, e)
                results[stage.name] = {"error": str(e), "status": "failed"}
                if stage.on_error:
                    next_stage = next(
                        (s for s in self.stages if s.name == stage.on_error), None
                    )
                    if next_stage:
                        logger.info("Jumping to error handler: %s", next_stage.name)
                else:
                    break

        results["stage_outputs"] = stage_outputs
        results["final_output"] = current_input
        return results
