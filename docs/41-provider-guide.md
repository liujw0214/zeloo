# Provider 使用指南

Zeloo 通过 Provider 抽象层统一接入外部 AI / Web / MCP 服务，支持热插拔、环境隔离、自动回退。

---

## 目录

1. [Provider 架构](#1-provider-架构)
2. [LLM Provider](#2-llm-provider)
3. [Web Search Provider](#3-web-search-provider)
4. [MCP Server Provider](#4-mcp-server-provider)
5. [Image Generation Provider](#5-image-generation-provider)
6. [Video Generation Provider](#6-video-generation-provider)
7. [Messaging Provider](#7-messaging-provider)
8. [Provider 路由](#8-provider-路由)
9. [成本追踪](#9-成本追踪)
10. [环境变量配置](#10-环境变量配置)

---

## 1. Provider 架构

```
llm_providers/          # 41 个 LLM Provider（OpenAI / Anthropic / 本地模型等）
web_providers/          # 39 个 Web Search Provider
mcp/                    # 65 个 MCP Server Provider
image_gen/              # 8 个图片生成 Provider
video_gen/              # 3 个视频生成 Provider
messaging/              # 18 个消息平台 Provider
```

所有 Provider 共享统一配置机制：

```python
from zeloo.core.config import Config

cfg = Config.from_env()          # 从环境变量读取
cfg.model                        # 当前使用的 LLM 模型
cfg.web_provider                 # 当前 Web Provider 名称
cfg.mcp_provider                 # 当前 MCP Provider
```

---

## 2. LLM Provider

### 2.1 支持的模型（部分）

| Provider | 模型 | API 类型 |
|----------|------|----------|
| OpenAI | gpt-4o, gpt-4o-mini, gpt-4-turbo | OpenAI REST |
| Anthropic | claude-3-5-sonnet, claude-3-haiku | Anthropic REST |
| Google | gemini-2.0-flash, gemini-1.5-pro | Google AI |
| DeepSeek | deepseek-chat, deepseek-coder | DeepSeek REST |
| Groq | llama-3.1-8b, mixtral-8x7b | Groq REST |
| Ollama | llama3, mistral, codellama | Ollama Local |
| LM Studio | (any served model) | OpenAI-compatible |
| vLLM | (any served model) | OpenAI-compatible |

### 2.2 使用示例

```python
from zeloo.core.config import Config

cfg = Config.from_env()

# 通过 provider 名称使用
result = cfg.llm_provider.complete(
    messages=[{"role": "user", "content": "Hello!"}],
    model=cfg.model,
    temperature=0.7,
)

# 流式输出
for chunk in cfg.llm_provider.stream(
    messages=[{"role": "user", "content": "Tell me a story"}],
    model=cfg.model,
):
    print(chunk, end="", flush=True)
```

### 2.3 切换 Provider

```bash
export zeloo_MODEL=anthropic/claude-3-5-sonnet-latest
export zeloo_LLM_PROVIDER=anthropic
```

或在代码中：

```python
from zeloo.llm_providers.factory import get_llm_provider

provider = get_llm_provider("openai", api_key="sk-...")
result = provider.complete(messages=[...])
```

---

## 3. Web Search Provider

### 3.1 支持的 Provider

| Provider | 环境变量 |
|----------|----------|
| Google | `GOOGLE_API_KEY` + `GOOGLE_SEARCH_ENGINE_ID` |
| DuckDuckGo | 无（免费） |
| Bing | `BING_API_KEY` |
| Serper | `SERPER_API_KEY` |
| Brave Search | `BRAVE_API_KEY` |
| Tavily | `TAVILY_API_KEY` |
| Exa | `EXA_API_KEY` |
| Firecrawl | `FIRECRAWL_API_KEY` |
| OpenStreetMap | 无（免费） |
| Brave News | `BRAVE_API_KEY` |

### 3.2 使用示例

```python
from zeloo.web_providers.factory import get_web_provider

provider = get_web_provider("duckduckgo")
results = provider.search("Python async best practices")
for r in results:
    print(r.title, r.url)

# Google 搜索
google = get_web_provider("google", api_key=os.environ["GOOGLE_API_KEY"])
results = google.search("site:github.com zeloo agent")
```

---

## 4. MCP Server Provider

Model Context Protocol — JSON-RPC stdio 服务框架。

### 4.1 内置 MCP Server

| Server | 命令 | 说明 |
|--------|------|------|
| filesystem | `npx -y @modelcontextprotocol/server-filesystem` | 文件读写 |
| sequential-thinking | `npx -y @modelcontextprotocol/server-sequential-thinking` | 思维链 |
| google-maps | `npx -y @modelcontextprotocol/server-google-maps` | 地图服务 |

### 4.2 使用示例

```python
from zeloo.mcp import MCPServer, MCPClient

# 启动 filesystem MCP server
server = MCPServer(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    name="filesystem",
)

# 通过 Agent 调用
client = MCPClient(server)
result = await client.call_tool("read_file", {"path": "/tmp/test.txt"})
```

---

## 5. Image Generation Provider

### 5.1 支持的模型

| Provider | 模型 | API |
|----------|------|-----|
| OpenAI | DALL-E 3, DALL-E 2 | OpenAI REST |
| Anthropic | Claude Image (via API) | Anthropic REST |
| Stability AI | SDXL 1.0, SD 3 | Stability REST |
| Replicate | FLUX.1, SDXL | Replicate API |
| DeepInfra | FLUX.1-schnell | DeepInfra REST |
| Fal.ai | SDXL, ControlNet | Fal.ai REST |

### 5.2 使用示例

```python
from zeloo.image_gen import get_provider

provider = get_provider("openai", api_key=os.environ["OPENAI_API_KEY"])
result = await provider.generate(
    prompt="A serene mountain landscape at sunset, digital art",
    model="dall-e-3",
    size="1024x1024",
)
print(result.url)  # 图片 URL
print(result.revised_prompt)  # DALL-E 修订后的提示词
```

---

## 6. Video Generation Provider

### 6.1 支持的模型

| Provider | 模型 | 环境变量 |
|----------|------|----------|
| DeepInfra | Hunyuan Video, Wan 2.1, Mochi, LTX-Video | `DEEPINFRA_API_KEY` |
| FAL.ai | Kling 1.6, Luma Hailuo, CogVideoX | `FAL_API_KEY` |
| xAI | Grok Video Preview | `XAI_API_KEY` |

### 6.2 使用示例

```python
from zeloo.video_gen import get_provider

provider = get_provider("deepinfra", api_key=os.environ["DEEPINFRA_API_KEY"])
result = await provider.generate(
    prompt="A serene forest with sunlight filtering through trees",
    model="hunyuan_video",
    duration_seconds=5,
    resolution="720p",
)
print(result.video_url)
print(f"Estimated cost: ${result.estimated_cost:.4f}")
```

---

## 7. Messaging Provider

支持 18 个消息平台：Telegram、Discord、Slack、飞书、钉钉、微信企业号、邮件 (SMTP/IMAP)、LINE、WhatsApp 等。

```python
from zeloo.messaging import get_messaging_provider

telegram = get_messaging_provider("telegram", bot_token=os.environ["TELEGRAM_BOT_TOKEN"])
await telegram.send_message(chat_id="@my_channel", text="Hello from Zeloo!")
```

---

## 8. Provider 路由

### 8.1 自动选择最优 Provider

```python
from zeloo.core.provider_router import ProviderRouter

router = ProviderRouter()
router.add_provider("openai", llm_provider, weight=10)
router.add_provider("deepseek", deepseek_provider, weight=8)
router.add_provider("groq", groq_provider, weight=5)

# 按权重分配
provider = router.get_provider()
```

### 8.2 故障转移

```python
router = ProviderRouter(failover=True)
router.add_provider("primary", primary_provider)
router.add_provider("secondary", secondary_provider)

# primary 失败时自动切换到 secondary
result = router.execute_with_fallback(lambda p: p.complete(messages))
```

---

## 9. 成本追踪

```python
from agent.cost_tracker import CostTracker

tracker = CostTracker(warn_threshold_usd=1.0, abort_threshold_usd=10.0)

# 记录使用
tracker.record(
    model="gpt-4o",
    input_tokens=1000,
    output_tokens=500,
    provider="openai",
)

# 查询成本
print(tracker.get_total_cost())  # 总成本 (USD)
print(tracker.format_cost("CNY"))  # 人民币
print(tracker.format_cost("EUR"))  # 欧元

# 环境变量覆盖
os.environ["zeloo_COST_WARN_THRESHOLD"] = "2.0"
os.environ["zeloo_COST_ABORT_THRESHOLD"] = "20.0"
```

---

## 10. 环境变量配置

### 10.1 LLM Provider

```bash
zeloo_MODEL=openai/gpt-4o-mini
zeloo_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
DEEPSEEK_API_KEY=sk-...
```

### 10.2 Web Provider

```bash
zeloo_WEB_PROVIDER=duckduckgo
GOOGLE_API_KEY=AIza...
BING_API_KEY=...
SERPER_API_KEY=...
```

### 10.3 Image / Video Provider

```bash
OPENAI_API_KEY=sk-...
STABILITY_API_KEY=sk-...
REPLICATE_API_KEY=r8_...
DEEPINFRA_API_KEY=...
FAL_API_KEY=...
XAI_API_KEY=...
```

### 10.4 MCP Provider

```bash
zeloo_MCP_SERVERS=filesystem,sequential-thinking
```

---

## 附录：Provider 测试

所有 Provider 均有单元测试覆盖：

```bash
# LLM Provider 测试
pytest tests/unit/test_llm_providers.py -v

# Web Provider 测试
pytest tests/unit/test_web_providers.py -v

# Image Gen 测试
pytest tests/unit/test_image_gen.py -v

# Video Gen 测试
pytest tests/unit/test_video_gen.py -v

# Provider 集成测试
pytest tests/integration/test_provider_integration.py -v
```
