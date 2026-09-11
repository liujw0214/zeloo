---
name: test-gen
description: 为函数、类、模块自动生成 pytest 测试，覆盖单元、集成、E2E 与性能场景
platforms: [cli, tui, api]
toolsets: [file, terminal, code_execution]
---

# Test Generation

按既定模板与覆盖率策略，自动产出 pytest 测试代码。先**理解被测对象**、再选**覆盖策略**、最后**生成 + 校验**。

## Triggers（触发条件）

- "generate tests" / "write tests" / "create test cases" / "test generation"
- "帮我写测试" / "补单元测试" / "生成测试用例"

## 测试分层

| 层级 | 范围 | 速度 | 数量占比 |
|---|---|---|---|
| Unit | 单函数 / 类 | ms 级 | 70% |
| Integration | 模块间协作 | s 级 | 20% |
| E2E | 完整用户路径 | 10s 级 | 5% |
| Performance | 基准 / 压测 | 分钟级 | 5% |

## 覆盖率策略

### 边界值

- 数值：0、1、-1、`min`、`max`、`min - 1`、`max + 1`
- 容器：空、单元素、多元素
- 字符串：空串、单字符、超长、含特殊字符（`\0` / Unicode / emoji）

### 等价类

- 有效类（happy path）
- 无效类（每种错误类型一个用例）

### 错误注入

- 网络：超时、连接拒绝、DNS 失败
- IO：磁盘满、权限拒绝、文件不存在
- 依赖：mock 抛异常

### Property-Based

```python
from hypothesis import given, strategies as st

@given(st.lists(st.integers(), min_size=1))
def test_sort_idempotent(xs):
    assert sorted(sorted(xs)) == sorted(xs)
```

适合：纯函数、集合操作、序列化往返。

## pytest 模板

```python
import pytest

def test_<func>_<scenario>_<expected>():
    # Arrange
    input_data = ...
    # Act
    result = func(input_data)
    # Assert
    assert result == expected
```

命名规范：`test_<单元>_<场景>_<期望>`。

### 参数化

```python
@pytest.mark.parametrize("input,expected", [
    (0,    "zero"),
    (1,    "one"),
    (-1,   "negative"),
    (None, ValueError),
])
def test_classify(input, expected):
    if expected is ValueError:
        with pytest.raises(ValueError):
            classify(input)
    else:
        assert classify(input) == expected
```

### Fixture

```python
@pytest.fixture
def user():
    return User(id=uuid4(), email="a@b.c")

def test_activate(user):
    user.activate()
    assert user.is_active
```

### Mock

```python
def test_send_email(mocker):
    mock_smtp = mocker.patch("module.smtplib.SMTP")
    send_email("to@x.com", "hi")
    mock_smtp.return_value.sendmail.assert_called_once()
```

## 生成流程

### 1. 阅读被测对象

- 函数签名、返回类型、异常
- 读 docstring 与类型注解
- 看调用方理解典型用法

### 2. 列出用例清单

按"输入空间 × 期望输出"列出矩阵，避免遗漏。

### 3. 生成测试

- happy path 1 个
- 每个分支 1 个
- 每个异常 1 个
- 边界值集中参数化

### 4. 运行 + 修测试

- 先确认**测试失败**（红）
- 实现 / 修复代码
- 测试通过（绿）
- 重构（重构）

### 5. 覆盖率检查

```bash
pytest --cov=src --cov-report=term-missing
```

- 目标：行覆盖 ≥ 85%，分支 ≥ 80%
- 关键模块 ≥ 95%

## 输出格式

文件组织：

```
tests/
├── unit/
│   ├── test_<module>.py
│   └── ...
├── integration/
│   └── test_<feature>.py
└── conftest.py
```

每个测试文件包含：

```python
"""Tests for <module>: <one-line description>"""
import pytest
from <module> import <thing>

class Test<Func>:
    def test_<happy_path>(self): ...
    def test_<error_path>(self): ...
```

## 反模式

| 反模式 | 修正 |
|---|---|
| 测试实现细节 | 测行为不测内部 |
| 一个测试里 10 个断言 | 拆开，断言失败时定位更准 |
| 共享可变状态 | 用 fixture 隔离 |
| sleep 等待异步 | mock 或显式 await |
| 用真实数据库 | 用 sqlite-memory / testcontainers |
| 复制粘贴 fixture | conftest.py 共享 |
| 跳过测试代替修复 | `@pytest.mark.xfail` 必须有原因 |

## Examples

### 案例：为折扣函数生成测试

```python
def discount(total: Decimal, vip: bool) -> Decimal:
    if total <= 0:
        raise ValueError("total must be positive")
    if vip:
        return total * Decimal("0.8")
    if total >= 100:
        return total * Decimal("0.9")
    return total

# 自动生成的测试
class TestDiscount:
    def test_vip_gets_20_percent(self):
        assert discount(Decimal("100"), vip=True) == Decimal("80.00")

    def test_non_vip_over_100_gets_10_percent(self):
        assert discount(Decimal("100"), vip=False) == Decimal("90.00")

    def test_non_vip_under_100_no_discount(self):
        assert discount(Decimal("50"), vip=False) == Decimal("50")

    @pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-1")])
    def test_non_positive_raises(self, bad):
        with pytest.raises(ValueError):
            discount(bad, vip=False)

    def test_boundary_exactly_100(self):
        assert discount(Decimal("100.00"), vip=False) == Decimal("90.00")
```

要点：覆盖 happy / error / 边界 / 参数化。

## 验证

- `pytest -q` 全绿
- 覆盖率达标
- 无 skip / xfail 滥用
- 测试运行时间：单测 < 5s，全部 < 5min
- flaky 测试有标记 + 已知原因
