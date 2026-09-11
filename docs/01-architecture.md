# 01. 整体架构设计

## 1.1 设计哲学

Zeloo（前名 Zeloo）采用**分层组合式架构**，核心设计哲学是：

> **循环保持简洁，能力通过组合扩展。**

- 核心对话循环（Agent Loop）精简到不足 10 行
- 所有业务能力以**工具（Tool）**、**技能（Skill）**、**插件（Plugin）**形式挂载
- 框架层只负责调度、缓存、安全边界，不耦合具体业务逻辑

## 1.2 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                      用户交互层                               │
│   CLI / TUI  │  消息网关 (21 平台) │  MCP Server │ ACP Adapter │
├─────────────────────────────────────────────────────────────┤
│                      Agent 核心层                             │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │ SystemPrompt │  │ ConversationLoop │  │ ToolRegistry  │  │
│  │  (三层架构)   │←→│  (思考-行动循环)  │←→│  (自动发现)   │  │
│  └──────────────┘  └──────────────────┘  └───────────────┘  │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │CredentialPool│  │ ErrorClassifier  │  │ HookRegistry  │  │
│  │ (多Key轮询)   │  │ (结构化错误分类)  │  │ (生命周期钩子) │  │
│  └──────────────┘  └──────────────────┘  └───────────────┘  │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │   Curator    │  │     Kanban       │  │   Insights    │  │
│  │ (技能生命周期)│  │ (多智能体看板)    │  │ (运行时洞察)   │  │
│  └──────────────┘  └──────────────────┘  └───────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                      能力扩展层                               │
│  Skills │ Memory(9后端) │ Cron │ Subagent │ CodeExec │ MCP  │
├─────────────────────────────────────────────────────────────┤
│                      基础设施层                               │
│  SQLite(FTS5+WAL) │ 终端后端(7种) │ Provider(2+ 适配器) │ 插件系统  │
│  i18n(2 语言) │ 安全策略 │ estop 紧急停止                      │

### 1.2.1 7 种终端后端

从 $5 VPS 到 GPU 集群到 serverless 全覆盖：

| 后端 | 适用场景 |
|------|----------|
| `local` | 本地开发调试，零配置 |
| `docker` | 隔离环境运行，CI/CD |
| `ssh` | 远程服务器执行 |
| `modal` | 云端 serverless，持久化休眠 |
| `daytona` | 云端 serverless，持久化休眠 |
| `vercel_sandbox` | Vercel 沙箱执行 |
| `singularity` | HPC 环境，学术/科研 |
```

## 1.3 核心模块职责

| 模块 | 职责 | 变化频率 |
|------|------|----------|
| **SystemPrompt** | 组装三层 system prompt，管理 prefix cache | 会话级 |
| **ConversationLoop** | 思考-行动循环，迭代预算控制，中断处理 | 每轮 |
| **ToolRegistry** | 工具自动发现、注册、Schema 生成 | 启动时 |
| **Skills** | 渐进披露的知识文档，按需加载 | 运行时可变 |
| **Memory** | 持久记忆 + 用户画像，跨会话累积 | 运行时可变 |
| **Subagent** | 隔离子代理委托，零知识隔离 | 按需 |
| **Cron** | 定时任务调度，支持纯脚本模式 | 按需 |
| **Gateway** | 多平台消息统一接入 | 常驻 |
| **Provider** | 多 LLM Provider 路由、熔断、降级 | 每轮 |
| **CredentialPool** | 多 API Key 轮询、熔断、环境变量回退 | 运行时 |
| **ErrorClassifier** | 结构化错误分类与重试/降级策略 | 每轮 |
| **HookRegistry** | 插件生命周期钩子调度 | 启动时注册 |
| **MCPServer** | 将 Zeloo 工具暴露为 MCP 服务 | 常驻 |
| **ACPAdapter** | IDE 集成协议适配 | 常驻 |
| **Curator** | 技能生命周期管理（active→stale→archived） | 定期 |
| **Kanban** | 多智能体协作看板（心跳/回收/僵尸检测） | 运行时 |
| **Insights** | 运行时指标采集与洞察报告生成 | 每轮 |
| **i18n** | 多语言国际化（当前 2 语言 YAML 包） | 启动时 |
| **Estop** | 全局紧急停止机制 | 按需 |

## 1.4 核心数据流

```
用户消息
  │
  ▼
