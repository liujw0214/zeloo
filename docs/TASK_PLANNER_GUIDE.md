# Task Planner Guide

Zeloo 的 Task Planner 把高层 Goal 拆解为可执行的 Plan，再驱动 Agent 按依赖顺序执行。本指南讲架构、组件、LLM 协同与测试。

## 架构

```
Goal (用户输入)
    │
    ▼
┌─────────────┐    plan(goal)
│ TaskPlanner │ ─────────────► Plan
└─────────────┘                   │
                                  ▼
                            ┌─────────────┐
                            │  PlanTask[] │
                            └─────────────┘
                                  │
                                  ▼ execute
                            ┌─────────────┐
                            │ PlanResult  │
                            └─────────────┘
```

层级：

- **Goal** —— 用户原始诉求，自然语言
- **SubGoal** —— Planner 拆出的中间目标
- **Task** —— 单个可执行原子任务
- **Plan** —— DAG 形式的任务集合 + 依赖关系

---

## 核心组件

入口：`agent.task_planner.TaskPlanner`

```python
from agent.task_planner import TaskPlanner

planner = TaskPlanner(llm=my_llm, tools=my_tools)

plan = planner.plan("修复登录页面的样式错乱问题")
result = planner.execute(plan)
```

### TaskPlanner

| 方法 | 签名 | 说明 |
|---|---|---|
| `plan` | `(goal: str, ctx: PlanContext) -> Plan` | 拆解 Goal 为 Plan |
| `execute` | `(plan: Plan) -> PlanResult` | 按依赖顺序执行 |
| `resume` | `(plan_id: str) -> PlanResult` | 从失败/中断处继续 |
| `cancel` | `(plan_id: str) -> None` | 取消正在执行的 Plan |

### PlanTask

```python
@dataclass
class PlanTask:
    id: str
    description: str
    dependencies: list[str]            # 其他 task id
    status: TaskStatus                 # pending/running/completed/failed/skipped
    tool_hint: str | None = None       # 推荐工具
    result: TaskResult | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    retries: int = 0
```

**状态机**：

```
pending ──► running ──► completed
   │           │
   │           └──► failed ──► (retry) ──► running
   │                                   │
   └────────► skipped ◄────────────────┘
```

### Plan

```python
@dataclass
class Plan:
    id: str
    goal: str
    tasks: list[PlanTask]
    dependencies: dict[str, list[str]]   # task_id -> [prerequisite_ids]
    status: PlanStatus                   # draft/ready/running/partial/done/failed
    created_at: datetime
    metadata: dict[str, Any]
```

### PlanContext

```python
@dataclass
class PlanContext:
    workspace: str
    memory: MemoryStore
    skills: SkillRegistry
    tools: ToolRegistry
    constraints: dict[str, Any]
```

---

## LLM Integration

TaskPlanner 与 LLM 的协同有三种模式。

### 1. 单次规划 + 执行

LLM 一次性输出完整任务列表。

```python
plan_json = llm.complete(
    system="你是任务规划助手...",
    user=f"目标：{goal}\n输出 JSON 格式的 Plan",
    response_format={"type": "json_object"},
)
plan = Plan.from_json(plan_json)
```

### 2. 增量规划（Re-plan）

每完成一个 task 后，让 LLM 决定下一步。

```python
for task in ready_tasks(plan):
    result = execute(task)
    plan = planner.replan(plan, last_result=result)
```

适合：长链路、信息逐步揭示的场景。

### 3. 工具增强规划

LLM 在规划时可以调用工具查信息。

```python
planner = TaskPlanner(
    llm=llm,
    tools=[search_code, read_file, list_dir],
    plan_strategy="tool_augmented",
)
```

---

## 依赖与执行

### 拓扑排序

`Plan` 内任务用 DAG 组织，planner 按拓扑序执行：

```
A ──► B ──► D
│           ▲
└──► C ─────┘
```

执行顺序：A → B → C → D 或 A → C → B → D。

