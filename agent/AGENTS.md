# agent/AGENTS.md

## 本包职责

Agent 核心运行时：负责对话循环、上下文管理、工具调用、消息流处理。

## 核心模块

- `agent_runtime_helpers.py`：Agent 运行时辅助函数（7KB）
- `context_compressor.py`：上下文压缩（14KB）
- `conversation_compression.py`：对话压缩
- `chat_completion_helpers.py`：聊天补全辅助
- `agent_init.py`：Agent 初始化
- `client_lifecycle.py`：客户端生命周期
- `context_breakdown.py`：上下文分解
- `compression_facade.py`：压缩门面
- `context_engine.py`：上下文引擎
- `display.py`：终端显示组件
- `prompt_builder.py`：提示词构建器
- `system_prompt.py`：系统提示词管理
- `turn_finalizer.py`：回合终结器
- `provider_router.py`：Provider 路由器
- `cost_tracker.py`：成本追踪器
- `langfuse_integration.py`：Langfuse 集成
- `prompt_optimizer/`：Prompt 优化器（evaluator/selector/cot_engine/tuner/ab_test + compressor/template_library/meta_prompt/safety/report/optimizer_v2）
- `checkpoint.py`：CheckpointManager 断点续传
- `replay.py`：TrajectoryReplay 轨迹回放（4 模式）
- `execution_sandbox.py`：ExecutionSandbox 代码沙箱（4 安全策略）
- `task_planner.py`：TaskPlanner 任务规划（依赖图）
- `memory_consolidator.py`：MemoryConsolidator 记忆整合
- `tool_recommender.py`：ToolRecommender 工具推荐
- `agent_analytics.py`：AgentAnalytics 性能分析
- `transports/`：多 Provider 适配器（19 个）

## 注意事项

- Agent 主循环不应直接调用外部 API，全部通过 `provider_router.py`
- 所有上下文操作必须通过 `context_engine.py` 门面
- 工具调用通过 `tools/` 注册系统，避免硬编码
- 终端展示通过 `display.py` 统一格式化
