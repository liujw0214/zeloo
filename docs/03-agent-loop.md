# 03. Agent 对话循环

## 3.1 核心循环

Agent Loop 是 Zeloo 的运行时心脏，遵循**思考-行动（Think-Act）**模式。核心逻辑精简到不足 10 行：

```python
while (api_call_count < self.max_iterations
       and self.iteration_budget.remaining > 0) \
       or self._budget_grace_call:
    if self._interrupt_requested:
        break
    response = client.chat.completions.create(
        model=model, messages=messages, tools=tool_schemas
    )
    if response.tool_calls:
        for tool_call in response.tool_calls:
            result = handle_function_call(tool_call.name, tool_call.args, task_id)
            messages.append(tool_result_message(result))
        api_call_count += 1
    else:
        return response.content

### 3.3 线程池并行执行

工具调用使用**线程池并行执行**，上限 **8 个 worker**。当 Agent 在一轮对话中触发多个工具调用时（如并行读取多个文件），这些调用同时执行，显著降低延迟：

```python
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=8)
futures = [executor.submit(handle_function_call, tc.name, tc.args) for tc in tool_calls]
results = [f.result() for f in futures]
```

**设计要点**：
- 循环为**同步执行**，父级等待子 Agent 完成
- 工具并行仅适用于一轮内的多个独立工具调用
- 子 Agent 的委托调用本身也是并行执行（`delegate_task`）
```

## 3.2 循环控制参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_iterations` | 90 | 工具调用迭代上限 |
| `iteration_budget` | 动态 | 更细粒度的 token/调用预算控制 |
| `_budget_grace_call` | True | 预算耗尽后允许额外执行一次（避免任务中途截断） |
| `_interrupt_requested` | False | 用户中断信号 |

### 3.2.1 迭代预算

`iteration_budget` 提供比 `max_iterations` 更精细的控制：

- 可基于 token 消耗、调用次数、时间等维度
- 预算耗尽时设置 `_budget_grace_call = True`，允许再执行一次以完成当前任务
- 避免任务在工具调用中途被截断导致状态不一致

### 3.2.2 中断机制

Zeloo 支持**双重中断机制**：

**① `_interrupt_requested` 信号（软中断）**
用户可通过 `Ctrl+C` 或平台特定中断信号设置 `_interrupt_requested = True`。

**② `estop.is_stopped()` 全局紧急停止（硬中断）**

```python
# agent/conversation_loop.py — 循环开头双重检查
while (api_call_count < self.max_iterations ...):
    if estop.is_stopped():
        return f"[emergency stop: {estop.get_reason()}]"
    if self._interrupt_requested:
        break
    # ...
```

中断处理流程：
1. 循环开始时**双重检查** `estop.is_stopped()` 和 `_interrupt_requested`
2. 若已置位，立即 break，返回当前已生成的内容
3. 正在执行的工具调用通过 `cancel_futures` 取消
4. 已完成的工具结果保留在 messages 中（不回滚）

`estop` 支持嵌套触发（栈式），多个子系统可独立请求停止。

### 3.2.3 estop 完整 API

**触发场景**：

| 场景 | `by` 字段 | 说明 |
|------|-----------|------|
| 用户主动 `/stop` | `user` | 最常见 |
| 安全威胁检测 | `security` | Prompt 注入、越权操作 |
| 资源耗尽 | `system` | OOM、磁盘满 |
| 超时 | `timeout` | 会话超时 |

**嵌套触发**：

```
trigger("reason A")      # stack: [A]
trigger("reason B")     # stack: [A, B]
is_stopped() → True     # 任一层触发则停止
reset()                 # pop → stack: [A]  仍停止
reset()                 # pop → stack: []    解除
```

**与 `_interrupt_requested` 的区别**：

| 维度 | `_interrupt_requested` | `estop.is_stopped()` |
|------|------------------------|----------------------|
| 粒度 | 单会话 | 全局（跨所有会话） |
| 触发 | 平台层（Ctrl+C） | 任意子系统 |
| 恢复 | 自动清除 | 需显式 `reset()` |
| 用途 | 用户中断 | 安全/系统级停止 |

**对话循环中的精确集成位置**（`agent/conversation_loop.py`）：

```python
def run_conversation(self, message: str) -> str:
    # 循环前检查 — 立即返回，不进入循环
    if estop.is_stopped():
        return f"[emergency stop: {estop.get_reason()}]"

    while (self.iteration_budget.remaining > 0) or self._budget_grace_call:
        # 循环内检查 — 安全边界
        if estop.is_stopped():
            break  # 已在 messages 中的工具结果保留
        if self._interrupt_requested:
            break
        # ...
```



## 3.3 工具执行

### 3.3.1 并行执行

```python
from concurrent.futures import ThreadPoolExecutor

def execute_tool_calls(tool_calls, task_id):
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(handle_function_call, tc.name, tc.args, task_id): tc
            for tc in tool_calls
        }
        results = []
        for future in as_completed(futures):
            results.append(future.result())
    return results
```

- 使用线程池并行执行，上限 **8 个 worker**
- 工具之间无依赖时可并行（如同时读取多个文件）
- 有依赖的工具调用需 LLM 在后续轮次串行发起