Gateway / CLI 接收
  │
  ▼
AIAgent.run_conversation(message)
  │
  ├─► 构建/复用 System Prompt (三层缓存)
  │
  ├─► Conversation Loop:
  │     │
  │     ├─► LLM API 调用 (system + messages + tools)
  │     │
  │     ├─► 有 tool_calls?
  │     │     ├─ 是 → 并行执行工具 → 结果追加到 messages → 循环
  │     │     └─ 否 → 返回最终内容
  │     │
  │     └─► 检查迭代预算 / 中断请求
  │
  └─► Turn Finalizer:
        ├─► 记忆写入 (MEMORY.md / USER.md)
        ├─► 技能固化评估
        ├─► 轨迹采集
        └─► 后台复盘 fork (异步)
```

## 1.5 关键设计决策

### 1.5.1 单体进程 + 隔离子代理

- 主 Agent 运行在单进程内，保证状态一致性
- `delegate_task` 生成的子代理在**独立线程/进程**中运行，仅接收 goal + context，**零知识隔离**（不共享主 Agent 状态）
- 子代理结果通过消息队列回传，避免共享内存竞争
- **子代理配置**：最大并发子 Agent 数 3，最大嵌套深度 2，子 Agent 超时 300 秒

**子代理角色**：

| 角色 | 权限 | 使用场景 |
|------|------|----------|
| `leaf`（默认） | 无 delegate_task/clarify/memory | 专注的工作者任务 |
| `orchestrator` | 保留 delegate_task | 可生成自己的 workers，复杂任务分解 |

### 1.5.2 状态持久化

- 会话状态存储在 SQLite（WAL 模式），支持 FTS5 全文搜索
- 记忆/技能以 Markdown 文件存储在 `~/.Zeloo/`，便于人工编辑和版本管理
- 两个 Agent 进程**不能共享** `~/.Zeloo` 目录（避免状态冲突）

### 1.5.3 Provider 无关性

- 所有 LLM 调用通过 OpenAI 兼容协议
- Provider 路由层支持：白名单/黑名单、优先级排序、自动熔断降级、多 Key 轮询
- 系统提示词中不硬编码任何 Provider 特定行为（通过模型门控动态注入）

### 1.5.4 Smart Model Routing（智能模型路由）

简单请求（短输入、无复杂关键词）自动路由到更便宜的模型，
降低成本同时不影响复杂任务质量。

**判定规则**（同时满足）：
- 字符数 ≤ `max_simple_chars`（默认 160）
- 单词数 ≤ `max_simple_words`（默认 28）
- 不包含复杂关键词（debug、fix、implement、security、sql 等）

**配置**（`config.yaml`）：

```yaml
smart_model_routing:
  enabled: true
  max_simple_chars: 160
  max_simple_words: 28
  cheap_provider: openai
  cheap_model: gpt-4o-mini
```

主模型在该轮结束后自动恢复，不影响后续对话。

### 1.5.5 Provider 原生 Prompt Caching

OpenAI、Anthropic 等 Provider 支持 prompt caching：对重复的系统提示词和历史消息只计费一次，
大幅降低长会话成本。Zeloo 在 LLM 调用后自动从响应中提取缓存统计信息。

**统计方式**：
- OpenAI 格式：`usage.prompt_tokens_details.cached_tokens`
- Anthropic 格式：`usage.cache_read_input_tokens`

**输出**：
- `prompt_cache_hit_ratio` 属性实时计算命中率
- 每轮对话结束时日志输出，如 `Prompt cache hit ratio: 80.0% (800/1000 cached tokens)`

**配置**（`config.yaml`）：

```yaml
prompt_caching:
  enabled: true
