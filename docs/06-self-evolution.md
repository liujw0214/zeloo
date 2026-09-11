# 06. 自进化闭环

## 6.1 自进化概述

Zeloo 的核心差异化能力是**自进化闭环**：Agent 从任务经验中提炼可复用技能，累积用户画像，在后台复盘中自我修正。

```
┌─────────────────────────────────────────────────┐
│                  自进化闭环                       │
│                                                   │
│  任务执行 → 轨迹采集 → 后台复盘 → 技能/记忆固化    │
│      ↑                                      │    │
│      └────────────── 下次会话复用 ────────────┘    │
└─────────────────────────────────────────────────┘
```

## 6.2 触发条件

自进化**不是每轮都触发**，而是基于门控条件：

### 6.2.1 技能固化触发

满足以下任一条件时，评估是否将工作流固化为技能：

- 完成复杂任务（5+ 工具调用）
- 修复了棘手的错误
- 发现了非平凡的工作流
- 同一工作流在会话中被重复使用 2+ 次

### 6.2.2 记忆写入触发

- 发现用户明确表达的偏好
- 发现关于用户的持久性事实
- 任务完成后需要记录的经验教训

### 6.2.3 后台复盘触发

- 会话结束时
- 定时检查（每 N 轮对话）
- 用户手动触发 `/review`

## 6.3 Turn Finalizer

每轮对话结束后，`TurnFinalizer` 执行以下步骤：

```python
class TurnFinalizer:
    def finalize(self, agent, turn_result):
        # 1. 记忆写入评估
        self._evaluate_memory_writes(agent, turn_result)

        # 2. 技能固化评估
        self._evaluate_skill_curation(agent, turn_result)

        # 3. 轨迹采集
        self._record_trajectory(agent, turn_result)

        # 4. 触发后台复盘（异步）
        self._maybe_spawn_background_review(agent, turn_result)
```

### 6.3.1 记忆写入评估

**Nudge 机制**：不在当前轮强制写入，而是在下轮的 system prompt 中注入提示，让 Agent 自主决定。

```python
# agent/turn_finalizer.py
MEMORY_NUDGE_KEYWORDS = (
    "i prefer", "i like", "i always", "i never",
    "my workflow", "remember that", "please note",
    "for future reference",
)

def _should_nudge_memory(self, turn_result: TurnResult) -> bool:
    text = (turn_result.user_message or "").lower()
    return any(kw in text for kw in MEMORY_NUDGE_KEYWORDS)

def finalize(self, agent, turn_result: TurnResult) -> None:
    self._evaluate_memory_nudge(agent, turn_result)
    self._evaluate_skill_nudge(agent, turn_result)
    # ...
```

### 6.3.2 技能固化评估

```python
# 技能值得固化的启发式标准
SKILL_WORTHY_MIN_TOOL_CALLS = 5
SKILL_WORTHY_MIN_DISTINCT_TOOLS = 3

def _is_skill_worthy(turn_result: TurnResult) -> bool:
    if turn_result.tool_call_count < SKILL_WORTHY_MIN_TOOL_CALLS:
        return False
    if len(turn_result.distinct_tool_names) < SKILL_WORTHY_MIN_DISTINCT_TOOLS:
        return False
    return True
```

### 6.3.3 Nudge Prompt 构建

```python
# agent/turn_finalizer.py
def build_nudge_prompt(agent) -> str:
    """构建下轮 system prompt 的 nudge 提示块，消费后清除标志。"""
    parts = []

    if getattr(agent, "_memory_nudge", False):
        agent._memory_nudge = False
        parts.append(
            "## Memory Nudge\n"
            "The previous turn may have revealed durable user preferences. "
            "If so, call the `memory` tool with action='append' to record them."
        )

    if getattr(agent, "_skill_nudge", False):
        agent._skill_nudge = False
        parts.append(
            "## Skill Nudge\n"
            "The previous turn solved a non-trivial workflow. "
            "If it is reusable, call `skill_manage` with action='create' to save it."
        )

    return "\n\n".join(parts)
```

