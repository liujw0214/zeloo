"""Reinforcement Learning training CLI for Zeloo agent trajectories.

Provides a basic training loop that consumes compressed trajectories from
the datagen pipeline and runs policy-gradient style updates. Designed to be
extensible — plug in a real RL backend (e.g. ``tinker-atropos``) by
overriding :meth:`RLTrainer.train_step`.

Usage::

    python rl_cli.py --data data/trajectories.jsonl --epochs 3
    python rl_cli.py --data data/trajectories.jsonl --backend atropos
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TrajectorySample:
    """A single training sample derived from a compressed trajectory."""

    session_id: str
    prompt: str
    response: str
    reward: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrainingConfig:
    """Configuration for the RL training loop."""

    data_path: Path
    epochs: int = 1
    batch_size: int = 4
    learning_rate: float = 1e-5
    backend: str = "mock"
    output_dir: Path = Path("rl_outputs")


class RLTrainer:
    """Base RL training loop.

    Subclasses or backends override :meth:`train_step` to perform the actual
    parameter update. The default implementation is a no-op mock that logs
    each batch so the pipeline can be validated end-to-end without a real
    RL framework.
    """

    def __init__(self, config: TrainingConfig) -> None:
        self.config = config
        self._step = 0

    def load_samples(self) -> list[TrajectorySample]:
        """Load trajectory samples from a JSONL file.

        Each line should be a JSON object with at least ``session_id``,
        ``prompt``, and ``response`` fields.
        """
        samples: list[TrajectorySample] = []
        if not self.config.data_path.exists():
            logger.error("Data file not found: %s", self.config.data_path)
            return samples

        with self.config.data_path.open(encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    samples.append(
                        TrajectorySample(
                            session_id=obj.get("session_id", f"line_{line_no}"),
                            prompt=obj.get("prompt", ""),
                            response=obj.get("response", ""),
                            reward=float(obj.get("reward", 0.0)),
                            metadata=obj.get("metadata", {}),
                        )
                    )
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed JSON at line %d", line_no)

        logger.info("Loaded %d sample(s) from %s", len(samples), self.config.data_path)
        return samples

    def train(self) -> dict[str, Any]:
        """Run the full training loop and return summary statistics."""
        samples = self.load_samples()
        if not samples:
            return {"epochs": 0, "total_steps": 0, "samples": 0}

        total_steps = 0
        for epoch in range(1, self.config.epochs + 1):
            logger.info("Epoch %d/%d starting", epoch, self.config.epochs)
            for i in range(0, len(samples), self.config.batch_size):
                batch = samples[i : i + self.config.batch_size]
                self.train_step(batch)
                total_steps += 1

        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "epochs": self.config.epochs,
            "total_steps": total_steps,
            "samples": len(samples),
            "backend": self.config.backend,
        }
        summary_path = self.config.output_dir / "training_summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Training complete. Summary written to %s", summary_path)
        return summary

    def train_step(self, batch: list[TrajectorySample]) -> None:
        """Process one batch of samples.

        Override this method to plug in a real RL backend such as
        ``tinker-atropos``. The default implementation simply logs the batch.
        """
        self._step += 1
        avg_reward = sum(s.reward for s in batch) / max(len(batch), 1)
        logger.info(
            "Step %d: batch=%d avg_reward=%.4f backend=%s",
            self._step,
            len(batch),
            avg_reward,
            self.config.backend,
        )


def build_trainer(config: TrainingConfig) -> RLTrainer:
    """Instantiate the appropriate trainer for the configured backend."""
    if config.backend == "mock":
        return RLTrainer(config)
    if config.backend == "atropos":
        try:
            from rl_backends.atropos import AtroposTrainer  # type: ignore

            return AtroposTrainer(config)  # type: ignore[return-value]
        except ImportError:
            logger.warning(
                "atropos backend not available, falling back to mock. "
                "Install the tinker-atropos submodule to enable it."
            )
            return RLTrainer(config)
    logger.warning("Unknown backend '%s', using mock", config.backend)
    return RLTrainer(config)


def main() -> int:
    parser = argparse.ArgumentParser(description="Zeloo RL training CLI")
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="Path to JSONL file with trajectory samples",
    )
    parser.add_argument("--epochs", type=int, default=1, help="Number of epochs")
    parser.add_argument(
        "--batch-size", type=int, default=4, help="Samples per training step"
    )
    parser.add_argument(
        "--lr", type=float, default=1e-5, help="Learning rate"
    )
    parser.add_argument(
        "--backend",
        choices=["mock", "atropos"],
        default="mock",
        help="RL backend to use",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("rl_outputs"),
        help="Directory for training outputs",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )

    config = TrainingConfig(
        data_path=args.data,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        backend=args.backend,
        output_dir=args.output_dir,
    )

    trainer = build_trainer(config)
    summary = trainer.train()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
