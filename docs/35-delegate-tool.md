# 35. 代理委托工具（delegate_tool）

## 35.1 模块总览

`tools/delegate_tool.py` 实现子代理委托模式：主 Agent 将任务委托给专业子 Agent，独立执行后返回结果。子 Agent 采用零知识隔离，仅接收 goal + context，不共享主 Agent 状态。

## 35.2 核心概念

```
主 Agent
  └── delegate_task(goal="实现登录功能")
        └── 子 Agent（独立线程，300s 超时）
              └── 返回 JSON 结果（task_id / status / result / duration）
```

## 35.3 角色系统

| 角色 | 权限 | 使用场景 |
|------|------|----------|
| `leaf`（默认） | 无 delegate_task/clarify/memory | 专注的工作者任务 |
| `orchestrator` | 保留 delegate_task | 可生成自己的 workers，复杂任务分解 |

## 35.4 核心 API

### 35.4.1 DelegateTool 类

```python
from tools.delegate_tool import DelegateTool

tool = DelegateTool()

result = tool.execute(
    goal="实现用户登录功能，包含表单验证和错误处理",
    role="leaf",
    max_iterations=10,
    timeout_seconds=300,
    model="gpt-4o",
    system_prompt="你是一个 Python 后端开发者",
)
# result = '{"task_id": "uuid", "status": "completed", "result": "...", ...}'
```

### 35.4.2 便捷函数

```python
from tools.delegate_tool import delegate_task, clarify

# 委托任务
result = delegate_task(
    goal="写一个快速排序算法",
    role="leaf",
    timeout_seconds=30,
)

# 子 Agent 询问主 Agent（仅 orchestrator 可用）
response = clarify("是否需要考虑重复元素的情况？")
```

## 35.5 返回值格式

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "result": "def quick_sort(arr): ...",
  "iterations_used": 5,
  "token_usage": {"input": 1200, "output": 450},
  "duration_seconds": 12.34,
  "error": null
}
```

状态值：`completed` / `error` / `timeout`

## 35.6 配置参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `goal` | str | 必填 | 子 Agent 的任务描述 |
| `role` | str | `"leaf"` | `leaf` 或 `orchestrator` |
| `max_iterations` | int | 10 | 子 Agent 最大工具调用迭代次数 |
| `timeout_seconds` | int | 300 | 硬超时（秒），超时取消任务 |
| `model` | str | `""` | 子 Agent 模型覆盖（空则继承主 Agent） |
| `system_prompt` | str | `""` | 子 Agent 系统提示覆盖 |

## 35.7 隔离机制

子 Agent 的零知识隔离通过以下方式实现：

- **独立线程**：子 Agent 运行在 `ThreadPoolExecutor` 独立线程中
- **无共享状态**：不继承主 Agent 的 memory、context、credential_pool
- **显式注入**：`injected_context_files` 参数显式指定需要注入的上下文文件
- **线程池上限**：最大 3 个并发子 Agent，防止资源耗尽

## 35.8 错误处理

| 场景 | 行为 |
|------|------|
| 无效 role | 返回 `{"status": "error", "error": "Invalid role: xxx"}` |
| 子 Agent 异常 | 返回 `{"status": "error", "error": "具体错误信息"}` |
| 超时 | 返回 `{"status": "timeout", "error": "Task exceeded 300s timeout"}` |
| AIAgent 不可用 | 返回 `{"status": "error", "error": "AIAgent not available"}` |

## 35.9 配置示例

```yaml
# config.yaml
delegate:
  max_concurrent: 3
  default_timeout_seconds: 300
  default_role: "leaf"
  max_nested_depth: 2
  model_overrides:
    complex: "gpt-4o"
    simple: "gpt-4o-mini"
```

## 35.10 测试覆盖

| 测试文件 | 覆盖内容 | 用例数 |
|----------|----------|--------|
| `test_delegate_tool.py` | 角色枚举、错误处理、超时、配置、JSON 返回格式 | 10 |
