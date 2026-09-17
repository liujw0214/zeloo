# Pipeline: daily

> 加载优先级:项目 `.zeloo/workspace/PIPELINE.md` > `~/.zeloo/workspace/PIPELINE.md` > 本文件
> **这是 Agent 一天的流水线闭环**。/pipeline load 后,cron + GoalManager 串联各阶段自动续跑,无需人插手。

---

## 概述

一天 6 个阶段,从早 8 点到晚 10 点:

| # | 阶段 | 触发 | 命令 | 预算 |
|---|------|------|------|------|
| 1 | morning_brief | `0 8 * * *` | `/goal draft` | 15 turn |
| 2 | plan_today | `15 8 * * *` | `/plan` | 30 turn |
| 3 | specs_first | `30 8 * * *` | `/spec` | 60 turn |
| 4 | implement_goals | `0 9 * * *` | `/goal` | 200 turn |
| 5 | evening_summary | `0 18 * * *` | `/heartbeat` | 10 turn |
| 6 | overnight_consolidate | `0 22 * * *` | `/goal` | 50 turn |

阶段 1-5 串行;阶段 6 依赖阶段 5。

---

## 语法

每个 `## Stage N: <name>` 块定义一个阶段。字段:

| 字段 | 说明 |
|------|------|
| `kind` | `goal` / `plan` / `spec` / `heartbeat` / `brief` / `verify` / `consolidate` |
| `cron` | 标准 5 字段 cron,无 cron = 永不自动触发(只能手动) |
| `tz` | IANA 时区(默认 `Asia/Shanghai`) |
| `delivery` | `steer` / `follow_up` / `auto`,缺省 `auto` |
| `max_turns` | 该阶段预算 turn |
| `prompt` | 多行 YAML 文本(`- prompt: |` + 缩进块) |
| `depends_on` | 逗号分隔的阶段名,全部 done 才解锁 |
| `enabled` | `true` / `false`,缺省 `true` |

---

## 默认 6 阶段流水线

```yaml
## Stage 1: morning_brief
- kind: brief
- cron: "0 8 * * *"
- delivery: steer
- max_turns: 15
- prompt: |
  Read state.db::session_meta and memory/MEMORY.md.
  Summarize: active goals, unfinished tasks, today\'s plan.
  One paragraph + 3 actionable items. End with "Ready for the day."

## Stage 2: plan_today
- kind: plan
- cron: "15 8 * * *"
- delivery: auto
- depends_on: morning_brief
- max_turns: 30
- prompt: |
  Review the morning brief. Generate today\'s plan under
  .zeloo/plans/YYYY-MM-DD.md. Include top 3 priorities, blockers, and
  estimated turns each.

## Stage 3: specs_first
- kind: spec
- cron: "30 8 * * *"
- delivery: auto
- depends_on: plan_today
- max_turns: 60
- prompt: |
  For each new feature in today\'s plan, write SPEC.md / tasks.md /
  checklist.md under .zeloo/specs/. Do not execute. Do not skip.

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
  Consolidate today\'s MEMORY.md entries: dedupe, prune noise, move
  long-term learnings to AGENTS.md if appropriate. Do NOT execute any tasks.
```

---

## 使用

```bash
# 加载(自动从 workspace_templates/PIPELINE.md)
> /pipeline load

# 列出已加载的流水线
> /pipeline list

# 启动
> /pipeline start daily

# 查看状态
> /pipeline status daily

# 手动触发某个阶段
> /pipeline run morning_brief

# 暂停
> /pipeline pause

# 停止(状态保留,可恢复)
> /pipeline stop
```

---

## 状态持久化

所有阶段进度写入 `state.db::pipeline_stage` 表。崩溃/重启后会从
最近一次 `done` 的阶段之后续跑,不会重复已完成的阶段。
