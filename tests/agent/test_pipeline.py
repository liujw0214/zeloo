"""Regression tests for agent/pipeline.py — the daily closed-loop orchestrator.

Pipeline is "agent-improves-agent": six stages from morning brief through
overnight memory consolidation, driven by cron. These tests verify the
parser / store / runner mechanics in isolation; nothing here invokes a
real agent, writes to the real state.db, or fires any cron job.

Tests use ephemeral SQLite databases (tmp_path) and never touch the
live ``/root/zeloo`` working tree beyond the import path.

Bug class this guards:
- Stage status transitions breaking (done → running → done)
- Dependency checks allowing downstream stages when their dep failed
- Idempotency: re-triggering a done stage must be a no-op
- Parser regressions on PIPELINE.md format

Inverse tests (must hold):
- A failed upstream stage must block ALL downstream stages (no auto-retry)
- on_cron_tick is a pure function: never call queue_prompt itself
- Stage kind ``brief`` translates to ``/goal draft``, not ``/goal``
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent.pipeline import (
    Pipeline,
    PipelineRunner,
    PipelineStore,
    Stage,
    parse_pipeline_markdown,
)


PIPELINE_MD_PATH = Path(__file__).resolve().parents[2] / "workspace_templates" / "PIPELINE.md"


# --- Fixtures ---

@pytest.fixture(scope="module")
def pipeline_md() -> str:
    """The canonical daily PIPELINE.md shipped with the repo."""
    return PIPELINE_MD_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def daily_pipeline(pipeline_md: str) -> Pipeline:
    """Parsed daily pipeline (6 stages, name='daily')."""
    return parse_pipeline_markdown(pipeline_md)


@pytest.fixture
def tmp_store(tmp_path):
    """An ephemeral PipelineStore backed by a tmp SQLite file."""
    db = tmp_path / "pipeline_state.db"
    store = PipelineStore(db)
    yield store
    if hasattr(store, "close"):
        store.close()


@pytest.fixture
def captured_runner(tmp_store, daily_pipeline):
    """PipelineRunner with a queue_prompt that records every call."""
    queue_log: list[str] = []
    tmp_store.save(daily_pipeline)

    def record_prompt(prompt: str) -> None:
        queue_log.append(prompt)

    runner = PipelineRunner(tmp_store, record_prompt, lambda: None)
    runner.start("daily")
    return runner, tmp_store, queue_log


# --- Level 1: static shape ---

def test_pipeline_md_exists_and_has_six_stage_blocks(pipeline_md: str):
    """The repo ships exactly one PIPELINE.md with 6 stage blocks."""
    blocks = [ln for ln in pipeline_md.splitlines() if ln.startswith("## Stage ")]
    assert len(blocks) == 6, f"expected 6 stage blocks, got {len(blocks)}: {blocks}"


# --- Level 2: parser ---

def test_parser_round_trip_returns_six_stages(daily_pipeline: Pipeline):
    assert daily_pipeline.name == "daily"
    assert len(daily_pipeline.stages) == 6


def test_parser_preserves_stage_names_and_kinds(daily_pipeline: Pipeline):
    """Hardcoded contract: the daily pipeline has these specific stage kinds."""
    expected = [
        ("morning_brief",      "brief"),
        ("plan_today",         "plan"),
        ("specs_first",        "spec"),
        ("implement_goals",    "goal"),
        ("evening_summary",    "heartbeat"),
        ("overnight_consolidate", "consolidate"),
    ]
    actual = [(s.name, s.kind) for s in daily_pipeline.stages]
    assert actual == expected


def test_parser_preserves_dependency_chain(daily_pipeline: Pipeline):
    """Each stage's depends_on must point to the previous stage (linear chain)."""
    expected_deps = [
        [],
        ["morning_brief"],
        ["plan_today"],
        ["specs_first"],
        ["implement_goals"],
        ["evening_summary"],
    ]
    actual = [s.depends_on for s in daily_pipeline.stages]
    assert actual == expected_deps