```

缓存统计仅做观测，不影响请求本身；Provider 是否缓存由其服务端策略决定。

### 1.5.6 Credential Pool（凭证池）

集中管理所有 Provider 的 API Key，支持多 Key 轮询与自动熔断。

**核心能力**：
- **多 Key 轮询**：同一 Provider 配置多个 Key，round-robin 轮换，分散限流压力
- **自动熔断**：401/403 认证失败时永久禁用该 Key；其他错误累计达阈值后禁用
- **冷却恢复**：非致命错误触发临时冷却（默认 300s），冷却结束后自动恢复
- **环境变量回退**：池中无可用 Key 时，回退到 `zeloo_<PROVIDER>_API_KEY` 环境变量
- **加密持久化**：凭证存储在本地 JSON 文件，权限设为 0600

**配置**（`config.yaml`）：

```yaml
credential_pool:
  storage_path: ~/.Zeloo/credentials.json
  cooldown_seconds: 300
  max_failures: 3
```

### 1.5.7 Error Classifier（错误分类器）

将原始异常和 LLM 错误响应转化为结构化分类，提供统一的重试/降级策略。

**错误类别**：

| 类别 | 触发条件 | 可重试 | 降级 Provider |
|------|----------|--------|---------------|
| AUTH | 401/403 或 invalid api key | 否 | 是 |
| RATE_LIMIT | 429 或 rate limit 提示 | 是（30s） | 是 |
| TIMEOUT | 超时异常 | 是（10s） | 是 |
| SERVER_ERROR | 5xx | 是（5s） | 是 |
| CONTEXT_OVERFLOW | context length exceeded | 是（压缩后） | 否 |
| CONTENT_FILTER | content policy violation | 否 | 否 |
| NETWORK | 连接错误 | 是（5s） | 是 |
| VALIDATION | 400/422 参数错误 | 否 | 否 |

**用法**：

```python
from agent.error_classifier import classify_error

result = classify_error(exc, provider="openai", status_code=429)
if result.retryable:
    await asyncio.sleep(result.retry_delay_seconds)
if result.should_fallback_provider:
    router.switch_to_next()
```

### 1.5.8 Plugin Lifecycle Hooks（插件生命周期钩子）

插件可注册回调，在 Agent 运行的关键节点被触发，实现观测、修改或拦截操作。

**支持的钩子类型**：

| 钩子 | 签名 | 用途 |
|------|------|------|
| `pre_tool_call` | `(tool_name, args) -> dict \| None` | 工具调用前拦截/修改参数 |
| `post_tool_call` | `(tool_name, args, result) -> Any` | 工具调用后修改结果 |
| `pre_llm_call` | `(messages, tools) -> tuple \| None` | LLM 调用前修改上下文 |
| `post_llm_call` | `(response) -> dict \| None` | LLM 调用后修改响应 |
| `on_session_start` | `(session_id) -> None` | 会话开始通知 |
| `on_session_end` | `(session_id) -> None` | 会话结束通知 |
| `transform_llm_output` | `(content) -> str | None` | 最终输出文本转换 |
| `on_conversation_start` | `(session_id) -> None` | 对话开始通知 |
| `on_conversation_end` | `(session_id, summary) -> None` | 对话结束通知 |

**注册方式**：插件的 `register(registry, skills_manager, hooks)` 入口接收 `HookRegistry`，调用 `hooks.register(HookType.PRE_TOOL_CALL, callback, "plugin_name")` 即可。钩子异常被捕获并记录，不会中断 Agent 运行。

### 1.5.9 MCP Server（MCP 服务端）

Zeloo 不仅能作为 MCP 客户端调用外部工具，还能作为 MCP 服务端，将自身工具暴露给其他 AI Agent / IDE 使用。

**支持的 MCP 方法**：
- `initialize` / `notifications/initialized`：握手
- `tools/list`：列出所有已注册工具的 schema
- `tools/call`：执行指定工具并返回结果
- `ping`：健康检查

**启动方式**：

```bash
python -m mcp_serve
```

可通过 `toolset_filter` 参数限制暴露的工具集，避免将危险工具（如 shell）暴露给外部。

### 1.5.10 ACP Adapter（IDE 集成适配器）

ACP（Agent Client Protocol）适配器让 Zeloo 能被 IDE（VS Code、Cursor 等）直接调用，实现 IDE 内的 AI 助手能力。

**核心消息类型**：
- `initialize` / `initialized`：协议握手
- `session/new`：创建新会话
- `session/end`：结束会话
- `message`：发送用户消息，Agent 返回响应
- `message/update` / `message/end`：流式输出与结束

**启动方式**：

```bash
python -m acp_adapter
```

### 1.5.11 Curator（技能生命周期管理）

Curator 管理技能的完整生命周期，确保技能库始终保持高质量。

**状态机**：

```
active ──(N 天未使用)──► stale ──(M 天仍未使用)──► archived
  ▲                         │                          │
  └──── 使用技能重新激活 ◄────┴──────────────────────────┘
