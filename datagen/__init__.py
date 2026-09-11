"""Datagen utilities — trajectory extraction, compression, and training data export.

This package groups the data-generation pipeline:
  - :mod:`datagen.compress_trajectories` — compress long conversation traces.
  - :mod:`datagen.extract_trajectories` — export DB trajectories as ShareGPT JSONL.
  - :mod:`datagen.dataloader` — trajectory loading utilities.
"""

from .compress_trajectories import compress_trajectory
from .dataloader import Trajectory, TrajectoryLoader
from .extract_trajectories import extract_for_training

__all__ = [
    "compress_trajectory",
    "extract_for_training",
    "Trajectory",
    "TrajectoryLoader",
]