@pytest.mark.parametrize("stage_index,cron_expr", [
    (0, "0 8 * * *"),
    (1, "15 8 * * *"),
    (2, "30 8 * * *"),
    (3, "0 9 * * *"),
    (4, "0 18 * * *"),
    (5, "0 22 * * *"),
])
def test_parser_preserves_cron_schedule(daily_pipeline: Pipeline, stage_index, cron_expr):
    """Each stage's cron expression must match the daily schedule."""
    # Parser stores cron with surrounding quotes from YAML ("0 8 * * *"); strip them
    s = daily_pipeline.stages[stage_index]
    assert s.cron.strip('"') == cron_expr, f"stage[{stage_index}] cron = {s.cron!r}"


def test_each_stage_validates_clean(daily_pipeline: Pipeline):
    """Every stage must pass its own validate() — no schema errors."""
    for s in daily_pipeline.stages:
        errs = s.validate()
        assert errs == [], f"stage {s.name!r} has validation errors: {errs}"


# --- Level 3: store persistence ---

def test_store_save_and_load_round_trip(tmp_store, daily_pipeline: Pipeline):
    tmp_store.save(daily_pipeline)
    loaded = tmp_store.load("daily")
    assert loaded is not None
    assert loaded.name == "daily"
    assert len(loaded.stages) == len(daily_pipeline.stages)
    for orig, back in zip(daily_pipeline.stages, loaded.stages):
        assert orig.name == back.name
        assert orig.kind == back.kind
        assert orig.depends_on == back.depends_on
        assert orig.max_turns == back.max_turns


def test_store_mark_stage_running(tmp_store, daily_pipeline):
    tmp_store.save(daily_pipeline)
    tmp_store.mark_stage("daily", "morning_brief", status="running", started_at=1.0)
    stage = tmp_store.load("daily").stage_by_name("morning_brief")
    assert stage.status == "running"
    assert stage.started_at == 1.0


def test_store_mark_stage_done_records_finished_time(tmp_store, daily_pipeline):
    tmp_store.save(daily_pipeline)
    tmp_store.mark_stage("daily", "morning_brief", status="running", started_at=1.0)
    tmp_store.mark_stage("daily", "morning_brief", status="done", finished_at=2.0, last_error="")
    stage = tmp_store.load("daily").stage_by_name("morning_brief")
    assert stage.status == "done"
    assert stage.finished_at == 2.0


def test_store_mark_stage_failed_records_error(tmp_store, daily_pipeline):
    tmp_store.save(daily_pipeline)
    tmp_store.mark_stage(
        "daily", "implement_goals",
        status="failed", finished_at=3.0, last_error="budget exhausted"
    )
    stage = tmp_store.load("daily").stage_by_name("implement_goals")
    assert stage.status == "failed"
    assert stage.last_error == "budget exhausted"
    assert stage.finished_at == 3.0


def test_store_list_pipelines(tmp_store, daily_pipeline):
    tmp_store.save(daily_pipeline)
    assert tmp_store.list_pipelines() == ["daily"]


# --- Level 4: runner semantics ---

def test_runner_emit_morning_brief_translates_brief_kind(captured_runner):
    """kind=brief must produce `/goal draft ...`, not bare `/goal`."""
    runner, store, queue_log = captured_runner
    prompt = runner.on_cron_tick("daily", "morning_brief")
    assert prompt.startswith("/goal draft "), (
        f"expected '/goal draft ...' for kind=brief, got: {prompt[:80]!r}"
    )


def test_runner_emit_plan_stage(captured_runner):
    runner, _, _ = captured_runner
    prompt = runner.on_cron_tick("daily", "morning_brief")
    runner.on_stage_complete("daily", "morning_brief")
    prompt = runner.on_cron_tick("daily", "plan_today")
    assert prompt.startswith("/plan "), f"expected '/plan ...', got: {prompt[:80]!r}"


def test_runner_emit_spec_stage(captured_runner):
    runner, _, _ = captured_runner
    runner.on_cron_tick("daily", "morning_brief")
    runner.on_stage_complete("daily", "morning_brief")
    runner.on_cron_tick("daily", "plan_today")
    runner.on_stage_complete("daily", "plan_today")
    prompt = runner.on_cron_tick("daily", "specs_first")
    assert prompt.startswith("/spec ")


