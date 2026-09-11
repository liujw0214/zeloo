# 02. System Prompt 三层架构

## 2.1 设计动机

System Prompt 是 Agent 行为的基准。传统做法每次对话都重新装配完整 prompt，导致：

1. **Token 浪费**：固定内容（身份、指令）每轮重复发送
2. **延迟增加**：LLM Provider 无法复用 prefix cache
3. **成本偏高**：长 system prompt 每轮都全额计费
Zeloo 将 System Prompt 按*变化频率*划分为三层，最大化 LLM Provider 的 prefix cache 命中率。

## 2.2 三层定义

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
┃ Stable 层（会话级别不变化）                                               ┃
┃  ┣ SOUL.md / 身份 / 工具指导 / 环境提示 / 编码简则                       ┃
┃  ┗ Model Gating（拒绝不适配的模型）                                       ┃
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
┃ Context 层（项目级别，随 cwd 切换）                                       ┃
┃  ┣ 工作区快照 / 调用方 system_message / 上下文文件                       ┃
┃  ┗ Platform Hint（CLI/TUI/Telegram 等差异化提示）                       ┃
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
┃ Volatile 层（每轮都可能变化）                                            ┃
┃  ┣ 技能索引 / 记忆快照 / USER.md / 时间戳                                ┃
┃  ┗ 插件段落（Plugins 注入）                                             ┃
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

三层以`\n\n`拼接，顺序固定为 `stable\n\ncontext\n\nvolatile`。

> **为什么是这个顺序？** LLM 的 prefix cache 是最长前缀匹配。把最稳定的内容放最前面，即使后面两层变化，prefix cache 仍能命中前面。

**设计意图**：最大化 LLM Provider 的 prefix cache 命中率，稳定层只构建一次并缓存，节省约 **70% 的 API 成本**。缓存统计输出示例：`Prompt cache hit ratio: 80.0% (800/1000 cached tokens)`。

### 2.2.1 Volatile 层完整构建流程

`build_system_prompt_parts()` 中的 volatile 层按以下顺序装配：

1. **技能索引**（Skills Index）
2. **记忆快照**（Memory Snapshot）
3. **外部记忆**（Third-party Memory）
4. **插件段落**（Plugin Paragraphs）
5. **时间戳行**（Timestamp Line）

## 2.3 Stable 层 — 身份与约束

### 2.3.1 组成

| 组件 | 内容 | 变化条件 |
|------|------|----------|
| SOUL.md | Agent 身份、行为准则 | 极少变化 |
| 编码简则 | 代码风格、注释要求 | 几乎不变 |
| 工具指导 | 工具调用规范、错误处理 | 极少变化 |
| 环境提示 | 运行时环境信息 | 环境变化时 |
| Model Gating | 拒绝不适配的模型 | 从不变化 |

### 2.3.2 SOUL.md

```python
def _load_soul(agent) -> str:
    path = Path(__file__).parent / "SOUL.md"
    return path.read_text()
```

### 2.3.3 Model Gating

```python
SUPPORTED_MODELS = {"gpt-4o", "gpt-4-turbo", "claude-3-5-sonnet", "claude-3-opus"}

def _model_gate(model: str) -> str:
    if model.lower() not in SUPPORTED_MODELS:
        return (
            "STOP: This session requires a model with ≥128K context window. "
            f"Current model '{model}' is not supported."
        )
    return ""
```

### 2.3.4 编码简则

```python
GUIDANCE_LINES = [
    "You are a coding agent. Write complete, production-ready code.",
    "Always prefer stdlib over external dependencies (YAGNI).",
    "Type annotations are mandatory for all public functions.",
    "Docstrings are required for all public functions.",
    "No placeholder comments like '# TODO' or '# FIXME' in final output.",
]
```

## 2.4 Context 层 — 项目与环境

### 2.4.1 组成

| 组件 | 内容 | 变化条件 |
|------|------|----------|
| 工作区快照 | git 状态、文件树、活跃文件 | 项目文件变化 |
| 环境探测 | 一行环境摘要 | 环境变化（远程后端跳过） |
| Bot Mode 协议 | 仅 Bot Chat 会话 | 会话类型 |
| Profile 行 | 当前 profile 名称及路径 | 切换 profile |
| 平台提示 | CLI/TUI/Telegram 等差异化提示 | 切换平台 |
| 调用方消息 | 外部传入的 system_message | 每轮可不同 |
| 上下文文件 | AGENTS.md / .cursorrules / .Zeloo.md | 切换项目目录 |

### 2.4.2 上下文文件发现

**发现优先级**（从高到低）：

1. `.Zeloo.md` / `Zeloo.md`
2. `AGENTS.md`
3. `CLAUDE.md`
4. `.cursorrules`

**搜索范围**：从 cwd 向上遍历到 git root（无 git 时只查 cwd 本身，避免拾取 `/tmp` 等无关文件）。

### 2.4.3 安全扫描

所有上下文文件在注入前必须经过威胁扫描：

