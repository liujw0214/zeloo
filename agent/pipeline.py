"""Agent full-day pipeline orchestrator (closed loop).

A pipeline is a sequence of *stages* executed in order, each backed by either a
``/goal``, ``/plan``, ``/spec``, or ``/heartbeat`` command. Once a pipeline is
loaded (via ``/pipeline load`` or auto-loaded from
``workspace_templates/PIPELINE.md``), the cron scheduler + goal manager run the
stages in order without user intervention.

Architecture:

  workspace_templates/PIPELINE.md   # human-authored daily plan
          |
          v
  Pipeline.from_markdown()          # parser
          |
          v
  PipelineRunner.start()            # registers cron + goal hooks
          |
          v
  loop (no human in the loop)
    Stage 1  /goal: morning brief            (08:00, steered)
    Stage 2  /spec: write today's specs       (08:15, auto)
    Stage 3  /plan: implement spec N          (09:00+, per-spec)
    Stage 4  /goal: implement + verify        (continues until done)
    Stage 5  /heartbeat: evening summary      (18:00, follow-up)
    Stage 6  /goal: overnight consolidation   (22:00, steer, memory write)

All stage transitions are persisted to ``state.db::pipeline_state`` so a crash
mid-day resumes cleanly. The PipelineRunner is goroutine-safe (used from both
the cron scheduler thread and the interactive CLI thread).
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


# ---- Stage model ----

STAGE_TYPES = {"goal", "plan", "spec", "heartbeat", "brief", "verify", "consolidate"}

VALID_DELIVERY = {"steer", "follow_up", "auto"}


@dataclass
class Stage:
    """One stage of a daily pipeline.

    A stage is a tiny job descriptor that gets translated into one of the
    existing commands (``/goal``, ``/plan``, ``/spec``, ``/heartbeat``). The
    cron scheduler and GoalManager share ``state.db`` so a stage's status is
    visible across both surfaces.
    """
    name: str
    kind: str                          # one of STAGE_TYPES
    cron: str = ""                     # 5-field cron expression
    tz: str = "Asia/Shanghai"
    prompt: str = ""                   # what to feed to the model
    delivery: str = "auto"             # steer / follow_up / auto
    depends_on: list[str] = field(default_factory=list)
    max_turns: int = 30
    enabled: bool = True
    timeout_seconds: int = 1800        # 30 min default
    # Runtime state (not part of the markdown schema, persisted to state.db)
    status: str = "pending"            # pending / running / done / failed / skipped
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    last_error: str = ""

    def validate(self) -> list[str]:
        """Return a list of validation errors (empty = valid)."""
        errs = []
        if not self.name:
            errs.append("stage name is required")
        if self.kind not in STAGE_TYPES:
            errs.append(f"kind must be one of {sorted(STAGE_TYPES)}, got {self.kind!r}")
        if self.kind != "heartbeat" and not self.cron:
            errs.append(f"stage {self.name!r}: cron expression required")
        if self.delivery not in VALID_DELIVERY:
            errs.append(f"delivery must be one of {sorted(VALID_DELIVERY)}, got {self.delivery!r}")
        if not self.prompt:
            errs.append(f"stage {self.name!r}: prompt is empty")
        return errs


# ---- Pipeline model ----

@dataclass
class Pipeline:
    """A named ordered sequence of stages that runs every day."""
    name: str
    description: str = ""
    owner: str = "user"                # user / agent
    stages: list[Stage] = field(default_factory=list)
    enabled: bool = True
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())

    def stage_by_name(self, name: str) -> Optional[Stage]:
        for s in self.stages:
            if s.name == name:
                return s
        return None

    def pending_stages(self) -> list[Stage]:
        """Stages ready to run: deps satisfied, not done, not running, not skipped."""
        done_names = {s.name for s in self.stages if s.status == "done"}
        result = []
        for s in self.stages:
            if s.status in ("done", "skipped", "running"):
                continue
            if not s.enabled:
                continue
            if all(dep in done_names for dep in s.depends_on):
                result.append(s)
        return result


# ---- Markdown parser ----

_STAGE_RE = re.compile(
    r"^##\s+(?P<name>[^\n]+)\n"
    r"(?P<body>(?:^(?!##\s).*\n?)*)",
    re.MULTILINE,
)

_FIELD_RE = re.compile(
    r"^\s*-\s*(?P<key>[a-z_]+)\s*:\s*(?P<val>.+?)\s*$",
    re.MULTILINE,
)


def _coerce_field(key: str, val: str):
    if key in ("max_turns", "timeout_seconds"):
        try:
            return int(val)
        except ValueError:
            return val
    if key == "enabled":
        return val.lower() in ("true", "yes", "1", "on")
    if key == "depends_on":
        return [x.strip() for x in val.split(",") if x.strip()]
    return val


def parse_pipeline_markdown(md: str) -> Pipeline:
    """Parse a PIPELINE.md document into a Pipeline object.

    Format::

        # Pipeline: <name>
        <description paragraph>

        ## Stage 1: <name>
        - kind: goal
        - cron: "0 8 * * *"
        - tz: Asia/Shanghai
        - delivery: steer
        - max_turns: 50
        - prompt: |
          multi-line prompt text
        - depends_on: (optional, comma-separated stage names)

        ## Stage 2: ...
    """
    lines = md.splitlines()
    name = ""
    description_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("# Pipeline:"):
            name = line[len("# Pipeline:"):].strip()
            i += 1
            break
        i += 1
    if not name:
        raise ValueError("PIPELINE.md must start with `# Pipeline: <name>`")
    while i < len(lines) and not lines[i].startswith("## "):
        description_lines.append(lines[i])
        i += 1
    description = chr(10).join(description_lines).strip()
    stages = []
    current = None
    current_prompt = []
    in_prompt = False
    prompt_indent = 0
    def _finalize():
        nonlocal current, current_prompt, in_prompt, prompt_indent
        if current is not None:
            current.prompt = chr(10).join(current_prompt).strip()
            stages.append(current)
        current = None
        current_prompt = []
        in_prompt = False
        prompt_indent = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## Stage"):
            _finalize()
            m = re.match(r"##\s+Stage\s+\d+\s*:\s*(.+)", line)
            if m:
                current = Stage(name=m.group(1).strip(), kind="goal", prompt="")
                in_prompt = False
        elif current is not None and not in_prompt and line.lstrip().startswith("- "):
            m = _FIELD_RE.match(line)
            if m:
                key = m.group("key")
                val = m.group("val").rstrip().strip()
                if key == "prompt" and val == "|":
                    in_prompt = True
                    prompt_indent = None
                    current_prompt = []
                else:
                    coerced = _coerce_field(key, val)
                    if hasattr(current, key):
                        setattr(current, key, coerced)
        elif current is not None and in_prompt:
            stripped = line.strip()
            if stripped.startswith("- "):
                in_prompt = False
                i -= 1
            elif stripped.startswith("## "):
                in_prompt = False
                i -= 1
            elif line.strip() == "":
                i += 1
                continue
            else:
                if prompt_indent is None:
                    prompt_indent = len(line) - len(line.lstrip())
                if prompt_indent > 0 and len(line) >= prompt_indent and line[:prompt_indent] == " " * prompt_indent:
                    current_prompt.append(line[prompt_indent:])
                else:
                    current_prompt.append(line)
        i += 1
    _finalize()
    return Pipeline(name=name, description=description, stages=stages)

class PipelineStore:
    """SQLite-backed pipeline + stage state store."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._init_schema()

    def _init_schema(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS pipeline (
                    name TEXT PRIMARY KEY,
                    description TEXT NOT NULL DEFAULT '',
                    owner TEXT NOT NULL DEFAULT 'user',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pipeline_stage (
                    pipeline_name TEXT NOT NULL,
                    stage_name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    cron TEXT NOT NULL DEFAULT '',
                    tz TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                    prompt TEXT NOT NULL DEFAULT '',
                    delivery TEXT NOT NULL DEFAULT 'auto',
                    depends_on TEXT NOT NULL DEFAULT '',
                    max_turns INTEGER NOT NULL DEFAULT 30,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    timeout_seconds INTEGER NOT NULL DEFAULT 1800,
                    status TEXT NOT NULL DEFAULT 'pending',
                    started_at REAL,
                    finished_at REAL,
                    last_error TEXT NOT NULL DEFAULT '',
                    seq INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (pipeline_name, stage_name),
                    FOREIGN KEY (pipeline_name) REFERENCES pipeline(name) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_stage_status
                    ON pipeline_stage(pipeline_name, status);
            """)

    def save(self, pipeline: Pipeline):
        pipeline.updated_at = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO pipeline (name, description, owner, enabled, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (pipeline.name, pipeline.description, pipeline.owner,
                 1 if pipeline.enabled else 0, pipeline.created_at, pipeline.updated_at),
            )
            # Replace stages
            conn.execute("DELETE FROM pipeline_stage WHERE pipeline_name = ?", (pipeline.name,))
            for i, s in enumerate(pipeline.stages):
                conn.execute(
                    "INSERT INTO pipeline_stage (pipeline_name, stage_name, kind, cron, tz, prompt, "
                    "delivery, depends_on, max_turns, enabled, timeout_seconds, status, "
                    "started_at, finished_at, last_error, seq) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (pipeline.name, s.name, s.kind, s.cron, s.tz, s.prompt, s.delivery,
                     ",".join(s.depends_on), s.max_turns,
                     1 if s.enabled else 0, s.timeout_seconds, s.status,
                     s.started_at, s.finished_at, s.last_error, i),
                )

    def load(self, name: str) -> Optional[Pipeline]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT name, description, owner, enabled, created_at, updated_at "
                "FROM pipeline WHERE name = ?", (name,)
            ).fetchone()
            if not row:
                return None
            stages_rows = conn.execute(
                "SELECT stage_name, kind, cron, tz, prompt, delivery, depends_on, "
                "max_turns, enabled, timeout_seconds, status, started_at, finished_at, last_error "
                "FROM pipeline_stage WHERE pipeline_name = ? ORDER BY seq",
                (name,),
            ).fetchall()
        stages = [
            Stage(
                name=r[0], kind=r[1], cron=r[2], tz=r[3], prompt=r[4],
                delivery=r[5],
                depends_on=[x for x in r[6].split(",") if x],
                max_turns=r[7],
                enabled=bool(r[8]),
                timeout_seconds=r[9],
                status=r[10],
                started_at=r[11],
                finished_at=r[12],
                last_error=r[13],
            )
            for r in stages_rows
        ]
        return Pipeline(
            name=row[0], description=row[1], owner=row[2],
            enabled=bool(row[3]),
            created_at=row[4], updated_at=row[5],
            stages=stages,
        )

    def list_pipelines(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            return [r[0] for r in conn.execute("SELECT name FROM pipeline ORDER BY name").fetchall()]

    def mark_stage(self, pipeline_name: str, stage_name: str, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields.keys())
        vals = list(fields.values()) + [pipeline_name, stage_name]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE pipeline_stage SET {cols} WHERE pipeline_name = ? AND stage_name = ?",
                vals,
            )


# ---- Runner ----

class PipelineRunner:
    """In-process runner: watches state.db for cron triggers and advances stages.

    The runner is intentionally lightweight: cron-time dispatch is delegated to
    the existing cron scheduler (it calls our hooks). This runner focuses on
    stage sequencing + state transitions + emitting the right ``/command`` to
    the prompt queue.
    """

    def __init__(self, store: PipelineStore, queue_prompt: Callable[[str], None],
                 get_goal_manager: Callable[[], Optional[object]]):
        self.store = store
        self.queue_prompt = queue_prompt
        self.get_goal_manager = get_goal_manager
        self._lock = threading.Lock()
        self._active_pipeline: Optional[str] = None
        self._stop_event = threading.Event()

    def start(self, pipeline_name: str):
        """Mark pipeline as active; cron + goal hooks drive stage execution."""
        with self._lock:
            self._active_pipeline = pipeline_name

    def stop(self):
        with self._lock:
            self._active_pipeline = None

    def on_cron_tick(self, pipeline_name: str, stage_name: str) -> str:
        """Cron-driven hook. Returns the prompt to feed to the agent.

        Idempotent: if the stage is already done/running, returns "" so the
        scheduler skips the prompt injection.
        """
        with self._lock:
            pipeline = self.store.load(pipeline_name)
            if not pipeline or not pipeline.enabled:
                return ""
            stage = pipeline.stage_by_name(stage_name)
            if not stage or not stage.enabled:
                return ""
            if stage.status in ("done", "running", "skipped"):
                return ""
            # Dep check
            for dep in stage.depends_on:
                ds = pipeline.stage_by_name(dep)
                if not ds or ds.status != "done":
                    return ""
            self.store.mark_stage(pipeline_name, stage_name,
                                  status="running", started_at=time.time())
            return self._stage_prompt(stage)

    def on_stage_complete(self, pipeline_name: str, stage_name: str, *, error: str = ""):
        with self._lock:
            if error:
                self.store.mark_stage(pipeline_name, stage_name,
                                      status="failed", finished_at=time.time(),
                                      last_error=error)
            else:
                self.store.mark_stage(pipeline_name, stage_name,
                                      status="done", finished_at=time.time(),
                                      last_error="")

    def status_report(self, pipeline_name: str) -> str:
        p = self.store.load(pipeline_name)
        if not p:
            return f"Pipeline {pipeline_name!r} not found"
        lines = [f"Pipeline: {p.name}", f"  Enabled: {p.enabled}", f"  Stages ({len(p.stages)}):"]
        for s in p.stages:
            icon = {"done": "OK", "running": ">>", "failed": "!!",
                    "skipped": "--"}.get(s.status, "??")
            lines.append(f"    [{icon}] {s.name} ({s.kind}) cron={s.cron or '-'}")
        return "\n".join(lines)

    def _stage_prompt(self, stage: Stage) -> str:
        """Translate a stage into the prompt that gets queued for the agent."""
        if stage.kind == "goal":
            return f"/goal {stage.prompt}"
        if stage.kind == "plan":
            return f"/plan {stage.prompt}"
        if stage.kind == "spec":
            return f"/spec {stage.prompt}"
        if stage.kind == "heartbeat":
            return f"/heartbeat {stage.prompt}"
        if stage.kind == "brief":
            return f"/goal draft {stage.prompt}"
        if stage.kind == "verify":
            return f"/goal verify {stage.prompt}"
        if stage.kind == "consolidate":
            return f"/goal {stage.prompt}"
        return stage.prompt


# ---- Default daily pipeline ----

DEFAULT_DAILY_PIPELINE = """# Pipeline: daily

A full-day Agent closed loop. Six stages from morning brief to overnight
memory consolidation. Runs unattended once loaded.

## Stage 1: morning_brief
- kind: brief
- cron: "0 8 * * *"
- delivery: steer
- max_turns: 15
- prompt: |
  Read state.db::session_meta and memory/MEMORY.md.
  Summarize: active goals, unfinished tasks, today's plan.
  One paragraph + 3 actionable items. End with "Ready for the day."

## Stage 2: plan_today
- kind: plan
- cron: "15 8 * * *"
- delivery: auto
- depends_on: morning_brief
- max_turns: 30
- prompt: |
  Review the morning brief. Generate today's plan under
  .zeloo/plans/YYYY-MM-DD.md. Include top 3 priorities, blockers, and
  estimated turns each.

## Stage 3: specs_first
- kind: spec
- cron: "30 8 * * *"
- delivery: auto
- depends_on: plan_today
- max_turns: 60
- prompt: |
  For each new feature in today's plan, write SPEC.md / tasks.md / checklist.md
  under .zeloo/specs/. Do not execute. Do not skip.

## Stage 4: implement_goals
- kind: goal
- cron: "0 9 * * *"
- delivery: steer
- depends_on: specs_first
- max_turns: 200
- prompt: |
  Implement the specs created in stage 3. Continue until all checklist.md
  items are [x] OR until budget is exhausted. Update MEMORY.md as you go.

## Stage 5: evening_summary
- kind: heartbeat
- cron: "0 18 * * *"
- delivery: follow_up
- depends_on: implement_goals
- max_turns: 10
- prompt: |
  Produce evening summary: what got done, what is open, blockers. Save to
  .zeloo/daily/YYYY-MM-DD-summary.md.

## Stage 6: overnight_consolidate
- kind: consolidate
- cron: "0 22 * * *"
- delivery: steer
- depends_on: evening_summary
- max_turns: 50
- prompt: |
  Consolidate today's MEMORY.md entries: dedupe, prune noise, move long-term
  learnings to AGENTS.md if appropriate. Do NOT execute any tasks.
"""