def test_runner_emit_goal_stage(captured_runner):
    runner, _, _ = captured_runner
    # complete stages 1-3 to unlock stage 4
    for name in ("morning_brief", "plan_today", "specs_first"):
        runner.on_cron_tick("daily", name)
        runner.on_stage_complete("daily", name)
    prompt = runner.on_cron_tick("daily", "implement_goals")
    assert prompt.startswith("/goal "), f"expected '/goal ...', got: {prompt[:80]!r}"


def test_runner_failed_upstream_blocks_downstream(captured_runner):
    """The contract: if stage 4 fails, stages 5 and 6 must NOT fire."""
    runner, _, _ = captured_runner
    for name in ("morning_brief", "plan_today", "specs_first"):
        runner.on_cron_tick("daily", name)
        runner.on_stage_complete("daily", name)
    # Stage 4 fails
    runner.on_cron_tick("daily", "implement_goals")
    runner.on_stage_complete("daily", "implement_goals", error="simulated failure")
    # Stages 5 and 6 must be blocked
    assert runner.on_cron_tick("daily", "evening_summary") == ""
    assert runner.on_cron_tick("daily", "overnight_consolidate") == ""


def test_runner_is_idempotent_on_done_stages(captured_runner):
    """Re-triggering a done stage must return empty (no double-run)."""
    runner, _, _ = captured_runner
    runner.on_cron_tick("daily", "morning_brief")
    runner.on_stage_complete("daily", "morning_brief")
    # Second call must be a no-op
    assert runner.on_cron_tick("daily", "morning_brief") == ""


def test_runner_cron_tick_is_pure_function(captured_runner):
    """Critical: runner.on_cron_tick must NOT call queue_prompt itself.

    The runner is intentionally pure: external cron scheduler receives the
    returned prompt and is responsible for injecting it. If this contract
    breaks, prompts get double-injected (once by runner, once by scheduler).
    """
    runner, _, queue_log = captured_runner
    runner.on_cron_tick("daily", "morning_brief")
    assert queue_log == [], (
        f"runner.on_cron_tick leaked into queue_prompt: {queue_log!r}"
    )


def test_runner_blocks_stage_without_prior_dep_done(captured_runner):
    """plan_today depends on morning_brief — must NOT fire if morning_brief is pending."""
    runner, _, _ = captured_runner
    # Skip morning_brief entirely
    prompt = runner.on_cron_tick("daily", "plan_today")
    assert prompt == "", (
        f"dep check broken: plan_today fired without morning_brief done: {prompt[:80]!r}"
    )


def test_runner_status_report_includes_all_stages(captured_runner):
    runner, _, _ = captured_runner
    runner.on_cron_tick("daily", "morning_brief")
    runner.on_stage_complete("daily", "morning_brief")
    runner.on_cron_tick("daily", "plan_today")
    runner.on_stage_complete("daily", "plan_today", error="transient")  # plan fails
    report = runner.status_report("daily")
    assert "Pipeline: daily" in report
    assert "morning_brief" in report
    assert "plan_today" in report
    # morning_brief done -> "OK"
    assert "[OK] morning_brief" in report
    # plan_today failed -> "!!"
    assert "[!!] plan_today" in report


def test_runner_stage_with_no_deps_fires_immediately(captured_runner):
    """The first stage (morning_brief, depends_on=[]) must fire without prior work."""
    runner, _, _ = captured_runner
    prompt = runner.on_cron_tick("daily", "morning_brief")
    assert prompt != "", "stage with no deps must fire on first tick"


# --- Inverse / sentinel: pipeline must not be wired up yet ---

def test_pipeline_module_has_no_validate_method_on_pipeline_class():
    """Documenting the current API gap: Pipeline has no top-level validate().

    This is a sentinel that will START failing once a Pipeline.validate()
    method is added — at which point the test must be updated to exercise
    the new API. It exists so the gap doesn't get silently overlooked.
    """
    assert not hasattr(Pipeline, "validate"), (
        "Pipeline.validate() was added — update this sentinel and add a "
        "Pipeline-level validation test in test_parser_round_trip_returns_six_stages."
    )