### 3.3.2 工具调用处理

```python
def handle_function_call(name, args, task_id):
    tool = self.tool_registry.get(name)
    if tool is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        result = tool.execute(**args)
        return {"name": name, "result": result}
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return {"name": name, "error": str(e)}
```

**错误处理原则**：
- 工具执行异常**不中断循环**，将错误信息作为 tool result 返回给 LLM
- LLM 可根据错误信息决定重试、换工具或放弃
- 严重异常（如 OOM）才触发中断

**生命周期钩子 + 洞察集成**：

```python
# run_agent.py execute_tool() — 完整流程
def execute_tool(self, tool_name: str, args: dict) -> Any:
    # PRE_TOOL_CALL 钩子：可修改参数
    evt = self._hooks.dispatch(HookType.PRE_TOOL_CALL, tool_name=tool_name, args=args)
    args = evt.args

    start = time.monotonic()
    try:
        result = self._tool_registry.execute(tool_name, **args)
        elapsed_ms = (time.monotonic() - start) * 1000

        # Insights 记录
        self._insights.record_tool_call(tool_name, elapsed_ms)

        # POST_TOOL_CALL 钩子：可修改结果
        evt = self._hooks.dispatch(
            HookType.POST_TOOL_CALL, tool_name=tool_name, args=args, result=result
        )
        return evt.result

    except Exception as exc:
        self._insights.record_tool_error(tool_name, type(exc).__name__)
        raise
```

钩子异常被捕获并记录，不中断 Agent 运行。

### 3.3.2 LLM API 重试与退避

对话循环对 LLM 调用内置了**指数退避重试**机制，应对瞬时故障（限流、网络超时、服务不可用）。

**触发重试的错误类型**：
- 限流（rate limit / 429）
- 网络超时（timeout）
- 连接错误（connection）
- 服务端错误（500/502/503 / overloaded）

**退避策略**：
- 最大重试次数：`llm_max_retries`（默认 3 次）
- 退避公式：`base_delay * 2^attempt + random(0, 0.5)`（默认 base_delay=1.0s）
- 非瞬时错误（如认证失败、参数错误）不重试，直接返回错误

**配置方式**（ConversationLoop 构造参数）：
```python
loop = ConversationLoop(
    agent,
    llm_max_retries=3,
    llm_retry_base_delay=1.0,
)
```

全部重试耗尽后返回 `[LLM unavailable after retries]`，循环终止。

### 3.3.3 工具结果格式

工具结果必须是可 JSON 序列化的，且包含以下字段：

```json
{
  "name": "tool_name",
  "result": "...",      // 成功时
  "error": "..."        // 失败时（与 result 互斥）
}
```

### 3.3.4 生命周期钩子（Hooks）

工具执行过程中会触发多个生命周期钩子，插件可通过钩子注入观测、修改或拦截逻辑。

**钩子类型**：

| 钩子 | 签名 | 触发时机 |
|------|------|----------|
| `PRE_TOOL_CALL` | `(tool_name, args) → (args)` | 工具执行前，可修改参数 |
| `POST_TOOL_CALL` | `(tool_name, args, result) → result` | 工具执行后，可修改返回值 |
| `PRE_LLM_CALL` | `(messages, tools) → (messages, tools)` | LLM 调用前 |
| `POST_LLM_CALL` | `(response) → response` | LLM 调用后 |
| `ON_SESSION_START` | `(session_id)` | 会话创建 |
| `ON_SESSION_END` | `(session_id)` | 会话结束 |
| `TRANSFORM_OUTPUT` | `(content) → content` | 最终输出文本转换 |

**完整调用链（工具）**：

```python
def execute_tool(self, tool_name: str, args: dict) -> Any:
    # 1. PRE_TOOL_CALL — 可修改 args
    evt = self._hooks.dispatch(
        HookType.PRE_TOOL_CALL,
        tool_name=tool_name,
        args=args,
    )
    args = evt.args

    # 2. 执行
    start = time.monotonic()
    try:
        result = self._tool_registry.execute(tool_name, **args)
        elapsed_ms = (time.monotonic() - start) * 1000
        self._insights.record_tool_call(tool_name, elapsed_ms)
    except Exception as exc:
        self._insights.record_tool_error(tool_name, type(exc).__name__)
        raise

    # 3. POST_TOOL_CALL — 可修改 result
    evt = self._hooks.dispatch(
        HookType.POST_TOOL_CALL,
        tool_name=tool_name,
        args=args,
        result=result,
    )
    return evt.result
```

**完整调用链（LLM）**：

```python
def call_llm(self, messages: list, tools: list) -> dict:
    # 1. PRE_LLM_CALL — 可修改 messages 和 tools
    evt = self._hooks.dispatch(
        HookType.PRE_LLM_CALL,
        messages=messages,
        tools=tools,
    )
    messages, tools = evt.messages, evt.tools

    # 2. 调用
    response = self._client.chat.completions.create(
        model=model, messages=messages, tools=tools,
    )

    # 3. POST_LLM_CALL — 可修改响应
    evt = self._hooks.dispatch(HookType.POST_LLM_CALL, response=response)
    return evt.response
```

