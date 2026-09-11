# 18. Agent 核心模块开发计划

> 本文档案记录 Zeloo Agent 核心模块的 API 设计。所有 11 个模块均已实现（见"现状"列），本文档保留作为代码规范参考。

## 18.1 模块总览

### 核心实现

| 模块 | 预估大小 | 优先级 | Zeloo 现状 |
|------|------------|--------|-------------|
| `agent_runtime_helpers.py` | 7KB | P1 | ✅ 已实现 |
| `context_compressor.py` | 14KB | P1 | ✅ 已实现 |
| `conversation_compression.py` | 8KB | P1 | ✅ 已实现 |
| `chat_completion_helpers.py` | 10KB | P1 | ✅ 已实现 |
| `agent_init.py` | 9KB | P1 | ✅ 已实现 |
| `client_lifecycle.py` | 9KB | P2 | ✅ 已实现 |
| `context_breakdown.py` | — | P2 | ✅ 已实现 |
| `compression_facade.py` | — | P2 | ✅ 已实现 |
| `context_engine.py` | — | P2 | ✅ 已实现 |
| `display.py` | 11KB | P2 | ✅ 已实现 |
| `prompt_builder.py` | 8KB | P2 | ✅ 已实现 |

### 高级扩展（第二轮扩展）

| 模块 | 优先级 | 关键能力 | Zeloo 现状 |
|------|--------|----------|-------------|
| `checkpoint.py` | P1 | CheckpointManager 断点续传 | ✅ 已实现 |
| `replay.py` | P1 | TrajectoryReplay 轨迹回放（4 模式） | ✅ 已实现 |
| `execution_sandbox.py` | P1 | ExecutionSandbox 代码沙箱（4 策略） | ✅ 已实现 |
| `task_planner.py` | P1 | TaskPlanner 任务规划与依赖 | ✅ 已实现 |
| `memory_consolidator.py` | P2 | MemoryConsolidator 记忆整合 | ✅ 已实现 |
| `tool_recommender.py` | P2 | ToolRecommender 工具智能推荐 | ✅ 已实现 |
| `agent_analytics.py` | P2 | AgentAnalytics 性能指标分析 | ✅ 已实现 |

---

## 18.2 agent_runtime_helpers.py（P1）

### 18.2.1 职责

运行时辅助函数集，封装 `run_agent.py` 和 `conversation_loop.py` 中的高频通用逻辑，供各模块复用。

### 18.2.2 预计 API 设计

```python
# agent/agent_runtime_helpers.py

def resolve_model_config(agent) -> ModelConfig:
    """从 agent 配置中解析模型信息。"""

def build_tool_context(tools: list[Tool]) -> dict[str, Any]:
    """构建工具上下文，注入到 system prompt。"""

def truncate_messages_for_context(
    messages: list[Message], max_tokens: int
) -> list[Message]:
    """截断消息列表以适应上下文窗口。"""

def resolve_session_id(platform: str, user_id: str) -> str:
    """根据平台和用户 ID 生成稳定会话 ID。"""

def compute_token_estimate(text: str) -> int:
    """估算文本的 token 数量（cl100k_base）。"""

def should_compress_context(agent) -> bool:
    """判断当前上下文是否需要压缩。"""
```

---

## 18.3 context_compressor.py（P1）

### 18.3.1 职责

最大的核心文件（14KB），负责上下文压缩的核心算法。压缩策略包括：

- **对话历史摘要**：对长对话进行语义摘要，保留关键信息
- **工具调用去重**：合并重复的相似工具调用
- **Token 预算控制**：确保上下文不超过模型窗口限制
- **重要性评分**：对消息按重要性打分，优先保留高价值内容

### 18.3.2 预计 API 设计

```python
# agent/context_compressor.py

class ContextCompressor:
    def __init__(self, max_tokens: int = 128000):
        self.max_tokens = max_tokens

    def compress(
        self,
        messages: list[Message],
        strategy: CompressionStrategy = "hybrid",
    ) -> list[Message]:
        """压缩消息列表，返回压缩后的消息。"""
        ...

    def summarize_messages(
        self, messages: list[Message], target_tokens: int
    ) -> list[Message]:
        """对消息进行语义摘要。"""
        ...

    def deduplicate_tool_calls(
        self, messages: list[Message]
    ) -> list[Message]:
        """合并重复的工具调用。"""
        ...

    def score_message_importance(
        self, message: Message
    ) -> float:
        """给单条消息打分（0.0-1.0）。"""
        ...
```