```

**核心原则**：
- **永不删除**：技能只被归档，不删除（可恢复）
- **使用即激活**：Agent 使用某技能时，自动从 stale/archived 恢复为 active
- **后台评估**：定期运行 `run_cycle()` 评估所有技能的活跃度

**配置**（`config.yaml`）：

```yaml
curator:
  enabled: true
  stale_after_days: 30      # 30 天未使用 → stale
  archive_after_days: 90    # 90 天仍未使用 → archived
```

**状态文件**：`~/.Zeloo/skills/.curator_state.json`，记录每个技能的状态、最后使用时间、使用次数。

### 1.5.12 Kanban（多智能体协作看板）

v0.13.0 引入的持久化多智能体协作系统，支持复杂任务的分工与追踪。

**隔离模型**：`Board`（硬边界）→ `Tenant`（软命名空间）→ `Worker`

**核心机制**：
- **心跳机制**：Worker 定期调用 `heartbeat(task_id)` 报告存活
- **僵尸检测**：超过 `zombie_timeout_seconds`（默认 300s）无心跳的任务被自动回收
- **重试预算**：失败任务自动重试，超过 `max_retries` 后标记为 BLOCKED
- **优先级排序**：任务按 priority + created_at 排序

**任务状态流转**：

```
todo ──assign──► in_progress ──complete──► completed
  ▲                  │
  │                  └──fail──► todo (retry) / blocked (exhausted)
  └──── reclaim zombie ────────┘
```

**配置**（`config.yaml`）：

```yaml
kanban:
  enabled: true
  zombie_timeout_seconds: 300
  default_max_retries: 3
```

### 1.5.13 Insights（运行时洞察）

采集运行时指标并生成可操作的洞察报告，帮助用户优化 Agent 行为。

**采集指标**：
- 工具调用统计（次数、平均耗时、错误率）
- 错误分类计数（来自 ErrorClassifier）
- Token 用量（按小时聚合）
- 会话统计（会话数、平均迭代次数）

**报告内容**：
- 摘要（总会话数、总迭代数、平均迭代/会话）
- Token 用量（近 1 小时）
- Top 10 工具（调用次数、平均耗时、错误数）
- Top 5 错误类别
- 自动生成的优化建议（高 Token 用量、高错误率工具等）

### 1.5.14 i18n（国际化）

基于 YAML 的轻量国际化系统，支持 2 种语言（en/zh-CN）。

**语言文件位置**：`locales/<lang>.yaml`

**核心 API**：

```python
from agent.i18n import gettext, set_language

set_language("zh-CN")
print(gettext("hello_world"))  # "你好，世界"
print(gettext("tool_call_failed", tool="file_read"))  # 支持 {var} 占位符
```

**已支持语言**：en（默认）、zh-CN，其余语言按需添加。线程安全，每个线程可独立设置语言。

### 1.5.15 Estop（紧急停止）

全局紧急停止机制，可立即终止所有 Agent 活动。

**触发场景**：
- 用户主动请求停止
- 检测到安全威胁（Prompt 注入、越权操作）
- 资源耗尽（内存、磁盘）

**行为**：
- 对话循环在下一次迭代边界退出
- 待执行的工具调用被取消
- 不再发起新的 LLM 调用

**API**：

```python
from agent.estop import estop

estop.trigger(reason="User requested stop", by="user")
if estop.is_stopped():
    return
estop.reset()  # 解除停止
```

支持嵌套触发（栈式），多个子系统可独立请求停止。

## 1.6 非功能需求

| 维度 | 要求 |
|------|------|
| 上下文窗口 | 最低 64K tokens |
| 冷启动时间 | < 3s（本地后端） |
| 工具调用延迟 | < 500ms（本地工具） |
| 并发子代理 | 默认 3 个，可配置 |
| 内存占用 | < 500MB（空闲） |
| 前缀缓存命中率 | > 80%（同会话内） |