**错误处理**：钩子回调中抛出的异常被捕获并记录日志，不中断 Agent 运行。

### 3.3.5 运行时洞察（Insights）

`Insights` 在每次工具调用和 LLM 调用时自动采集指标：

**采集时机**：

| 指标 | 触发点 | 记录内容 |
|------|--------|----------|
| `tool_call` | `execute_tool` 成功后 | tool_name、elapsed_ms |
| `tool_error` | `execute_tool` 抛出异常 | tool_name、error_type |
| `llm_call` | `call_llm` 完成后 | model、input_tokens、output_tokens、latency_ms |

**API**：

```python
from agent.insights import insights

insights.record_tool_call("file_read", elapsed_ms=120)
insights.record_tool_error("shell", "TimeoutError")
insights.record_llm_call(
    model="gpt-4o",
    input_tokens=800,
    output_tokens=400,
    latency_ms=850,
)

report = insights.generate_report()
# report["summary"]: {total_calls, total_iterations}
# report["top_tools"]: 调用次数/耗时/错误率
# report["recommendations"]: 自动优化建议
```

**与 Provider Router 的关系**：ErrorClassifier 将错误分类结果传给 Insights，错误聚合统计用于生成优化建议（如"Provider X 错误率偏高"）。

## 3.4 消息历史管理

### 3.4.1 消息结构

```python
@dataclass
class Message:
    role: str          # "system" | "user" | "assistant" | "tool"
    content: str
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
```

### 3.4.2 历史裁剪

当消息历史超过上下文窗口时，触发 **context compression**。触发条件为**任一**：
- 消息条数超过 `DEFAULT_CONTEXT_MAX_MESSAGES`（默认 40）
- 估算 token 数超过 `max_context_tokens`（默认 128000）

裁剪策略：

1. 保留 system prompt（从缓存复用）
2. 保留最近 N 轮对话（可配置，默认 10 轮）
3. 中间轮次压缩为摘要
4. 工具结果中的长文本截断（保留首尾）

压缩完成后调用 `invalidate_system_prompt()` 重建 system prompt（捕获本会话的记忆/技能变化）。

> Token 计数优先使用 `tiktoken`（cl100k_base 编码），不可用时回退到字符数 / 4 估算。

### 3.4.3 工具参数校验

在调用 `execute_tool` 之前，对话循环会对工具参数进行 **schema 校验**：

- **必填字段检查**：缺失 required 参数直接返回错误，不执行工具
- **类型检查**：string / integer / number / boolean / array / object 类型不匹配返回错误
- **容错**：未知工具或无 schema 的工具跳过校验，交给 `execute_tool` 处理

校验失败时返回 `Argument validation error: ...` 给 LLM，使其能修正调用。

### 3.4.4 轨迹采集

每轮对话的完整轨迹（messages + tool_calls + tool_results）持久化到 SQLite，用于：

- 会话恢复
- 自进化复盘
- 训练数据生成（ShareGPT 格式）

## 3.5 Provider 交互

### 3.5.1 请求构建

```python
def build_api_request(self, messages):
    return {
        "model": self.model,
        "messages": [self._cached_system_prompt, *messages],
        "tools": self.tool_schemas,
        "temperature": self.temperature,
        "max_tokens": self.max_tokens,
        "stream": self.stream,
    }
```

System prompt 直接使用缓存的完整字符串，不重新构建。

### 3.5.2 流式输出

启用 `stream=True` 时：

- LLM 响应以 token 流形式返回
- 实时显示到 CLI / 转发到消息平台
- tool_call 参数边生成边解析，参数完整后立即执行（不等整个响应结束）

### 3.5.3 Provider 故障转移

```python
def call_llm(self, messages):
    for provider in self.provider_chain:
        try:
            return provider.chat.completions.create(...)
        except Exception as exc:
            # ErrorClassifier 结构化分类
            result = classify_error(exc, provider=provider.name)
            if not result.retryable:
                # 不可重试（认证失败/参数错误）→ 切换 Provider
                self._router.switch_to_next()
                continue
            # 可重试 → 等待后重试
            time.sleep(result.retry_delay_seconds)
            if result.should_fallback_provider:
                self._router.switch_to_next()
    raise AllProvidersFailedError()
```

- 主 Provider 故障时通过 `ErrorClassifier` 分类决定是否重试/降级
- `CredentialPool` 管理多 Key 轮询，失败时自动熔断/冷却
- `ProviderRouter` 持有 `CredentialPool` 实例，每次调用 `resolve()` 获取当前可用 Key

## 3.6 循环结束条件

循环在以下任一条件满足时结束：

1. LLM 返回纯文本响应（无 tool_calls）→ 任务完成
2. `api_call_count >= max_iterations` → 达到迭代上限
3. `iteration_budget.remaining <= 0` 且无 grace call → 预算耗尽
4. `_interrupt_requested` 为 True → 用户中断
5. 所有 Provider 均失败 → 不可恢复错误

结束后进入 **Turn Finalizer** 阶段（见 [自进化闭环](./06-self-evolution.md)）。
