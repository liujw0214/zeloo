"""Tests for the Curator skill lifecycle manager."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from agent.curator import Curator, SkillState


def test_curator_track_usage():
    with tempfile.TemporaryDirectory() as td:
        c = Curator(skills_dir=td, stale_after_days=1, archive_after_days=3)
        c.track_usage("my-skill")
        assert c.get_state("my-skill") == SkillState.ACTIVE
        stats = c.get_stats()
        assert stats["total"] == 1
        assert stats["active"] == 1


def test_curator_stale_transition():
    with tempfile.TemporaryDirectory() as td:
        c = Curator(skills_dir=td, stale_after_days=0, archive_after_days=999)
        c.track_usage("stale-skill")
        # Force last_used to far in the past
        c._records["stale-skill"].last_used = 0
        summary = c.run_cycle()
        assert summary["stale"] == 1
        assert c.get_state("stale-skill") == SkillState.STALE


def test_curator_archive_transition():
    with tempfile.TemporaryDirectory() as td:
        c = Curator(skills_dir=td, stale_after_days=0, archive_after_days=0)
        c.track_usage("old-skill")
        c._records["old-skill"].last_used = 0
        c._records["old-skill"].state = SkillState.STALE
        summary = c.run_cycle()
        assert summary["archived"] == 1
        assert c.get_state("old-skill") == SkillState.ARCHIVED


def test_curator_usage_reactivates():
    with tempfile.TemporaryDirectory() as td:
        c = Curator(skills_dir=td, stale_after_days=1, archive_after_days=3)
        c.set_state("reactivated", SkillState.ARCHIVED)
        c.track_usage("reactivated")
        assert c.get_state("reactivated") == SkillState.ACTIVE


def test_curator_persistence():
    with tempfile.TemporaryDirectory() as td:
        state_file = Path(td) / "state.json"
        c1 = Curator(skills_dir=td, state_file=state_file)
        c1.track_usage("persisted")
        # Load fresh instance
        c2 = Curator(skills_dir=td, state_file=state_file)
        assert c2.get_state("persisted") == SkillState.ACTIVE
        assert c2._records["persisted"].use_count == 1


if __name__ == "__main__":
    tests = [
        test_curator_track_usage,
        test_curator_stale_transition,
        test_curator_archive_transition,
        test_curator_usage_reactivates,
        test_curator_persistence,
    ]
    for t in tests:
        t()
    print("All curator tests passed!")