nudge prompt 块由 `agent/system_prompt.py` 的 `_build_volatile_layer()` 在构建 system prompt 时注入。

技能固化的判断标准：
- 工作流包含 3+ 步骤
- 涉及非显而易见的工具组合
- 可能在未来任务中复用

### 6.3.3 轨迹采集

```python
def _record_trajectory(self, agent, turn_result):
    trajectory = {
        "session_id": agent.session_id,
        "turn_id": turn_result.turn_id,
        "messages": turn_result.messages,
        "tool_calls": turn_result.tool_calls,
        "tool_results": turn_result.tool_results,
        "success": turn_result.success,
    }
    agent._session_db.save_trajectory(trajectory)
```

轨迹数据用于：
- 后台复盘的输入
- 训练数据生成（ShareGPT 格式）
- 问题排查

## 6.4 后台复盘（Background Review）

`agent/background_review.py` 实现异步轨迹分析，守护线程运行，不阻塞主循环。

### 6.4.1 设计原则

- **异步执行**：不阻塞主对话循环
- **隔离线程**：在守护线程中运行，避免影响主 Agent
- **成本可控**：使用便宜辅助模型（默认 `gpt-4o-mini`）
- **失败静默**：复盘失败不影响主流程

### 6.4.2 入口函数

```python
def run_background_review(payload: dict[str, Any]) -> None:
    """公有无参数入口，供定时任务或 TurnFinalizer 调用。"""
    trajectory = _load_trajectory(payload)
    if not trajectory:
        return
    analysis = _call_review_model(trajectory, payload)
    for candidate in analysis.get("skills", []):
        if _validate_skill(candidate):
            _save_skill_candidate(candidate, payload)
    for memory in analysis.get("memories", []):
        _write_memory(memory, payload)
```

### 6.4.3 辅助模型提示词

```python
REVIEW_SYSTEM_PROMPT = """You are a trajectory analyzer for a self-evolving AI agent.
Given a conversation turn's trajectory, extract:
1. Reusable skills (non-trivial workflows that may recur)
2. Durable user facts or preferences (memory)

Output ONLY valid JSON with this shape:
{
  "skills": [{"name": "kebab-case-name", "description": "...", "content": "## Title\\nSteps..."}],
  "memories": [{"target": "user"|"memory", "content": "..."}]
}
- Skill names must be lowercase kebab-case.
- Skill content must start with YAML frontmatter (---\\nname: ...\\ndescription: ...\\n---).
- Memories are declarative facts, not instructions.
- If nothing is worth extracting, return {"skills": [], "memories": []}.
"""
```

### 6.4.4 技能候选验证

```python
def _validate_skill(candidate: dict[str, Any]) -> bool:
    name = candidate.get("name", "").strip()
    content = candidate.get("content", "").strip()

    # 1. 名称必须非空且为 kebab-case
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", name):
        return False

    # 2. 内容不得为空
    if not content:
        return False

    # 3. 不得包含明显密钥
    if contains_secrets(content):
        return False

    # 4. frontmatter 必须有效（含 name 字段）
    if not has_valid_frontmatter(content):
        return False

    # 5. 不得与现有技能重名
    if skill_exists(name):
        return False

    return True
```

### 6.4.5 轨迹格式

输入轨迹结构：

```python
{
    "session_id": "sess_xxx",
    "turn_id": 5,
    "user_message": "帮我分析这份 CSV...",
    "tool_call_count": 7,
    "tool_calls": [
        {"function": {"name": "file_read", "arguments": '{"path": "data.csv"}'}},
        {"function": {"name": "execute_code", "arguments": '{"code": "import pandas..."}'}},
        ...
    ],
    "assistant_response": "以下是分析结果..."
}
```

### 6.4.6 配置

复盘可使用比主模型更便宜的模型，降低成本：

