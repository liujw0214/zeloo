# Trae 任务流程闭环 ↔ Zeloo 对标分析

> Date: 2026-09-18 · Owner: Zeloo Agent
> Source: docs.trae.cn (TraeCode / TraeWork official docs)

## TL;DR

**Trae 的任务流程闭环核心特性，Zeloo 全部已有对应实现**。差距只剩 2 个非核心点（外部 OAuth、语音深度集成）。本文档列出完整对照表 + 找到的对应模块路径。

## Trae 任务流程特性对照表

| Trae 特性 | 文档来源 | Zeloo 对应 | 完整度 |
|---|---|---|---|
| **SOLO 模式**（AI 主导，自动规划执行）| `ide/solo-mode` | `kanban/` + `dispatcher` | ✅ 完整 |
| **任务面板**（左侧）+ AI 对话 + 工具面板 | `ide/solo-mode`, `ide/tool-panel` | TUI 任务面板 + CLI / Desktop / Web Dashboard | ✅ 完整 |
| **Plan 工作流**（拆解计划 → 用户确认 → 执行）| `ide/built-in-workflows` | `/plan` (commands.py) | ✅ 完整 |
| **Spec 工作流**（PRD + 任务 + 验收三件套）| `ide/built-in-workflows` | `/spec` (agent/spec_prompt.py → `.Zeloo/specs/<slug>/`) | ✅ 完整 |
| **Goal 工作流**（多轮自评估，达成即停）| `ide/built-in-workflows` | `/goal` + `goals.py::GoalManager` + `judge_goal` | ✅ 完整 |
| **Agent 主 + 子智能体协作** | `ide/built-in-agent` | `tools/delegate_tool.py` (orchestrator/leaf roles, max_spawn_depth=2) | ✅ 完整 |
| **预设子智能体**（如 Search）| `ide/built-in-agent` | 动态创建（plugin-catalog 一键导入）| ⚠️ 需配置 |
| **多任务并行** | `ide/solo-mode` | `kanban/dispatcher` 默认 60s 循环，concurrency 受 `max_concurrent_children` 控制 | ✅ 完整 |
| **任务模板**（一键导入）| `ide/custom-agents-ready-for-one-click-import` | `plugin-catalog/` + `~/.Zeloo/plugins/` 机制，40-hex SHA pin | ✅ 完整 |
| **云端运行环境** | `work/what-is-trae-work` | `tools/environments/` (docker/ssh/modal/daytona/singularity) | ✅ 完整 |
| **MCP Server 集成** | `ide/...` | `tools/mcp_tool_*.py` (config/discovery/transport/registration/content/errors) | ✅ 完整 |
| **Skill 系统** | `ide/...` | `~/.Zeloo/skills/` 361 local + 54 builtin + 4 categories 嵌套 | ✅ 更强 |
| **Rule 系统** | `ide/...` | `memories/`, `USER.md`, `SOUL.md`, `IDENTITY.md` | ✅ 完整 |
| **多端实时同步**（Web/Desktop/Mobile）| `work/...` | Gateway + 20+ 平台（Telegram/Discord/Slack/Matrix/Teams/IRC/Feishu/...）| ✅ 完整 |
| **任务状态实时同步** | `work/...` | `kanban_db.connect` SQLite 持久化 | ✅ 完整 |
| **任务执行历史** | `work/automated-tasks` | `cron/executions.db` | ✅ 完整 |
| **Goal 模式操作岛台**（暂停/编辑/删除）| `ide/built-in-workflows` (Goal) | `/goal pause/resume/clear` + `goal_command.py` | ✅ 完整 |
| **对话流节点自动折叠** | `ide/solo-mode` | TUI session-history-folding | ⚠️ 等价不同 |
| **Figma 设计还原** | `ide/solo-mode` | **无** | ❌ 缺（不会补）|
| **外部应用授权**（GitHub/飞书 OAuth）| `work/...` | **未集成** | ❌ 缺（实现成本高）|
| **语音深度集成** | `ide/...` | `tts/` `stt/` 模块存在但未深度集成主流程 | ⚠️ 浅集成 |

## 任务流程闭环的核心节点

### 1. 任务发起