### 并行

无依赖的任务并行执行：

```python
async def execute_parallel(tasks: list[PlanTask]) -> list[TaskResult]:
    return await asyncio.gather(*[run(t) for t in tasks])
```

### 失败处理

| 策略 | 行为 |
|---|---|
| `fail-fast` | 任一 task 失败立即终止整个 plan |
| `continue` | 标记 failed，继续执行下游可选任务 |
| `retry` | 自动重试 N 次，仍失败再 fail-fast |

---

## 测试

### 单元测试

```python
# tests/unit/test_task_planner.py
import pytest
from agent.task_planner import TaskPlanner, Plan, PlanTask

def test_plan_from_json():
    raw = {
        "tasks": [
            {"id": "a", "description": "...", "dependencies": []},
            {"id": "b", "description": "...", "dependencies": ["a"]},
        ]
    }
    plan = Plan.from_json(raw)
    assert len(plan.tasks) == 2
    assert plan.dependencies == {"b": ["a"]}

def test_topological_order():
    plan = Plan(tasks=[
        PlanTask(id="a", description="", dependencies=[]),
        PlanTask(id="b", description="", dependencies=["a"]),
        PlanTask(id="c", description="", dependencies=["a", "b"]),
    ])
    order = plan.topological_order()
    assert order.index("a") < order.index("b") < order.index("c")
```

### 集成测试

```python
def test_execute_simple_plan(monkeypatch):
    fake_llm = FakeLLM(responses=[...])
    fake_tools = FakeTools(...)
    planner = TaskPlanner(llm=fake_llm, tools=fake_tools)

    plan = planner.plan("运行单元测试")
    result = planner.execute(plan)

    assert result.status == "done"
    assert all(t.status == "completed" for t in result.tasks)
```

### 黄金输出

```python
SCENARIOS = [
    {
        "goal": "为新功能写测试",
        "expected_tasks": [
            "读取功能代码",
            "生成测试用例",
            "运行 pytest",
            "修复失败用例",
        ],
        "expected_order_starts_with": "读取功能代码",
    },
]
```

### 端到端

```python
def test_real_plan_with_real_llm(real_llm):
    planner = TaskPlanner(llm=real_llm)
    plan = planner.plan("把 main.py 的 print 改成 logger")
    result = planner.execute(plan)
    assert result.status == "done"
    assert any("logging" in t.result.output for t in result.tasks)
```

---

## 最佳实践

| 实践 | 说明 |
|---|---|
| **任务粒度适中** | 单 task 5-30s 内能完成 |
| **显式依赖** | 不要假设隐式顺序 |
| **可恢复** | 中断后能从最近 checkpoint 续跑 |
| **可观察** | 每个 task 有日志、trace_id |
| **预算控制** | plan 总成本（token / 工具调用次数）有上限 |
| **取消语义** | 长 plan 必须可中途取消 |
| **避免无限重试** | retry 次数 + backoff |

---

## 反模式

| 反模式 | 修正 |
|---|---|
| Plan 包含上百个 task | 拆 plan 或提高粒度 |
| 所有 task 都依赖上一个 | 找并行机会 |
| 失败直接放弃 | 区分可恢复 / 不可恢复 |
| LLM 自由发挥 plan | 加 schema 校验 |
| 把副作用强的操作当 task | 用 worker + 审批门 |
| 无超时 | 每个 task 设置 timeout |

---

## 调试

```python
planner = TaskPlanner(llm=llm, debug=True)
plan = planner.plan(goal, ctx)
print(plan.visualize())   # ASCII DAG
result = planner.execute(plan)
print(result.timeline)    # 时间线
```

可视化、trace、日志三件套，定位问题必备。

---

## 参考

- `agent/task_planner.py` —— 入口实现
- `agent/conversation_loop.py` —— 与主循环的协作
- `tests/unit/test_m8.py` —— planner 测试参考
- `docs/03-agent-loop.md` —— 主循环文档