```yaml
background_review:
  enabled: true
  model: gpt-4o-mini  # 便宜模型
  max_turns_per_review: 5
  review_interval_minutes: 10
```

### 6.4.4 复盘内容

复盘模型分析轨迹后输出：

```json
{
  "skills": [
    {
      "name": "fix-django-migration",
      "description": "Steps to resolve Django migration conflicts",
      "content": "## Fixing Django Migration Conflicts\n1. Run `python manage.py makemigrations --merge`\n..."
    }
  ],
  "memories": [
    {
      "target": "user",
      "content": "User works with Django 4.2 and prefers pytest over unittest"
    }
  ],
  "improvements": [
    "Consider using `--skip-checks` flag for faster migration runs"
  ]
}
```

## 6.5 技能固化校验

后台复盘提取的技能候选需要经过校验：

```python
def _validate_skill(self, candidate):
    # 1. 名称不冲突
    if skill_exists(candidate.name):
        return False

    # 2. 内容不为空
    if not candidate.content.strip():
        return False

    # 3. 不包含敏感信息
    if contains_secrets(candidate.content):
        return False

    # 4. 格式正确（有 frontmatter + 正文）
    if not has_valid_frontmatter(candidate.content):
        return False

    return True
```

### 6.5.1 Curator 后台生命周期

技能固化后由 Curator（`agent/curator.py`）管理其生命周期：

```
active ──(30 天未使用)──► stale ──(90 天仍未使用)──► archived
  ▲                         │                          │
  └──── 重新使用自动激活 ◄────┴──────────────────────────┘
```

Curator 作为**独立后台进程**定期运行 `run_cycle()`，不阻塞主 Agent：
- 每次 `_evaluate_skill_curation` 固化技能后，`curator.track_usage(skill_name)` 将其设为 active
- Curator 后台定期扫描 `~/.Zeloo/skills/.curator_state.json`，按时间阈值更新状态
- **永不删除**：archived 技能仍可恢复，只是不出现在技能索引中

---

## 6.6 轨迹压缩与训练数据

### 6.6.1 轨迹压缩

长轨迹在存储前经过压缩：

```python
def compress_trajectory(trajectory):
    # 1. 保留首回合（用户意图）
    # 2. 保留尾回合（最终结果）
    # 3. 中间回合压缩为摘要
    compressed = {
        "first_turn": trajectory.turns[0],
        "last_turn": trajectory.turns[-1],
        "middle_summary": summarize(trajectory.turns[1:-1]),
    }
    return compressed
```

### 6.6.2 训练数据导出

轨迹可导出为 ShareGPT 格式，用于 SFT/DPO 训练：

```json
{
  "conversations": [
    {"from": "human", "value": "How do I fix a Django migration conflict?"},
    {"from": "gpt", "value": "Let me check the current migration state...", "tool_calls": [...]},
    {"from": "tool", "value": "..."},
    {"from": "gpt", "value": "Here's how to fix it..."}
  ]
}
```

## 6.7 自进化的成本控制

| 机制 | 成本控制策略 |
|------|-------------|
| 后台复盘 | 使用便宜模型，限频执行 |
| 技能固化 | 校验过滤，只保留高质量技能 |
| 记忆写入 | 字符预算限制，过时内容合并 |
| 轨迹采集 | 压缩存储，定期清理 |
| Nudge 提示 | 只提示不强制，Agent 自主决定 |

## 6.8 自进化与缓存的关系

自进化只影响 volatile 层（技能索引、记忆快照），stable 层始终保持缓存命中。

```
自进化写入 (skill_manage / memory)
  │
  ▼
Volatile 层内容变化
  │
  ▼
下次 context compression 时重建
  ├─► Stable 层：字节不变 → prefix cache 命中 ✓
  └─► Volatile 层：更新内容 → 重新发送
```

**结论**：Agent "成长"的成本仅在于 volatile 层的 token，stable 层的大段身份/指导内容始终复用缓存。