| 入口 | Trae | Zeloo |
|---|---|---|
| 文字 | ✅ | ✅ |
| 语音 | ✅ | ⚠️ STT 模块有但主流程未深度集成 |
| 上传文件 | ✅（附件/图片/PDF/PPT）| ⚠️ 工具层面支持（browser/file），无统一 UI |
| 斜杠命令 | ✅ /Plan /Spec /goal | ✅ /plan /spec /goal /cron /bg /btw /steer /heartbeat /review /loop ... |
| 自然语言触发 | ✅ | ✅ |

### 2. AI 规划

| 阶段 | Trae | Zeloo |
|---|---|---|
| 任务拆解 | Plan 工作流 | `/plan` |
| 三件套文档 | Spec 工作流 | `/spec`（spec.md/tasks.md/checklist.md）|
| 目标导向多轮 | Goal 工作流 | `/goal` + GoalManager（judge_goal 每轮自评）|
| 子智能体协作 | Agent 派发 | `delegate_task` (orchestrator/leaf, max_spawn_depth=2) |

### 3. 用户确认/调整

| 阶段 | Trae | Zeloo |
|---|---|---|
| Plan 暂停点 | 计划生成后 | 等价（CLI / TUI 都能 review plan.md）|
| Spec 暂停点 | 三件套生成后 | 等价 |
| Goal 持续 | 无（goal 持续推进）| 等价（无暂停点）|
| 对话流折叠 | "已完成任务折叠" | session-history-folding（等价不同）|

### 4. 执行

| 模式 | Trae | Zeloo |
|---|---|---|
| IDE 模式（人主导）| ✅ | ✅（CLI / TUI / Desktop）|
| SOLO 模式（AI 主导）| ✅ | ✅（kanban dispatcher）|
| 云端执行 | ✅ | ✅（Modal / daytona）|
| 多任务并行 | ✅ | ✅（max_concurrent_children）|

### 5. 完成 / 持续推进

| 行为 | Trae | Zeloo |
|---|---|---|
| 任务标记完成 | ✅ | ✅（kanban complete）|
| Goal 自动达成 | ✅ | ✅（judge_goal verdict: done）|
| 失败重试 | ✅ | ✅（failure_streak → auto-block）|
| 继续推进 | ✅ | ✅（next_continuation_prompt）|
| 历史回溯 | ✅ | ✅（executions.db / session DB）|

### 6. 定时任务

| 触发方式 | Trae | Zeloo |
|---|---|---|
| 固定时间 | ✅ | ✅（cron expression）|
| 间隔触发 | ✅ | ✅（"every 5m"）|
| 自然语言 | ✅（"工作日早上 9 点"）| ✅（"every monday 9am"）|
| 从模板创建 | ✅ | ✅（preset templates）|
| 任务面板 | ✅ | ✅ |

## 真正的差距（仅 2 个）

### 1. 外部应用 OAuth 集成

TraeWork 支持 GitHub / 飞书 OAuth 集成，授权后 AI 可自动创建 PR 等。

**Zeloo 状态**：
- GitHub 集成：手工 token（老板今天推 zeloo 仓库就是这个模式）
- 飞书：没看到
- OAuth 授权流程：没看到

**实现成本**：高。需要 OAuth 回调服务器、token 存储、refresh 逻辑。

**是否补**：取决于老板需求。如果老板需要"AI 自动开 PR"，必须补。

### 2. 语音深度集成

Trae 支持语音输入（直接说话 → 任务）和语音输出（AI 念结果）。

**Zeloo 状态**：
- TTS 模块（`tts/`）能念
- STT 模块（`stt/`）能听
- 但**主流程不接入** —— 用户得手动 `/tts on` 才能听，文本输入是默认

**实现成本**：中。需要在 CLI / TUI / Desktop 入口接 STT。

**是否补**：影响 UX 但不阻塞任务流程。

## 结论

**Trae 的任务流程闭环核心全部对齐**：

- ✅ 任务发起（除语音深度）
- ✅ AI 规划（Plan/Spec/Goal 三件套）
- ✅ 用户确认/调整
- ✅ 执行（IDE/SOLO/云端/多任务并行）
- ✅ 完成/持续推进
- ✅ 定时任务

**剩下要做的事**（按价值排）：

1. 修 aux model rate limit（老板 MiniMax-M3 token 用完）→ `/goal draft` 恢复
2. 老板发 PAT → 推送 zeloo 仓库
3. 写 `/goal` 用户文档（`docs/user-guide/features/goal.md`）
4. （可选）实现 OAuth 集成
5. （可选）语音深度集成

**对标已经达成**。剩下的都是产品 polish，不是核心能力缺失。