### 18.3.3 压缩策略

| 策略 | 描述 | 适用场景 |
|------|------|----------|
| `hybrid` | 摘要 + 去重 + 截断组合 | 长对话 |
| `summarize` | 仅语义摘要 | 超长单轮对话 |
| `prune` | 按重要性保留高分区段 | 高频短对话 |
| `truncate` | 简单截断尾部 | 紧急内存不足 |

---

## 18.4 conversation_compression.py（P1）

### 18.4.1 职责

对话压缩器，专注于压缩 `messages` 列表。与 `context_compressor.py` 的区别：

- `context_compressor` 侧重算法和策略
- `conversation_compression` 侧重消息格式和协议兼容

### 18.4.2 预计 API 设计

```python
# agent/conversation_compression.py

class ConversationCompressor:
    def compress_for_model(
        self,
        messages: list[Message],
        model: str,
    ) -> list[Message]:
        """根据模型上下文窗口压缩对话。"""
        ...

    def preserve_recent_turns(
        self,
        messages: list[Message],
        min_recent_turns: int = 3,
    ) -> list[Message]:
        """始终保留最近 N 轮完整原文。"""
        ...

    def extract_tool_call_patterns(
        self, messages: list[Message]
    ) -> list[str]:
        """提取工具调用模式，用于提示词注入。"""
        ...
```

---

## 18.5 chat_completion_helpers.py（P1）

### 18.5.1 职责

Chat Completion API 调用辅助（10KB），封装 OpenAI/Anthropic 等各种 Provider 的消息格式转换、请求构建、响应解析。

### 18.5.2 预计 API 设计

```python
# agent/chat_completion_helpers.py

def build_chat_request(
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    **kwargs,
) -> dict[str, Any]:
    """构建 Provider 无关的 chat 请求。"""
    ...

def parse_chat_response(
    response: Any,
    provider: str,
) -> ChatResponse:
    """解析各 Provider 的响应格式。"""
    ...

def convert_messages_format(
    messages: list[Message],
    target_provider: str,
) -> list[dict]:
    """将标准 Message 转换为特定 Provider 格式。"""
    ...

def estimate_response_tokens(
    request: dict[str, Any],
    model: str,
) -> int:
    """估算响应的最大 token 数。"""
    ...
```

---

## 18.6 agent_init.py（P1）

### 18.6.1 职责

Agent 初始化逻辑（9KB），集中管理 `AIAgent.__init__()` 的所有配置加载、依赖注入、状态初始化。

### 18.6.2 预计 API 设计

```python
# agent/agent_init.py

class AgentInitializer:
    def __init__(self, config: AgentConfig):
        self.config = config

    def load_tools(self) -> ToolRegistry:
        """加载所有启用的工具集。"""

    def load_skills(self) -> SkillManager:
        """加载技能管理器。"""

    def load_memory(self) -> MemoryProvider:
        """根据配置选择记忆后端。"""

    def load_provider(self) -> ProviderRouter:
        """初始化 Provider 路由器。"""

    def init_session(self) -> SessionDB:
        """初始化或恢复会话。"""

    def validate_config(self) -> None:
        """验证配置完整性，缺失则报错。"""

def create_agent(config: dict | AgentConfig) -> AIAgent:
    """工厂函数，通过配置字典或对象创建 Agent。"""
    ...
```

---

## 18.7 prompt_builder.py（P2）

### 18.7.1 职责

提示词构建器（8KB），将三层 System Prompt 的构建逻辑从 `system_prompt.py` 抽离，提供更细粒度的模板管理和注入控制。

### 18.7.2 预计 API 设计

