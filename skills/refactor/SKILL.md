---
name: refactor
description: 应用 8 类经典重构模式改善代码结构，行为不变的前提下提升可读性、可维护性与可演化性
platforms: [cli, tui, api]
toolsets: [file, terminal, code_execution]
---

# Refactoring Patterns

在**严格保持行为不变**的前提下，应用 8 类经典重构模式改善代码结构。

## Triggers（触发条件）

- "refactor" / "restructure" / "improve design" / "clean code" / "extract"
- "重构" / "提取函数" / "改名" / "消除重复"

## 8 类核心模式

### 1. Extract Function（提取函数）

把一段可命名的逻辑提到独立函数。

**信号**：函数 > 20 行；注释在解释"做什么"而非"为什么"。

```python
# Before
def checkout(cart):
    total = 0
    for item in cart.items:
        total += item.price * item.qty
    if total > 100:
        total *= 0.9
    return total

# After
def checkout(cart):
    return apply_discount(compute_subtotal(cart))

def compute_subtotal(cart):
    return sum(item.price * item.qty for item in cart.items)

def apply_discount(total):
    return total * 0.9 if total > 100 else total
```

### 2. Inline Function（内联函数）

函数体比名字更直白时，删掉这层包装。

**信号**：函数被调用一次，名字没有抽象价值。

### 3. Extract Variable（提取变量）

把复杂表达式赋给一个有意义的名字。

```python
# Before
if (user.age >= 18 and user.country in ALLOWED) and not user.banned:
    ...

# After
is_eligible = user.age >= 18 and user.country in ALLOWED
is_active   = not user.banned
if is_eligible and is_active:
    ...
```

### 4. Rename（改名）

改标识符以提升可读性。

- 范围：声明 + 所有调用点 + 注释 + 文档
- 工具：`ruff --fix` / `pyright rename` / IDE refactor
- 不要一次改 N 个名字，分批提交

### 5. Move（移动）

把函数/类挪到更合适的位置。

- 原则：**与用它的代码放在一起**
- 同模块内：`def` 之间移动
- 跨模块：先 import，再迁移，最后清理旧 import

### 6. Replace Magic Number with Symbolic Constant

```python
# Before
if retry > 3:
    sleep(60)

# After
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 60
if retry > MAX_RETRIES:
    sleep(RETRY_BACKOFF_SECONDS)
```

### 7. Replace Conditional with Polymorphism

```python
# Before
def speed(vehicle):
    if vehicle.type == "car":
        return vehicle.power * 2
    elif vehicle.type == "bike":
        return vehicle.power * 1
    elif vehicle.type == "boat":
        return vehicle.power * 0.5

# After
class Vehicle: def speed(self): raise NotImplementedError
class Car(Vehicle):   def speed(self): return self.power * 2
class Bike(Vehicle):  def speed(self): return self.power * 1
class Boat(Vehicle):  def speed(self): return self.power * 0.5
```

### 8. Introduce Parameter Object

```python
# Before
def search(query, page, size, sort_by, sort_dir, filters):
    ...

# After
@dataclass
class SearchOptions:
    query: str
    page: int = 1
    size: int = 20
    sort: SortSpec = field(default_factory=SortSpec)
    filters: FilterSet = field(default_factory=FilterSet)

def search(opts: SearchOptions):
    ...
```

## 工作流程

### 步骤

1. **先有测试** —— 没有测试就不动手重构（最常见反模式）
2. **明确不变项** —— 列出：公开 API、返回类型、副作用、错误码、时序
3. **识别目标** —— 选**一个**改动影响最大的模式
4. **应用 + 跑测试** —— 一次只动一种模式
5. **commit** —— 一类模式一次提交，便于回滚
6. **重复** —— 下一个目标

### 安全网

- 单元测试覆盖关键分支
- 关键路径加**快照测试**（golden file）
- 性能敏感代码跑微基准（`pytest-benchmark`）
- 重构后做 `git diff --stat` 检查改动范围

## 顺序：先控制流，再命名，再去重，再类型

1. 控制流（嵌套 → 守卫子句）
2. 命名（变量、函数、类）
3. 去重（DRY）
4. 类型（收紧边界、消除 `Any`）

## 何时停止

- 测试通过 + 行为一致
- 改动量已超出本次 PR 的合理范围
- 下一步是**架构重构**（拆服务、改存储），不是本技能范围

## 反模式

| 反模式 | 修正 |
|---|---|
| 没有测试就开始重构 | 先补测试 |
| 一次提交改 N 个模式 | 拆分 commit |
| 用 `// FIXME` 代替真正的改动 | 直接改 |
| "为了重构而重构" | 聚焦具体代码味道 |
| 在重构里偷偷改行为 | 拆成两个 PR |
| 引入新依赖解决简单问题 | 优先用 stdlib |

## 决策清单

动手前自问：

- [ ] 是否有覆盖目标代码的测试？
- [ ] 是否明确本次重构要应用的模式？
- [ ] 公开 API 是否会变化？
- [ ] 是否能在一个 commit 内完成？
- [ ] 是否记录了"为什么"而不是"做了什么"？

## Examples

### 案例：把重复校验逻辑提取为守卫子句

```python
# Before
def process(order):
    if order is not None:
        if order.items:
            if order.status == "pending":
                ...  # 主体逻辑

# After
def process(order):
    if order is None or not order.items or order.status != "pending":
        return
    ...  # 主体逻辑，缩进减少
```

模式：组合 1（Extract Variable）+ 7（Polymorphism 不适用），主要是控制流扁平化。

## 验证

- 测试通过
- 类型检查通过
- `git diff --stat` 改动范围合理（< 300 行）
- 没有新增 TODO/FIXME
- 公开 API 兼容（导入路径、签名）
