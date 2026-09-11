# 45. optional_skills 完整 API 参考

> 本文档详细描述 `optional_skills/` 包的所有公共 API 与函数签名，供开发者与 Agent 工具调用使用。

---

## 45.1 包概览

`optional_skills/` 提供 6 个领域技能模块 + 1 个技能加载器：

```
optional_skills/
├── __init__.py                # 包导出
├── skill_loader.py            # 技能发现与加载
├── software_development.py    # 软件开发技能
├── devops.py                  # DevOps 技能
├── data_science.py            # 数据科学技能
├── mlops.py                   # MLOps 技能
├── research.py                # 研究辅助技能
└── security.py                # 安全技能
```

---

## 45.2 skill_loader API

### 45.2.1 `SkillInfo` dataclass

```python
@dataclass
class SkillInfo:
    name: str
    category: str
    description: str
    triggers: list[str]
    version: str
    path: Path
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 技能名称（来自 SKILL.md frontmatter） |
| `category` | `str` | 分类（来自父目录名） |
| `description` | `str` | 描述（来自 frontmatter） |
| `triggers` | `list[str]` | 触发词列表（来自 `## Triggers` 章节） |
| `version` | `str` | 版本号（来自 frontmatter，默认 1.0.0） |
| `path` | `Path` | SKILL.md 所在目录的路径 |

### 45.2.2 `load_skill_index(skill_dir: Path) -> list[SkillInfo]`

扫描 `skill_dir` 下的所有 `SKILL.md` 文件并解析元数据。

```python
from pathlib import Path
from optional_skills.skill_loader import load_skill_index

skills = load_skill_index(Path("~/.Zeloo/skills"))
# Returns: list of SkillInfo sorted by category/name
```

**特性**：
- 自动跳过非 SKILL.md 文件
- 自动跳过非目录项
- 自动跳过 frontmatter 缺失的文件（不返回）
- 按字典序排序（先 category 后 name）

### 45.2.3 `find_skill_by_name(name: str, skill_dir: Path) -> SkillInfo | None`

按精确名称查找技能。

```python
info = find_skill_by_name("docker_build", Path("~/.Zeloo/skills"))
if info:
    print(f"Found: {info.path}")
```

### 45.2.4 `_parse_skill_md(path, category, fallback_name) -> SkillInfo | None`

解析单个 SKILL.md 文件。Frontmatter 用 `---` 分隔，triggers 从 `## Triggers` 章节提取。

**SKILL.md 格式示例**：

```markdown
---
name: my_skill
description: A useful skill
version: 1.2.0
---

# My Skill

Description body here.

## Triggers

- "trigger one"
- "trigger two"
- trigger three
```

---

## 45.3 software_development 技能

| 函数 | 用途 |
|------|------|
| `code_review()` | 代码审查（风格、bug、最佳实践） |
| `refactor()` | 重构建议（提取函数、简化逻辑） |
| `generate_tests()` | 自动生成单元测试 |

---

## 45.4 devops 技能

| 函数 | 用途 |
|------|------|
| `cicd_analysis()` | CI/CD 配置审查 |
| `docker_diagnostics()` | Docker 配置诊断 |
| `k8s_health()` | Kubernetes 健康检查 |

---

## 45.5 data_science 技能

| 函数 | 用途 |
|------|------|
| `eda()` | 探索性数据分析 |
| `feature_analysis()` | 特征工程分析 |
| `data_quality_report()` | 数据质量报告生成 |

---

## 45.6 mlops 技能

机器学习模型部署、监控、A/B 测试相关工具。

---

## 45.7 research 技能

学术研究辅助（论文检索、引用格式化、文献综述）。

---

## 45.8 security 技能

| 函数 | 用途 |
|------|------|
| `dependency_audit()` | 依赖安全审计 |
| `secret_detection()` | 密钥泄漏检测 |
| `threat_analysis()` | 威胁建模分析 |

---

## 45.9 工具集成

所有技能函数通过 `tools/optional_skill_tools.py` 的 18 个 `@tool` 装饰器包装后暴露给 Agent：

```python
from tools.optional_skill_tools import code_review_tool, dependency_audit_tool

# Agent 调用示例
result = code_review_tool(
    code_path="/path/to/file.py",
    focus="security",
)
```

工具集合注册在 `toolsets.py` 的 6 个 `optional_skill:*` 命名空间：
- `optional_skill:devops`
- `optional_skill:data_science`
- `optional_skill:mlops`
- `optional_skill:research`
- `optional_skill:security`
- `optional_skill:software_development`

---

## 45.10 测试覆盖

`tests/unit/test_optional_skills.py` 提供 19 个测试，覆盖：
- SkillInfo dataclass 行为
- load_skill_index 边界条件（空目录、不存在、多分类、跳过非 MD）
- _parse_skill_md frontmatter 与 triggers 解析
- find_skill_by_name 存在与不存在场景
- 所有 6 个技能模块的可导入性
- 包导出完整性

---

## 45.11 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-09-09 | 初始 6 模块版本 |
| 1.0.1 | 2026-09-09 | skill_loader triggers 解析修复（空行不再重置 section） |