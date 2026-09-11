---
name: code-translate
description: 跨编程语言翻译代码，保留语义与行为，覆盖从遗留系统到现代栈的迁移场景
platforms: [cli, tui, api]
toolsets: [file, terminal, code_execution]
---

# Code Translation

跨语言代码翻译：在保留行为和语义的前提下，把代码从一种编程语言迁移到另一种。

## Triggers（触发条件）

- "translate" / "convert code" / "port to" / "migrate from"
- "把这段 Python 翻译成 Go" / "把 JS 重写成 TS" / "Java 迁到 Kotlin"

## 工作流程

### 1. 范围与目标确认

- 明确源语言、目标语言与翻译边界（单文件 / 模块 / 全量）
- 收集上下文：依赖、调用方、运行时（VM / 解释器 / 编译型）
- 列出不可翻译或需人工决策的语义差异（如 GIL、协程模型、类型系统）

### 2. 语义抽取

- 优先解析 AST（`ast` / `tree-sitter` / `babel` 等），而不是直接做字符串替换
- 标注每个节点的语义类别：声明、表达式、控制流、副作用、I/O
- 识别跨语言不一致点：
  - 类型映射（`int` → `number`、`str` → `string`）
  - 运算符（`&&` → `and`、`||` → `or`、`!` → `not`）
  - 标准库等价（`os.path` → `pathlib`、`fmt.Println` → `print`）
  - 习惯用法（list comprehension ↔ stream/map ↔ for 循环）
  - 内存模型（引用 vs 值）、异常模型、可空性

### 3. 翻译策略

- **直译优先**：保持原结构与命名，最大化可复核性
- **避免混合**：同一函数内不要残留源语言风格
- **不要自动引入框架**：除非显式要求，否则用目标语言标准库
- **保留可观测行为**：返回值、副作用、异常类型、日志格式必须一致

### 4. 行为验证

- 在动笔之前**先写行为测试**（golden / property-based）
- 翻译完成后跑同一组用例，对比输出
- 浮点、并发、随机、时序相关逻辑需要专门用例

### 5. 后续重构

- 行为稳定后，再做一轮目标语言惯用法重构
- 抽取公共模块、统一错误处理、利用类型系统收紧边界

## 输出格式

```markdown
## Translation Report

### Scope
- Source: <lang> <version>
- Target: <lang> <version>
- Files: <count>

### Mapping Table
| Source Construct | Target Equivalent | Notes |
|---|---|---|

### Behavioral Tests
- [ ] <case 1>
- [ ] <case 2>

### Migration Notes
- <不可直译项>：<原因> / <处理方式>
- <保留的手写优化>：<位置>

### Diff Summary
- LOC: <before> → <after>
- Files: <count>
```

## 注意事项

- **不要做"翻译式命名"**：保留领域术语，不强行本地化
- **不要删除注释**：把意图注释翻译过去，而不是删掉
- **不要假设库等价**：所有第三方依赖逐个确认，不能用 `*` 通配
- **不要引入 Unicode 假设变化**：源文件编码保持一致
- 不要把翻译与功能重构混在同一次提交

## 常见陷阱

| 陷阱 | 处理 |
|---|---|
| `==` vs `===` / 隐式布尔转换 | 显式类型转换 |
| `null` / `None` / `nil` / `undefined` | 统一可选类型，避免 `NullPointerException` |
| 整数除法（Python 2 风格） | 显式 `//` 或转 float |
| 闭包变量捕获时机（for 循环） | 引入中间变量或显式工厂 |
| 异常链 / cause 字段 | 显式包装，不要丢失原始异常 |

## Examples

### 案例：Python → Go

输入（Python）：

```python
def fetch_users(ids):
    if not ids:
        return []
    out = []
    for i in ids:
        try:
            u = db.query_user(i)
            out.append(u)
        except NotFoundError:
            continue
    return out
```

输出（Go）：

```go
func FetchUsers(ids []int) ([]User, error) {
    if len(ids) == 0 {
        return nil, nil
    }
    out := make([]User, 0, len(ids))
    for _, id := range ids {
        u, err := db.QueryUser(id)
        if errors.Is(err, ErrNotFound) {
            continue
        }
        if err != nil {
            return nil, err
        }
        out = append(out, u)
    }
    return out, nil
}
```

报告要点：
- Mapping：`def` → `func`、列表 → slice、异常 → error
- Migration Notes：Python `except NotFoundError: continue` → Go 显式 `errors.Is`
- Tests：空列表 / 全部命中 / 部分 404 / 全 404 / DB 故障

## 验证

- 行为测试覆盖率 ≥ 翻译前基线
- 类型检查 / 编译通过
- 无源语言语法残留（grep 检查关键字）
- 公共 API 签名一致或显式记录变更
