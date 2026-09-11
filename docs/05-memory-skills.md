# 05. 记忆与技能系统

## 5.1 持久记忆系统

### 5.1.1 记忆类型

| 类型 | 文件 | 用途 | 写入者 |
|------|------|------|--------|
| Agent 记忆 | `MEMORY.md` | Agent 自身经验、偏好、工作流程 | Agent 通过 memory tool |
| 用户画像 | `USER.md` | 用户背景、偏好、习惯 | Agent 通过 memory tool (target=user) |
| 会话历史 | SQLite | 完整对话轨迹 | 系统自动 |

### 5.1.2 存储位置

```
~/.Zeloo/
├── memories/
│   ├── MEMORY.md      # Agent 记忆
│   └── USER.md        # 用户画像
└── state.db            # SQLite 会话数据库
```

### 5.1.3 Memory 工具

```python
@tool(name="memory", description="Read or write persistent memory")
def memory(action: str, target: str = "memory", content: str = "") -> str:
    """
    action: "read" | "write" | "append"
    target: "memory" (MEMORY.md) | "user" (USER.md)
    """
    store = MemoryStore(home=agent_home())
    if action == "read":
        return store.read(target)
    elif action == "write":
        store.write(target, content)
        return "Memory written."
    elif action == "append":
        store.append(target, content)
        return "Memory appended."
```

### 5.1.4 记忆注入

会话开始时，记忆作为**冻结快照**注入 system prompt 的 volatile 层：

```python
def format_for_system_prompt(self, kind: str) -> str:
    content = self.read(kind)
    if not content:
        return ""
    label = "MEMORY" if kind == "memory" else "USER PROFILE"
    return f"## {label}\n{content}"
```

**关键设计**：
- 注入的是**会话开始时的快照**，运行时写入不立即反映
- 下次 context compression 重建时才更新
- 避免每轮都读磁盘，同时保证记忆最终一致

### 5.1.5 记忆预算

记忆有硬字符上限（默认 8000 字符）。满了之后 Agent 应：

1. 合并或替换过时条目
2. 在同一批次中完成（先读后写）
3. 保持声明式事实风格：`"User prefers concise responses"` ✓，而非 `"Always respond concisely"` ✗

### 5.1.6 外部记忆提供方

支持可插拔记忆后端架构，9 个内置记忆提供方：

| 提供方 | 类型 | 说明 |
|--------|------|------|
| LocalFile | 本地文件 | MEMORY.md / USER.md（默认） |
| Honcho | 对话式用户建模 | 基于会话的用户画像 |
| Mem0 | 通用记忆服务 | 向量检索记忆 |
| OpenViking | 开放记忆 | 开源记忆后端 |
| Supermemory | 超级记忆 | 全平台记忆同步 |
| Byterover | 字节记忆 | 字节跳动记忆服务 |
| Hindsight | 后见之明 | 回溯式记忆 |
| Holographic | 全息记忆 | 全息关联记忆 |
| RetainDB | 持久化 DB | 数据库持久化 |

**政策**：2026 年 5 月后，新记忆提供方不得直接添加到核心仓库，须作为独立插件发布。

```yaml
memory_providers:
  honcho:
    type: honcho
    api_key: ${HONCHO_API_KEY}
    app_name: Zeloo
```

外部记忆的 system prompt 块在 volatile 层，与内置记忆并列注入。

## 5.2 技能系统（Skills）

### 5.2.1 设计理念：Progressive Disclosure

技能采用**渐进披露**模式：

1. **索引阶段**：system prompt 中只包含所有 skill 的 `name + description`
2. **加载阶段**：Agent 需要某个 skill 时，通过 `skill_view(name=...)` 加载全文
3. **更新阶段**：Agent 可通过 `skill_manage` 创建/修改技能

**优势**：
- system prompt 体积小（只有索引）
- Agent 自主决定何时加载详细内容
- 技能内容可运行时更新，不影响缓存

### 5.2.2 Skill 文件结构

每个 skill 是一个目录，包含 `SKILL.md`：

```
~/.Zeloo/skills/
├── Zeloo/
│   └── SKILL.md
├── python-testing/
│   └── SKILL.md
└── web-scraping/
    └── SKILL.md
```

`SKILL.md` 格式：

```markdown
---
name: python-testing
description: Best practices for writing and running Python tests
platforms: [cli, tui, api]
toolsets: [terminal, file]
---

# Python Testing

## Running Tests
Use `pytest` to run tests...

## Writing Tests
Follow the AAA pattern...
```