```python
# agent/prompt_builder.py

class PromptBuilder:
    def __init__(self, templates_dir: Path | None = None):
        self.templates = self._load_templates(templates_dir)

    def build(
        self,
        layer: PromptLayer,  # stable / context / volatile
        context: dict[str, Any],
    ) -> str:
        """构建指定层的 prompt 内容。"""
        ...

    def inject_skill_prompts(self, skills: list[Skill]) -> str:
        """将技能描述注入 stable 层。"""

    def inject_memory_snapshot(self, snapshot: MemorySnapshot) -> str:
        """将记忆快照注入 volatile 层。"""

    def build_full_system_prompt(self, agent) -> str:
        """构建完整的 system prompt（三层拼接）。"""
        ...
```

---

## 18.8 client_lifecycle.py（P2）

### 18.8.1 职责

Provider 客户端生命周期管理：连接池、超时、重试、心跳检测、优雅关闭。

### 18.8.2 预计 API 设计

```python
# agent/client_lifecycle.py

class ClientLifecycle:
    def __init__(self, provider: ProviderRouter):
        self.provider = provider
        self._pool: dict[str, Any] = {}

    def acquire(self, provider_name: str) -> Any:
        """获取一个 Provider 客户端实例。"""
        ...

    def release(self, provider_name: str) -> None:
        """归还客户端到池中。"""

    def health_check(self) -> dict[str, bool]:
        """检查所有活跃客户端健康状态。"""

    def graceful_shutdown(self) -> None:
        """优雅关闭所有客户端连接。"""
```

---

## 18.9 context_breakdown.py（P2）

### 18.9.1 职责

上下文分解工具，将大段上下文拆分为可独立处理的片段，便于并行处理和增量更新。

### 18.9.2 预计 API 设计

```python
# agent/context_breakdown.py

def breakdown_by_tokens(
    text: str, chunk_size: int = 4000
) -> list[str]:
    """按 token 数拆分为块。"""

def breakdown_by_turns(
    messages: list[Message], chunk_turns: int = 10
) -> list[list[Message]]:
    """按对话轮次拆分为组。"""

def breakdown_by_semantic(
    messages: list[Message], max_groups: int = 5
) -> list[list[Message]]:
    """按语义主题拆分（LLM 辅助）。"""
```

---

## 18.10 compression_facade.py（P2）

### 18.10.1 职责

压缩门面，统一 `context_compressor` 和 `conversation_compression` 的压缩入口。

```python
# agent/compression_facade.py

class CompressionFacade:
    def compress(
        self,
        messages: list[Message],
        mode: CompressionMode = "auto",
    ) -> list[Message]:
        """自动选择最优压缩策略。"""

    def set_strategy(self, strategy: CompressionStrategy) -> None:
        """手动设置压缩策略。"""

    def estimate_savings(
        self, messages: list[Message]
    ) -> float:
        """估算压缩节省的比例（0.0-1.0）。"""
```

---

## 18.11 context_engine.py（P2）

### 18.11.1 职责

上下文引擎，协调 System Prompt 构建、消息管理、压缩决策、Token 预算分配。

```python
# agent/context_engine.py

class ContextEngine:
    def __init__(self, agent: AIAgent):
        self.agent = agent

    def prepare_messages(self) -> list[Message]:
        """准备发送给 LLM 的消息列表（含压缩）。"""

    def update_context(
        self,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        """更新当前上下文（追加或替换）。"""

    def get_token_budget(self) -> TokenBudget:
        """获取当前 Token 预算状态。"""
```

---

## 18.12 display.py（P2）

### 18.12.1 职责

终端显示组件（11KB），封装 Rich 的格式化输出，提供 Agent 状态的优雅展示。

```python
# agent/display.py

class AgentDisplay:
    def show_welcome(self, agent_name: str) -> None:
        """显示欢迎信息。"""

    def show_thinking(self, step: int, tool: str) -> None:
        """显示思考状态（LLM 思考中）。"""

    def show_tool_call(self, tool_name: str, args: dict) -> None:
        """显示工具调用。"""

    def show_tool_result(self, result: str) -> None:
        """显示工具结果。"""

    def show_error(self, error: Exception) -> None:
        """显示错误信息（红色）。"""

    def show_session_info(self, session_id: str, model: str) -> None:
        """显示会话信息。"""
```
