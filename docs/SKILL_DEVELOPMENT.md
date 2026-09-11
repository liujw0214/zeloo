# Skill Development Guide

本指南专门讲解 Zeloo 框架的**内置技能**（`skills/<name>/SKILL.md`）开发与维护流程，重点在 frontmatter 规范、目录结构、加载机制、测试与最佳实践。

> 与插件（plugins/）的区别：技能是声明式的工作流，由 LLM 解读执行；插件是带代码逻辑的可调用模块。

## 目录

1. [SKILL.md Schema](#skillmd-schema)
2. [目录结构](#目录结构)
3. [技能加载机制](#技能加载机制)
4. [与 Agent 的集成](#与-agent-的集成)
5. [测试技能](#测试技能)
6. [最佳实践](#最佳实践)
7. [完整示例](#完整示例)

---

## SKILL.md Schema

每个技能由一个 `SKILL.md` 文件定义，frontmatter 用 YAML 描述元数据，正文是 Markdown 工作流。

```yaml
---
name: skill-name             # 必需，kebab-case，全局唯一
description: 一句话描述         # 必需，≤ 200 chars
class: discipline             # 可选：discipline / workflow / integration
triggers:                     # 可选，触发词列表
  - "phrase 1"
  - "phrase 2"
platforms: [cli, tui, api]    # 可选，默认全平台
toolsets: [file, terminal]    # 可选，所需工具集
author: Zeloo                 # 可选
tags: [review, code-quality]  # 可选
version: 1.0.0                # 可选，遵循 SemVer
---
```

### 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | ✓ | kebab-case，作为唯一 ID 被注册表使用 |
| `description` | ✓ | 一句话说明技能用途，会被注入 system prompt |
| `triggers` |   | 触发短语，Agent 匹配用户输入时优先激活 |
| `class` |   | `discipline`（默认）/`workflow`/`integration` |
| `platforms` |   | 限定加载平台，默认全部 |
| `toolsets` |   | 依赖的工具集，用于权限隔离 |
| `version` |   | 改 description/正文必须 bump |

### 正文最小结构

```markdown
# <Skill Title>

## Triggers（触发条件）
- "phrase"

## 工作流程
1. 步骤一
2. 步骤二

## Examples（示例）
...

## 注意事项
- ...
```

---

## 目录结构

```
skills/
└── my-skill/
    ├── SKILL.md             # 必需，主入口
    ├── scripts/             # 可选，辅助 Python 脚本
    │   └── helper.py
    ├── references/          # 可选，参考资料
    │   └── spec.md
    └── examples/            # 可选，使用示例
        └── example.md
```

### 命名约定

- 技能目录：**kebab-case**（`code-review`、`test-gen`）
- SKILL.md 名称：固定大写
- 脚本：snake_case
- 引用文件：kebab-case `.md`

### 单文件 vs 多文件

- **单文件**：技能体量小，正文 < 100 行
- **多文件**：正文较长，把参考、示例、脚本分目录

---

## 技能加载机制

启动时由 `agent/skill_utils.py` 扫描 `skills/` 下所有 `SKILL.md`：

```python
# agent/skill_utils.py（伪代码）
def load_skills(root: Path) -> dict[str, Skill]:
    skills = {}
    for path in root.rglob("SKILL.md"):
        meta, body = parse_frontmatter(path.read_text())
        skills[meta["name"]] = Skill(meta=meta, body=body, path=path)
    return skills
```

加载流程：

1. 扫描 → 解析 frontmatter → 校验必填字段
2. 校验 `name` 唯一性
3. 注册到 `SkillRegistry`
4. 按 `platforms` / `toolsets` 过滤
5. 注入 system prompt 的 context 层

### 热重载

- 开发模式下，监听 `skills/` 目录变更
- 改 SKILL.md 无需重启 Agent
- 改目录结构（新增/删除 skill）需要重启

---

## 与 Agent 的集成

### 触发匹配

Agent 根据用户输入匹配 `triggers`：

```python
# agent/skill_hot_reload.py
def match_skill(user_input: str, skills: list[Skill]) -> Skill | None:
    for s in skills:
        if any(t in user_input for t in s.meta.get("triggers", [])):
            return s
    return None
```

### 注入 System Prompt

匹配到的技能正文追加到 context 层：

```
<system>
[...stable 层...]
[...context 层...]
# Active Skill: code-review
## 工作流程
...
[/context]
</system>
```

### 调用工具

技能正文中可以使用工具引用（如 `secret_scanner.scan_path`），但**必须声明 toolsets**：

```yaml
toolsets: [file, terminal, code_execution]
```

否则 Agent 不会授予这些工具的调用权限。

---

## 测试技能

### 校验层

1. **Schema 校验**：frontmatter 字段齐全、类型正确
2. **唯一性校验**：`name` 不重复
3. **描述长度**：`description` ≤ 200 chars
4. **触发词**：至少 2 个（推荐）

### 行为层

技能是 LLM 解读的"软逻辑"，无法做严格单测，但可以做：

1. **快照测试** —— 把"输入 → 期望产出结构"存为 fixture
2. **Evals** —— 用 `evals/<skill>/` 跑评分
3. **黄金输出** —— 给定 prompt，比对 LLM 输出格式

```python
# tests/unit/test_skills.py
import pytest
from agent.skill_utils import load_skills

def test_skill_metadata():
    skills = load_skills("skills/")
    assert "code-review" in skills
    meta = skills["code-review"].meta
    assert meta["name"] == "code-review"
    assert len(meta["description"]) <= 200

def test_skill_unique_names():
    skills = load_skills("skills/")
    names = [s.meta["name"] for s in skills.values()]
    assert len(names) == len(set(names))
```

### LLM-as-Judge

```python
# evals/code-review/run.py
SCENARIOS = [
    {"input": "审查 src/api/users.py 的权限逻辑",
     "expect": ["包含正确性问题", "包含安全建议", "P0/P1/P2 分级"]},
]
```

---

## 最佳实践

### 内容设计

| 实践 | 说明 |
|---|---|
| **单一职责** | 一个技能只解决一类问题，不要堆砌 |
| **可执行** | 工作流步骤要具体，避免"思考一下"这种空话 |
| **可度量** | 给出验收标准（如覆盖率、p99 阈值） |
| **可纠错** | 列出常见陷阱与反模式 |
| **例子真实** | Examples 用真实代码片段，不要 `foo`/`bar` |
| **避免循环** | 不要在技能里调用另一个技能（除非显式编排） |

### Frontmatter 规范

- `name` ≤ 32 字符，kebab-case
- `description` 必须以动词开头（"扫描…"、"生成…"、"审查…"）
- `triggers` 至少 2 个短语，覆盖中英文常见说法
- `version` 在破坏性变更时升 major

### 安全合规

- **不要写密钥**到 SKILL.md
- **不要指向内部路径**
- **不要在示例中暴露真实数据**
- 涉及执行命令时显式标注"需用户确认"

### 性能

- 单个 SKILL.md **不超过 600 行**，过长则拆目录
- 触发词不要太多（5 个以内），避免误匹配
- 注入 system prompt 的内容越短越省 token

---

## 完整示例

### 技能：API 文档生成器

`skills/api-doc-gen/SKILL.md`：

```markdown
---
name: api-doc-gen
description: 从 OpenAPI 规范自动生成 Markdown API 文档，支持分组与示例
class: workflow
triggers:
  - "生成 API 文档"
  - "gen api doc"
  - "openapi to markdown"
toolsets: [file]
version: 1.0.0
---

# API 文档生成

## 工作流程

1. 定位 OpenAPI 文件（默认 `openapi.yaml`）
2. 校验 schema（`openapi-spec-validator`）
3. 解析 paths 与 components
4. 按 tag 分组生成 Markdown
5. 嵌入请求/响应示例
6. 写入 `docs/api/`

## 命令

```bash
python scripts/gen.py --spec openapi.yaml --out docs/api/
```

## 输出结构

```
docs/api/
├── index.md
├── users.md
└── orders.md
```

## Examples

输入：`openapi.yaml` 含 `paths: /users, /orders`

输出：`docs/api/users.md` 含端点表格、参数说明、示例。
```

### 校验

```bash
python -c "from agent.skill_utils import load_skills; s = load_skills('skills/'); print(s['api-doc-gen'].meta)"
```

### 发布 checklist

- [ ] frontmatter 完整
- [ ] `description` ≤ 200 字符
- [ ] `triggers` 至少 2 个
- [ ] 工作流步骤清晰可执行
- [ ] Examples 用真实代码
- [ ] 加入 tests 校验
- [ ] 更新 README 技能列表
- [ ] bump `version`

---

## 常见问题

**Q: 技能和插件有什么区别？**

A: 技能是声明式工作流（LLM 解读），插件是带代码的可调用模块（确定性执行）。技能适合"思考 + 决策"，插件适合"动作 + 副作用"。

**Q: 能否在技能里 import Python？**

A: 不能直接 import。可以放在 `scripts/` 目录，让技能正文调用命令。

**Q: 改技能后没生效？**

A: 检查是否开了热重载；否则重启 Agent。

**Q: 多个技能匹配同一句话怎么办？**

A: 优先级：更具体的 `name` > 更具体的 `triggers` > 加载顺序。

**Q: 技能能否跨平台？**

A: 通过 `platforms` 字段限定；不填默认全部。