### 5.2.3 技能索引构建

```python
def build_skills_system_prompt(available_tools, available_toolsets, compact_categories=None):
    skills = []
    for skill_file in iter_skill_index_files():
        frontmatter = parse_frontmatter(skill_file)
        if not skill_matches_platform(frontmatter, current_platform):
            continue
        if not skill_matches_environment(frontmatter, available_toolsets):
            continue
        skills.append(f"- {frontmatter['name']}: {frontmatter['description']}")
    return "## Available Skills\n" + "\n".join(skills) if skills else ""
```

**过滤条件**：
- 平台匹配（`platforms` 字段）
- 工具集匹配（`toolsets` 字段，确保 skill 引用的工具可用）
- 禁用列表（用户可禁用特定 skill）

### 5.2.4 索引缓存

技能索引构建涉及大量文件 I/O，采用两级缓存：

1. **进程内 LRU 缓存**：key 包含 platform、disabled_skills、toolsets
2. **磁盘 snapshot manifest**：记录每个 skill 文件的 mtime + size，校验后复用

失效条件：
- skill 文件被增删改
- 平台/工具集变化
- 进程重启

### 5.2.5 skill_view 工具

```python
@tool(name="skill_view", description="Load a skill's full content")
def skill_view(name: str) -> str:
    skill_path = find_skill(name)
    if not skill_path:
        return f"Skill '{name}' not found."
    content = read_skill_md(skill_path)
    return content
```

Agent 加载 skill 后，内容作为 tool result 进入对话上下文，Agent 据此执行。

### 5.2.6 skill_manage 工具

```python
@tool(name="skill_manage", description="Create, update, or delete skills")
def skill_manage(action: str, name: str, content: str = "") -> str:
    """
    action: "create" | "patch" | "delete"
    """
    if action == "create":
        create_skill(name, content)
    elif action == "patch":
        patch_skill(name, content)
    elif action == "delete":
        delete_skill(name)
    # 清除索引缓存
    invalidate_skills_cache()
    return f"Skill '{name}' {action}d."
```

### 5.2.7 技能安全规则

system prompt 中注入技能安全规则：

```
## Skill Safety Rule
A skill placeholder containing `[SKILL_PRUNED]` lost its content in
context compression and is inaccessible — reload it with
skill_view(name='...') before acting on anything that depends on it.
```

当上下文压缩导致 skill 内容被裁剪时，Agent 必须重新加载才能使用。

### 5.2.8 双层技能架构

技能分为两层：

| 类型 | 路径 | 说明 |
|------|------|------|
| 内置技能 | `skills/` | 随仓库发布，默认可加载 |
| 可选技能 | `optional_skills/` | 较重/专业化技能，默认不启用，需手动启用 |

可选技能目前涵盖 7 个类别（实际 `optional_skills/` 模块）：软件开发（software_development）、DevOps、数据科学（data_science）、MLOps、研究（research）、安全（security）、技能加载器（skill_loader）。未来可扩展更多类别。

### 5.2.9 Curator 技能生命周期

Curator 系统自动管理技能的生命周期，确保技能库始终保持高质量。

**状态机**：

```
active ──(stale_after_days 未使用)──► stale ──(archive_after_days 仍未使用)──► archived
  ▲                                      │                                        │
  └────────── Agent 使用该技能重新激活 ◄──┴────────────────────────────────────────┘
```

**核心规则**：
- **永不删除**：技能只被归档，不删除（可通过 `set_state(name, ACTIVE)` 恢复）
- **使用即激活**：`track_usage(name)` 被调用时，stale/archived 技能自动恢复为 active
- **后台评估**：定期调用 `run_cycle()` 评估所有技能的活跃度

**配置**：

```yaml
curator:
  enabled: true
  stale_after_days: 30
  archive_after_days: 90
```

**状态持久化**：`~/.Zeloo/skills/.curator_state.json`

## 5.3 记忆与技能的协同

```
Agent 完成复杂任务
  │
  ▼
Turn Finalizer 评估
  │
  ├─► 可复用的工作流 → skill_manage(create) → 进入技能索引
  │
  └─► 用户偏好/事实 → memory(target=user) → 写入 USER.md
  │
  ▼
下次会话
  ├─► 技能索引出现在 volatile 层
  └─► 记忆快照出现在 volatile 层
  │
  ▼
Agent "记住"了上次的经验
```

**核心区别**：
- **技能**：可复用的工作流/知识，Agent 主动学习并固化
- **记忆**：用户偏好和事实，Agent 被动记录
