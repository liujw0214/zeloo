# AGENTS.md — 多 Agent 路由与权限矩阵

> 加载优先级:项目 `.zeloo/workspace/AGENTS.md` > `~/.zeloo/workspace/AGENTS.md` > 本文件
> **这个文件面向用户自己跑的多 Agent 场景**(主 Agent + 多个 subagent 的协作)。
> 它与仓库根目录 `/root/zeloo/AGENTS.md`(开发者贡献指南,**不**同)完全是两回事——
> 那份是给 AI 编程助手读的开发规范,这份是给 Agent 路由器读的能力清单。

---

## 路由器在读这个文件做什么

每个 user message 进入主 Agent 时,路由器会扫 `AGENTS.md` 决定:

1. **意图归属**:这个请求该由主 Agent 处理,还是转发给某个 subagent?
2. **权限检查**:被选中的 agent 在这个 workspace 里能调用哪些工具 / 读哪些路径?
3. **路由回退**:如果首选 agent 不可用(超时 / crash / 被禁),降级到谁?
4. **人类兜底**:什么情况下,必须停下来问用户而不是继续跑?

---

## 已注册 Agent

<!-- 每个 `- id:` 是一个 agent 块。最少要有 main。 -->

```yaml
- id: main
  name: 主 Agent
  role: 通用助理
  owns:
    - 全部 SOUL/IDENTITY/USER 规则
  default_for:
    - "*"        # 未匹配时默认走 main
  can_read:
    - .zeloo/workspace/**
    - ~/.zeloo/workspace/**
  can_write:
    - .zeloo/workspace/**
    - ~/.zeloo/memories/**
  tools:
    - read
    - write
    - edit
    - run_command
    - memory
  escalation: human

- id: research
  name: 调研 Agent
  role: 只读 + 网络搜索,产出 markdown 报告
  default_for:
    - "调研"
    - "搜一下"
    - "看看网上"
  can_read:
    - "**"            # 全读
  can_write:
    - .zeloo/workspace/reports/**
  tools:
    - read
    - web_search
    - web_fetch
  escalation: main   # 拿不准时把控制权交回主 Agent
  timeout_seconds: 120
  max_iterations: 8

- id: coder
  name: 编码 Agent
  role: 改代码、跑测试、提交
  default_for:
    - "改一下"
    - "修这个 bug"
    - "提交"
  can_read:
    - "**"
  can_write:
    - src/**
    - tests/**
    - .zeloo/workspace/code-changes/**
  tools:
    - read
    - write
    - edit
    - run_command
    - git
  escalation: human   # 任何破坏性操作前必须问
  forbidden_paths:
    - "**/.env"
    - "**/secrets/**"
    - "**/*.key"
```

---

## 路由规则

路由器按以下顺序匹配第一条命中的规则:

| 优先级 | 匹配条件 | 目标 Agent | 说明 |
|--------|----------|------------|------|
| 1 | message 含「commit / 提交 / PR」且位于 git repo | `coder` | 编码意图最优先 |
| 2 | message 含「搜 / 调研 / 看看网上 / search」 | `research` | 只读意图 |
| 3 | message 是 `/command` 形式 | `main` | 斜杠命令永远归主 |
| 4 | message 是 simple Q&A / 单行问答 | `main` | 不值得委派 |
| 5 | 其他 | `main` | 默认兜底 |

### 自定义匹配

你可以用 frontmatter 风格在文件顶部写自定义规则:

```yaml
---
# 用户级路由规则(覆盖默认表)
rules:
  - if: contains_any("视频", "剪辑", "剪片")
    target: video_editor
  - if: starts_with("/plan")
    target: planner
---
```

---

## 权限矩阵

> 路径模式支持 glob(`**`、`*`、`?`),不允许正则(避免误伤)。
> 工具名匹配 `tools.registry` 中已注册的工具;未列出的工具 = 拒绝。

| Agent | 读路径 | 写路径 | 可用工具 | 禁止 |
|-------|--------|--------|----------|------|
| `main` | `.zeloo/workspace/**`, `~/.zeloo/**` | 同上 + `~/.zeloo/memories/**` | 全部 | — |
| `research` | `**` | 仅报告目录 | read / web_* | 写代码、git、记忆 |
| `coder` | `**` | `src/**`, `tests/**`, `.zeloo/workspace/code-changes/**` | read/write/edit/run_command/git | `**/.env`, `**/*.key` |

### 权限检查的强制点

每个 agent turn 之前,路由器都会:

1. 解析 message 里的工具调用
2. 对照目标 agent 的 `can_read` / `can_write` / `tools` / `forbidden_paths`
3. 任一不通过 → 返回 `permission_denied` 给主 Agent,主 Agent 转告用户
4. 全通过 → 继续执行

---

## 升级与回退

### 升级到人类(暂停自动行为)

| 触发条件 | 行为 |
|----------|------|
| `coder` agent 要 `git push` / `git reset --hard` | 主 Agent 转交人类,等「确认 / 取消」 |
| `coder` agent 要改 `**/.env*` 或 `forbidden_paths` 命中 | 同上 |
| 任何 agent 连续 3 次失败 | 主 Agent 报告并暂停 |
| 任何 agent 触发 threat scan 拦截 | 立即停,转交人类 |

### 回退到主 Agent

| 触发条件 | 行为 |
|----------|------|
| subagent 超时(默认 120s,可 per-agent 改) | 控制权回主 Agent |
| subagent 迭代数耗尽(`max_iterations`) | 同上 |
| subagent 报告「需要更多上下文」 | 同上 |
| subagent 自爆 stack 或 OOM | 同上 + 主 Agent 记一行 `MEMORY.md` 备忘 |

---

## 与其他 Workspace 文件的关系

| 文件 | 关系 |
|------|------|
| `SOUL.md` | 主 Agent 的 `main` block 严格遵守 SOUL.md;subagent 默认不带 SOUL 风格 |
| `IDENTITY.md` | 只有 `main` 用 IDENTITY.md;subagent 用各自的 `name` / `role` |
| `USER.md` | 所有 agent 共享 USER.md(用户偏好对所有 agent 生效) |
| `MEMORY.md` | 共享 MEMORY.md;但 subagent 写入需要 `owner: agent` 标记,人类删时要询问 |
| `TOOLS.md` | subagent 的 `tools:` 列表是 TOOLS.md 中已启用工具的子集 |
| `HEARTBEAT.md` | 跨 agent 的定时任务可以指定 `agent:` 字段路由到特定 subagent |

---

## 自检清单(手填)

填完这个文件后,跑下面命令逐项验证:

- [ ] 至少定义了一个 `main` agent
- [ ] 每个 agent 都给了 `tools:` 列表(不是空)
- [ ] 每个 agent 都给了 `can_read` / `can_write`(即使只 `[]`)
- [ ] `forbidden_paths` 用 glob 而不是正则
- [ ] 升级规则里至少有一条会转交人类
- [ ] 跑 `Zeloo doctor --check agents-manifest` 没有报错
- [ ] 跑 `Zeloo route test "搜一下 Python 异步"`,确认路由到 `research`

---

> 提示:本文件默认**不**被 `zeloo init` seed(保护用户的多 Agent 拓扑不被覆盖)。
> 手动复制:从 `workspace_templates/AGENTS.md` 复制到 `.zeloo/workspace/AGENTS.md` 即可。
> 删除后回退到根 `AGENTS.md` 的开发者贡献语义(不推荐)。
