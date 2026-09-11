# 贡献指南

感谢您对 Zeloo 项目的贡献！本文档说明如何参与代码、文档、测试的贡献。

---

## 目录

1. [开发环境准备](#1-开发环境准备)
2. [代码规范](#2-代码规范)
3. [提交流程](#3-提交流程)
4. [测试指南](#4-测试指南)
5. [文档贡献](#5-文档贡献)
6. [PR 类型](#6-pr-类型)
7. [审查标准](#7-审查标准)

---

## 1. 开发环境准备

### 1.1 克隆仓库

```bash
git clone https://github.com/zeloo-project/zeloo.git
cd zeloo
```

### 1.2 安装依赖

```bash
# 使用 uv（推荐）
pip install uv
uv sync

# 安装 dev 依赖
uv sync --extra dev

# 验证安装
python -m zeloo --help
```

### 1.3 运行测试

```bash
# 全部测试
uv run pytest tests/ -v

# 仅单元测试
uv run pytest tests/unit/ -v

# 仅集成测试
uv run pytest tests/integration/ -v

# 单个测试文件
uv run pytest tests/unit/test_task_planner_integration.py -v
```

### 1.4 代码检查

```bash
# Ruff 检查
uv run ruff check .

# Ruff 格式
uv run ruff format .

# MyPy 类型检查
uv run mypy zeloo agent --ignore-missing-imports

# 全部检查
uv run ruff check . && uv run ruff format --check . && uv run mypy zeloo agent
```

---

## 2. 代码规范

### 2.1 Python 风格

遵循 **PEP 8** + **Ruff** 自动格式化：

```bash
# 自动格式化（修改文件）
uv run ruff format .

# 自动修复可修复问题
uv run ruff check . --fix
```

### 2.2 类型注解

- 所有公共函数必须有类型注解
- 使用 `from __future__ import annotations`（PEP 563）
- 优先使用泛型而非 `Any`

```python
# ✅ 推荐
def process_messages(messages: list[Message]) -> list[str]:
    ...

# ❌ 避免
def process_messages(messages):
    ...
```

### 2.3 Docstring

所有公共模块、类、函数必须有 docstring：

```python
class SessionDB:
    """SQLite-backed session storage with WAL mode and FTS5 search.

    Args:
        path: Path to the SQLite database file.
        wal_mode: Enable Write-Ahead Logging for concurrent reads.
        cache_size: SQLite page cache size in bytes.

    Example:
        >>> db = SessionDB("~/.Zeloo/sessions.db")
        >>> db.save_message("session_1", "user", "Hello!")
        >>> msgs = db.get_messages("session_1")
    """

    def __init__(
        self,
        path: str = "~/.Zeloo/sessions.db",
        wal_mode: bool = True,
        cache_size: int = 10000,
    ) -> None:
        ...
```

### 2.4 依赖版本锁定

在 `pyproject.toml` 中使用精确版本：

```toml
[project.dependencies]
openai = "==1.50.0"
httpx = "==0.27.2"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.4",
]
```

---

## 3. 提交流程

### 3.1 创建分支

```bash
git checkout -b feat/my-new-feature     # 新功能
git checkout -b fix/bug-description     # Bug 修复
git checkout -b docs/improve-api-doc   # 文档改进
git checkout -b test/add-coverage      # 测试覆盖
```

### 3.2 提交规范

遵循 [Conventional Commits](https://www.conventionalcommits.org/)：

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**类型**：

| Type | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档变更 |
| `test` | 测试相关 |
| `refactor` | 重构（无功能变化） |
| `perf` | 性能优化 |
| `ci` | CI/CD 变更 |
| `chore` | 构建/工具变更 |

**示例**：

```bash
feat(task_planner): add DAG execution with dependency resolution

- Add topological sort for task ordering
- Add cycle detection to prevent infinite loops
- Add concurrent task execution support

Closes #123
```

### 3.3 Commit Hooks

项目配置了 pre-commit hooks（使用 pre-commit 框架）：

```bash
# 安装 hooks
uv run pre-commit install

# 手动运行
uv run pre-commit run --all-files

# 跳过 hooks（不推荐）
git commit --no-verify
```

---

## 4. 测试指南

### 4.1 测试原则

- 每个 PR 必须附带测试
- 测试必须覆盖新功能或修复的 bug
- 修复 bug 时，先写一个会失败的测试来复现 bug

### 4.2 测试命名

```python
def test_<what_is_being_tested>():
    """Test description in present tense."""

def test_<what_is_being_tested>__edge_case():
    """Test description for specific edge case."""
```

### 4.3 测试结构

```python
# tests/unit/test_xxx.py

class TestComponentName:
    """Tests for ComponentName."""

    def test_basic_functionality(self):
        """Component returns expected result for valid input."""
        ...

    def test_handles_empty_input(self):
        """Component gracefully handles empty input."""
        ...

    def test_raises_on_invalid_input(self):
        """Component raises ValueError for invalid input."""
        with pytest.raises(ValueError, match="expected error"):
            component.do_something("invalid")
```

### 4.4 Mock 与 Fixture

```python
import pytest
from unittest.mock import Mock, patch

@pytest.fixture
def mock_provider():
    provider = Mock()
    provider.complete.return_value = "mocked response"
    return provider

def test_with_mocked_provider(mock_provider):
    result = agent.run(provider=mock_provider)
    assert result == "mocked response"
```

### 4.5 运行特定测试

```bash
# 按名称过滤
pytest tests/unit/ -k "task_planner"

# 按标记运行
pytest tests/ -m "not slow"

# 生成覆盖率报告
pytest tests/unit/ --cov=zeloo --cov-report=html --cov-report=term-missing
```

### 4.6 测试覆盖目标

- **核心模块**（Agent 核心）：> 90% 覆盖
- **Provider 层**：> 80% 覆盖
- **CLI 层**：> 70% 覆盖
- **文档/工具**：> 50% 覆盖

---

## 5. 文档贡献

### 5.1 文档类型

| 类型 | 位置 | 说明 |
|------|------|------|
| API 文档 | `docs/` | Markdown 格式 |
| Docstring | 代码中 | 函数/类说明 |
| 示例代码 | `examples/` | 完整可运行示例 |
| README | 项目根目录 | 安装与快速开始 |

### 5.2 文档格式

```markdown
# 标题

## 子标题

正文内容。

```python
# 代码示例
def example():
    pass
```

**注意**：代码块必须指定语言（`python`、`bash`、`yaml` 等）。
```

### 5.3 更新 API 文档

修改代码后，同步更新对应文档：

1. 更新 `docs/` 中的 Markdown 文档
2. 更新代码中的 docstring
3. 确保示例代码可运行

---

## 6. PR 类型

### 6.1 功能 PR

```
feat(<scope>): <description>

- 详细说明新功能
- 使用示例
- 相关 issue

[Breaking Change]: ...
Closes #XXX
```

### 6.2 Bug 修复 PR

```
fix(<scope>): <description>

- 问题描述
- 修复方案
- 测试验证

Fixes #XXX
```

### 6.3 重构 PR

```
refactor(<scope>): <description>

- 变更原因
- 前后对比
- 确保无行为变化

Related: #XXX
```

### 6.4 文档 PR

```
docs(<scope>): <description>

- 新增/修改内容
- 适用场景
```

---

## 7. 审查标准

### 7.1 必须通过

- [ ] `ruff check .` 无错误
- [ ] `ruff format --check .` 通过
- [ ] `mypy zeloo agent` 无新增错误
- [ ] `pytest tests/unit/` 全部通过
- [ ] 覆盖率无显著下降

### 7.2 代码审查要点

**功能正确性**
- 功能是否按需求实现？
- 边界情况是否处理？
- 是否有潜在的 bug？

**代码质量**
- 命名是否清晰？
- 是否有重复代码？
- 是否有适当的抽象？

**测试覆盖**
- 新功能是否有测试？
- 是否有回归风险？

**文档**
- 公 API 是否有 docstring？
- 示例代码是否可运行？

### 7.3 审查建议

- 使用具体的评论（"建议将 `x` 改为 `y`，因为..."）
- 区分必须修复 vs 建议改进
- 保持建设性语气

---

## 行为准则

Zeloo 项目遵循 [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/)。请确保：

- 尊重他人
- 不进行人身攻击
- 接受建设性批评
- 关注社区利益

---

## 问题与帮助

- **Bug 报告**：[GitHub Issues](https://github.com/zeloo-project/zeloo/issues/new)
- **功能请求**：[GitHub Discussions](https://github.com/zeloo-project/zeloo/discussions)
- **安全漏洞**：请私下联系维护者，不要公开披露