```python
def _scan_context_content(content, filename):
    content = content.lstrip("\ufeff")  # 去除 UTF-8 BOM
    findings = scan_for_threats(content, scope="context")
    if findings:
        return f"[BLOCKED: {filename} contained potential prompt injection]"
    return content
```

- 扫描范围：经典注入 + promptware/C2 模式 + role-play 劫持
- 命中后原文**永不进入** system prompt，替换为占位符
- 用户无机会干预（因为文件会原样进入 system prompt）

### 2.4.4 调用方消息不缓存

```python
# ephemeral_system_prompt is injected at API-call time only, never cached.
if system_message is not None:
    context_parts.append(system_message)
```

调用方传入的 `system_message` 虽然在 context 层，但**不参与缓存**，每轮对话可传入不同值而不破坏前缀缓存。

## 2.5 Volatile 层 — 运行时可变

### 2.5.1 组成

| 组件 | 内容 | 变化条件 |
|------|------|----------|
| 技能索引 | 所有 skill 的 name + description | 技能增删 |
| 记忆快照 | MEMORY.md + USER.md 内容 | 记忆写入 |
| 外部记忆 | 第三方记忆提供方内容 | 外部更新 |
| 插件段落 | 插件注入的 system prompt 块 | 插件渲染 |
| 时间戳行 | 对话开始时间 + Session/Model/Provider/Platform | 跨天重建 |

### 2.5.2 技能索引：Progressive Disclosure

只注入**索引**（name + description），不注入 skill 全文。Agent 需要时通过 `skill_view(name=...)` 按需加载。

> 技能索引放在 volatile 层的**最前面**，这样如果索引没变，longest-prefix cache 仍能命中到此处。

### 2.5.3 记忆快照：冻结注入

会话开始时从磁盘读取 `MEMORY.md` 和 `USER.md` 作为**冻结快照**注入。运行时通过 memory tool 写入的内容不会立即反映，直到下次 context compression 重建。

### 2.5.4 时间戳：字节稳定性

```python
def _timestamp_line(agent):
    now = zeloo_now()
    start = session_start_like(agent, now)  # 从 session_id 解析
    line = f"Conversation started: {start.strftime('%A, %B %d, %Y')}"
    # 跨天才加 "as of" 行
    if now.strftime("%Y%m%d") != start.strftime("%Y%m%d"):
        line += f"\nToday's date (as of last rebuild): {now.strftime('%A, %B %d, %Y')}"
    line += f"\nModel: {agent.model}\nProvider: {agent.provider}\nPlatform: {agent.platform}"
    return line
```

**字节稳定性设计**：
1. 只显示*日期*，不显示时间 — 当天字节稳定
2. 开始时间从 `session_id`（格式`YYYYMMDD_HHMMSS_...`）解析 — 重启后不位移
3. 单日会话保持单行 — 字节完全一致
4. 跨天才加第二行 — 此时 cache 本来就失效，无额外成本

### 2.5.5 插件段落：冻结与恢复

插件段落构建后冻结存储。恢复时会从已冻结的 prompt 中*提取字节*，不重新调用插件代码：
- 插件渲染失败 — fallback 到上次成功的字节（fail-open）
- 恢复时不再跑插件 — 避免插件状态不一致

## 2.6 缓存生命周期

```
会话开始  ─►  build_system_prompt()
  ├── agent._cached_system_prompt = 完整字符串
  └── agent._cached_system_prompt_static = stable 层

  每轮对话：直接复用 _cached_system_prompt

  Context Compression 触发
  ├── invalidate_system_prompt()
  ├── _cached_system_prompt = None
  ├── 从磁盘重载 memory
  ├── 清除插件冻结快照（保留上次作 fallback）
  └── 下一轮：重新 build_system_prompt()
```

### 2.6.1 强制重建触发条件

仅以下情况触发 `invalidate_system_prompt`：
- Context compression（上下文压缩）
- 切换模型 / Provider
- 切换平台
- 手动调用 `/refresh` 命令

### 2.6.2 恢复场景重建

从持久化状态恢复时，只恢复完整 prompt 字符串。`reconstruct_static_prefix` 重新构建 stable 层并验证是否仍是存储 prompt 的前缀：
```python
static = build_system_prompt_parts(agent)["stable"]
if stored.startswith(static):
    agent._cached_system_prompt_static = static
```

匹配成功 — 后续 API 调用可使用分段格式，借 provider 的 prefix cache 命中 stable 层。匹配失败 — 退回归发完整 prompt。

## 2.7 三层与自进化的关系

| 层 | 自进化影响 | 缓存影响 |
|----|-----------|----------|
| Stable | 不受影响 | 永久命中 |
| Context | 不受影响 | 项目切换时失效 |
| Volatile | 技能、记忆变化仅影响此层 | 仅此层重建，stable 层仍命中 |

**核心论点**：自进化发生在 volatile 层，缓存稳定在 stable 层，二者解耦。Agent "成长"不增加 token 成本。
