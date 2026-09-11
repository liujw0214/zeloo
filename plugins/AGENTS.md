# plugins/AGENTS.md

## 本包职责

插件系统：负责 Provider、Web、Image、Video、Browser 等扩展点。

## 核心模块

- `browser_providers.py`：浏览器提供者（browserbase/firecrawl）
- `web_providers/`：网络搜索提供者（tavily/duckduckgo/perplexity）
- `model_providers/`：模型提供者（deepseek/gemini）
- `image_gen/`：图像生成（dalle/fal/stability）
- `video_gen/`：视频生成（deepinfra/fal/xai）
- `langfuse_integration.py`：可观测性集成（位于 agent/）

## 注意事项

- 所有 Provider 必须实现 `Provider` 协议
- 注册到 `registry.py` 才能被 Agent 发现
- 付费 Provider 必须检查预算限制
- 失败的 Provider 必须有 fallback 机制
