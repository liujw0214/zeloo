# 30. 子包 AGENTS.md 工作流规范

> Zeloo 每个子包都包含 `AGENTS.md`，定义 AI 在该包内工作时的行为规范。本文档记录 Zeloo 各子包 AGENTS.md 的设计规范。

## 30.1 规范总览

| 目录 | AGENTS.md 状态 | 优先级 |
|------|----------------|--------|
| `agent/` | 已存在 | ✅ 已实现 |
| `gateway/` | 已存在 | ✅ 已实现 |
| `tools/` | 已存在 | ✅ 已实现 |
| `mcp/` | 已存在 | ✅ 已实现 |
| `cron/` | 已存在 | ✅ 已实现 |
| `plugins/` | 已存在 | ✅ 已实现 |
| `skills/` | 已存在 | ✅ 已实现 |
| `optional-skills/` | 已存在 | ✅ 已实现 |
| `tui_gateway/` | 已存在 | ✅ 已实现 |
| `evals/` | 已存在 | ✅ 已实现 |
| `datagen/` | 已存在 | ✅ 已实现 |

---

## 30.2 cron/AGENTS.md（P2）

```markdown
# cron/AGENTS.md

## 本包职责

定时任务调度系统。处理 cron 表达式的解析、任务的调度执行、失败重试和监控。

## 工作规范

### 调度格式

支持以下格式，按优先级尝试解析：
1. 自然语言（如 "every 2 hours", "at 9am"）
2. 5 字段 Cron 表达式（如 `0 9 * * *`）
3. ISO 时间戳（如 `2026-01-01T09:00:00Z`）
4. Duration（如 `30m`, `2h`, `7d`）

### 任务执行

- 使用独立的线程池执行任务，不阻塞主 Agent
- 任务执行结果记录到执行历史
- 失败任务自动重试（最多 N 次）
- 硬中断：任务执行超过 3 分钟强制终止

### 防重复

使用文件锁（`~/.Zeloo/cron/locks/`）防止同一任务在多实例环境下重复执行。

### 注意事项

- 不要在 cron 任务中执行长时间阻塞操作
- 遇到失败先记录日志，不阻塞主流程
- 优先使用无 agent 的纯脚本模式节省 token
```

---

## 30.3 skills/AGENTS.md（P2）

```markdown
# skills/AGENTS.md

## 本包职责

内置技能集（14 类别）。每个技能是 `SKILL.md` 文件定义的独立工作流。

## 技能加载

- 启动时扫描 `skills/` 下所有 `SKILL.md`
- 自动注册到技能注册表
- 支持按类别过滤加载

## 技能调用

1. Agent 判断当前任务是否适合某个技能
2. 加载技能描述注入 system prompt
3. Agent 按技能步骤执行任务
4. 任务完成后，Curator 评估是否值得固化

## 技能格式

```markdown
# skills/<category>/<name>/SKILL.md
---
name: skill-name
description: 一句话描述
author: Zeloo
tags: [tag1, tag2]
version: 1.0.0
---

# Skill Name

## Triggers（触发条件）
- "触发短语1"
- "触发短语2"

## Steps（执行步骤）
1. 步骤一
2. 步骤二
3. 步骤三

## Examples（示例）
...
```

## 注意事项

- 技能命名使用 kebab-case
- 描述不超过 50 字
- 每个技能至少 2 个触发短语
- 敏感信息不得写入技能内容
```

---

## 30.4 optional-skills/AGENTS.md（P2）

```markdown
# optional-skills/AGENTS.md

## 本包职责

可选技能集（22 类别），默认不启用。用于专业化或较重的技能。

## 与 skills/ 的区别

| 维度 | skills/ | optional-skills/ |
|------|---------|-------------------|
| 启用方式 | 默认启用 | 需在 config.yaml 中显式配置 |
| 体积 | 轻量 | 可能包含额外依赖 |
| 维护 | 随仓库更新 | 可独立发布 |
| 场景 | 通用工作流 | 专业领域 |

## 启用方式

```yaml
skills:
  optional_categories:
    - software-development
    - devops
    - data-science
```

## 注意事项

- 可选技能可能需要额外依赖（如数据库客户端）
- 首次使用前检查依赖是否已安装
- 可选技能由独立仓库维护时，遵循其更新节奏
```

---

## 30.5 tui_gateway/AGENTS.md（P3）✅ 已实现

**状态：** ✅ **全部组件已实现并测试通过**（2026-09）

```markdown
# tui_gateway/AGENTS.md

## 本包职责

TUI 网关运行时，处理终端界面的事件路由、Agent 回调、计费显示。

## 核心组件

- `agent_callbacks.py`：Agent 状态变更回调 ✅ CallbackRegistry + 7 种事件 + 订阅/退订
- `billing_view.py`：计费视图显示 ✅ BillingSnapshot + UsageTracker 集成
- `change_watcher.py`：文件变更监视 ✅ 轮询式（mtime+size）
- `compute_host.py`：计算主机管理 ✅ ComputeHost + 资源探测

## 注意事项

- TUI 网关仅处理事件路由，不执行业务逻辑
- 所有 Agent 调用通过 `agent_callbacks.py` 回调
- 计费视图实时更新，不缓存
```

**实现摘要：**

| 文件 | 行数 | 关键能力 |
|------|------|----------|
| `agent_callbacks.py` | 160 | AgentEvent / 7 种类型 / CallbackRegistry / 历史记录 |
| `billing_view.py` | 60 | BillingSnapshot / BillingView / UsageTracker 集成 |
| `change_watcher.py` | 80 | WatchEvent / ChangeWatcher / 5 类回调 |
| `compute_host.py` | 110 | HostInfo / ComputeHost / psutil 探测 |
| `__init__.py` | 40 | 统一导出 17 个公开符号 |

---

## 30.6 evals/AGENTS.md（P3）

```markdown
# evals/AGENTS.md

## 本包职责

评测套件（17 个子模块），用于验证 Agent 能力的正确性和性能。

## 评测分类

| 子目录 | 描述 |
|--------|------|
| `browser_use/` | 浏览器使用能力 |
| `compaction/` | 压缩效果评测 |
| `core_tool_deferral/` | 工具延迟评测 |
| `readtool/` | 读取工具评测 |
| `token_accounting/` | Token 计费评测 |

## 评测执行

```bash
python -m pytest evals/ -v --eval-name=compaction
```

## 注意事项

- 评测结果应与基准对比，检测回归
- 敏感评测数据脱敏后存储
- 评测失败不阻塞主流程，但需记录
```

---

## 30.7 datagen/AGENTS.md（P3）

```markdown
# datagen/AGENTS.md

## 本包职责

数据生成与轨迹压缩，为训练数据生成做准备。

## 核心组件

- `compress_trajectories.py`：轨迹压缩
- `extract_trajectories.py`：训练数据导出

## 轨迹格式

```python
{
    "session_id": "sess_xxx",
    "turn_id": 1,
    "user_message": "...",
    "tool_call_count": 5,
    "tool_calls": [...],
    "assistant_response": "...",
}
```

## 压缩策略

保留首尾轮原文，中间轮次摘要。节省约 70% 存储成本。

## 注意事项

- 轨迹数据不得包含 API 密钥
- 导出数据脱敏后可用于训练
- 压缩后的轨迹仍可还原关键信息
```

---

## 30.7 AGENTS.md 模板

```markdown
# <directory>/AGENTS.md

## 本包职责

一句话描述本包的职责范围。

## 核心组件

简要列出本包的关键模块及其职责。

## 工作规范

1. 规范一
2. 规范二
3. 规范三

## 注意事项

- 注意一
- 注意二
```
