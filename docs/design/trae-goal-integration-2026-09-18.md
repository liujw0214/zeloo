# TraeWork Goal ↔ Zeloo `/goal` 集成说明

> Date: 2026-09-18 · Owner: Zeloo Agent

## TL;DR

TraeWork Goal 工作流的所有核心特性，Zeloo `/goal` 都已有完整实现：

| TraeWork Goal | Zeloo `/goal` 实现位置 | 状态 |
|---|---|---|
| Goal-oriented multi-round loop | `zeloo_cli/goals.py::GoalManager` + `judge_goal()` | ✅ |
| Completion contract (auto-draft) | `goals.draft_contract(plain_language_goal)` | ✅ |
| Structured contract fields | `GoalContract` (outcome/verification/constraints/boundaries/stop_when) | ✅ |
| Pause / resume | `/goal pause`, `/goal resume` | ✅ |
| Gates (preconditions) | `/goal gate add`, `GoalGate`, `workspace_fingerprint`, `run_gate` | ✅ |
| Wait barrier (PID, deadline) | `/goal wait <pid>`, `waiting_on_pid`, `waiting_until` | ✅ |
| Subgoals (extra criteria) | `/subgoal`, `GoalState.subgoals` | ✅ |
| Budget control | `max_turns`, `turns_used` | ✅ |
| Self-evaluation per turn | `judge_goal` runs every turn, verdict: done / blocked / continue / wait / skipped | ✅ |
| Failure tolerance | `consecutive_parse_failures`, `consecutive_transport_failures` | ✅ |
| Persistence (per-session) | `load_goal` / `save_goal` / `clear_goal` (state.db::goals) | ✅ |
| Multi-surface dispatch | `dispatch_goal_command` shared by CLI / TUI / Desktop / Gateway | ✅ |

## Pipeline integration

`agent/pipeline.py::PipelineRunner._stage_prompt` already translates stage kinds
into `/goal`, `/plan`, `/spec`, `/heartbeat` slash commands:

```python
if stage.kind == "goal":       return f"/goal {stage.prompt}"
if stage.kind == "plan":       return f"/plan {stage.prompt}"
if stage.kind == "spec":       return f"/spec {stage.prompt}"
if stage.kind == "brief":      return f"/goal draft {stage.prompt}"
if stage.kind == "verify":     return f"/goal verify {stage.prompt}"
if stage.kind == "consolidate": return f"/goal {stage.prompt}"
```

So the daily 6-stage pipeline (morning_brief → plan_today → specs_first →
implement_goals → evening_summary → overnight_consolidate) is essentially a Goal
goal-pipeline graph driven by cron.

## What's missing (open work)

1. **Cron → PipelineRunner hook**: `PipelineRunner.on_cron_tick()` exists but no
   actual cron scheduler invokes it. Either:
   - Add a crontab entry that calls a CLI hook, or
   - Bridge through the existing `cron/` subsystem in Zeloo, or
   - Run `PipelineRunner` as a long-lived background process with its own scheduler.

2. **Pipeline → Goal binding**: a Pipeline stage of kind=goal currently emits
   `/goal <prompt>` text, but the stage's running/done status is owned by
   `PipelineStore` (state.db::pipeline_state), not by `GoalManager`
   (state.db::goals). To unify, decide which DB is canonical and bridge the other.

3. **CLI tests**: `tests/` does not appear to have `test_goal_*.py`. Suggested coverage:
   - GoalContract parse/draft round-trip
   - judge_goal verdict logic (done / blocked / continue / wait / skipped)
   - Gate run_gate / workspace_fingerprint integration
   - dispatch_goal_command per-subcommand (status/show/pause/resume/clear/wait/gate)

4. **Goal docs for end users**: no user-facing guide. `/goal` is powerful but
   invisible to non-CLI users (gateway, Telegram, Slack need quickstart).

## Verification

Ran `/goal draft` directly via Python:

```
draft_contract("完成 zeloo 仓库的清理和推送") →
  GoalContract(
    outcome: zeloo 仓库完成清理（移除临时文件、未追踪垃圾、敏感信息）...
    verification: git status 显示工作区干净；git log 显示包含清理操作的最新 commit...
    constraints: 不得删除 .git 目录、不得丢失已存在的合法源码文件、不得修改 .gitignore...
    boundaries: 仅限当前 zeloo 仓库目录内的文件操作...
    stop_when_blocked: git push 因权限/网络/远端冲突（如 non-fast-forward）失败时停止...
  )
```

Returns a non-empty contract within ~1 second using the configured auxiliary
model (no manual contract drafting required for users).

## Source links

- TraeWork Goal workflow docs:
  - https://docs.trae.cn/ide_built-in-workflows (Plan/Spec/Goal)
  - https://docs.trae.cn/work_spec-and-plan.md (TraeWork variant)
- Zeloo `/goal` source:
  - `zeloo_cli/goal_command.py` (194 lines, command dispatch + parsing)
  - `zeloo_cli/goals.py` (~1000 lines, GoalManager + judge_goal + GoalContract + GoalGate)
  - `agent/pipeline.py` (528 lines, PipelineRunner + STAGE_TYPES incl. "goal")
  - `zeloo_cli/cli_commands_mixin.py::ZELOOCLI._handle_goal_command` (line 2260)
