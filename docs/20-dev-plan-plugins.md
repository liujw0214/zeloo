# 20. 插件系统扩展开发计划

> 记录 Zeloo 缺失或需扩展的插件模块。

## 20.1 模块总览

| 插件 | 实现状态 | 实际文件 | 优先级 |
|------|---------|---------|--------|
| `model_providers/` | ✅ 41 个 Provider（详见 20.2.1 表格） | 43 个文件 | P1 |
| `web_providers/` | ✅ Tavily + DuckDuckGo + Perplexity + Brave + Exa + SearXNG + Firecrawl + GoogleCSE + Serper + Kagi + You.com + Parallel + Keenable + SerpAPI + Grok Search + Yandex + Mojeek + 360 Search + GoogleScholar + SemanticScholar + Arxiv + PubMed + Algolia + Baidu + Naver + Sogou + BingWeb + YahooSearch + Twitter + Amazon + YouTube + Reddit + StackOverflow + GitHub + HackerNews + Indeed + OpenStreetMap + Skyscanner | 39 个文件 | P2 |
| `image_gen/` | ✅ DALL-E + FAL + Stability + DeepInfra + Krea + GrokImage + MetaAI + Registry | 8 个文件 | P2 |
| `optional_mcps/` | ✅ 65 个 MCP Server（详见 20.5 表格，**达成 100% 完成**） | 67 个文件 | P2 |
| `video_gen/` | ✅ DeepInfra + FAL + xAI + Registry | 4 个文件 | P3 |
| `browser/` | ✅ BrowserBase + Firecrawl + Base + Registry | 4 个文件 | P2 |
| `observability/langfuse` | ✅ Langfuse 全链路集成 | `agent/langfuse_integration.py` | P2 |

---

## 20.2 model_providers/ 模型提供者（P1）

### 20.2.1 目标

目标支持 41 个模型提供者。已实现 DeepSeek + Gemini，需扩展以下：

| Provider | 优先级 | 说明 |
|----------|--------|------|
| DeepSeek | ✅ 已实现 | `model_providers/deepseek.py` |
| Gemini | ✅ 已实现 | `model_providers/gemini.py` |
| Anthropic | ✅ 已实现 | `model_providers/anthropic.py`（Claude 系列，system 消息分离） |
| OpenRouter | ✅ 已实现 | `model_providers/openrouter.py`（100+ 模型，OpenAI 兼容） |
| xAI (Grok) | ✅ 已实现 | `model_providers/xai.py`（grok-3/grok-3-mini） |
| ZAI (智谱 AI) | ✅ 已实现 | `model_providers/zhipu.py`（GLM-4 系列） |
| Fireworks | ✅ 已实现 | `model_providers/fireworks.py`（高吞吐 OpenAI 兼容） |
| HuggingFace | ✅ 已实现 | `model_providers/huggingface.py`（Inference API） |
| Groq | ✅ 已实现 | `model_providers/groq.py`（超低延迟 Llama/Mixtral） |
| Cohere | ✅ 已实现 | `model_providers/cohere.py`（Command R 系列） |
| Mistral | ✅ 已实现 | `model_providers/mistral.py`（Mistral Large / Mixtral） |
| Azure OpenAI | ✅ 已实现 | `model_providers/azure_openai.py`（企业部署） |
| OpenAI | ✅ 已实现 | `model_providers/openai.py`（GPT-4o / o1 系列） |
| Together AI | ✅ 已实现 | `model_providers/together.py`（Llama / Mistral / Qwen 系列） |
| Replicate | ✅ 已实现 | `model_providers/replicate.py`（Llama / SDXL 开源模型） |
| Hyperbolic | ✅ 已实现 | `model_providers/hyperbolic.py`（低成本 Llama / Qwen） |
| Novita AI | ✅ 已实现 | `model_providers/novita.py`（Llama / Mistral / Qwen） |
| Lepton AI | ✅ 已实现 | `model_providers/lepton.py`（Llama / Mixtral / CodeLLama） |
| Cloudflare Workers AI | ✅ 已实现 | `model_providers/cloudflare.py`（边缘推理） |
| DeepInfra Chat | ✅ 已实现 | `model_providers/deepinfra.py`（Serverless GPU） |
| Perplexity Sonar | ✅ 已实现 | `model_providers/perplexity_sonar.py`（实时搜索+引用） |
| DeepSeek R1 | ✅ 已实现 | `model_providers/deepseek_r1.py`（推理模型 + Extended Thinking） |
| Cerebras | ✅ 已实现 | `model_providers/cerebras.py`（超快 GPU 推理） |
| Ollama | ✅ 已实现 | `model_providers/ollama.py`（本地/自托管，上千模型） |
| AI21 Jurassic | ✅ 已实现 | `model_providers/ai21.py`（Jamba / Command 系列） |
| LocalAI | ✅ 已实现 | `model_providers/localai.py`（自托管 OpenAI 兼容） |
| vLLM | ✅ 已实现 | `model_providers/vllm.py`（高吞吐自托管推理） |
| Anyscale | ✅ 已实现 | `model_providers/anyscale.py`（托管端点） |
| Featherless | ✅ 已实现 | `model_providers/featherless.py`（托管 Open AI 模型） |
| MonsterAPI | ✅ 已实现 | `model_providers/monsterapi.py`（GPU 加速推理） |
| Cohere Command | ✅ 已实现 | `model_providers/cohere_command.py`（RAG 优化企业模型） |
| Mistral Nemo | ✅ 已实现 | `model_providers/mistral_nemo.py`（开源前沿模型） |
| AI Horde | ✅ 已实现 | `model_providers/ai_horde.py`（分布式免费推理） |
| DeepSeek Coder | ✅ 已实现 | `model_providers/deepseek_coder.py`（代码专用） |
| Qwen / DashScope | ✅ 已实现 | `model_providers/qwen.py`（阿里云通义千问） |
| Scale AI | ✅ 已实现 | `model_providers/scale.py`（企业 AI + 数据标注） |
| Portkey | ✅ 已实现 | `model_providers/portkey.py`（100+ 模型统一网关） |
| Mistral Large 3 | ✅ 已实现 | `model_providers/mistral_large.py`（最新旗舰模型） |
| SambaNova | ✅ 已实现 | `model_providers/samba.py`（GPU 加速企业推理） |
| IBM Watsonx | ✅ 已实现 | `model_providers/watsonx.py`（Granite / Llama 企业平台） |
| AWS Bedrock | ✅ 已实现 | `model_providers/amazon_bedrock.py`（Claude/Llama/Mistral） |
| 火山引擎 | ✅ 已实现 | `model_providers/volc_backend.py`（字节豆包模型） |
| Copilot | P3 | GitHub Copilot |

### 20.2.2 ProviderProfile 抽象

```python
# model_providers/base.py

class ProviderProfile(ABC):
    name: str
    base_url: str
    supports_streaming: bool = True
    supports_vision: bool = False
    supports_function_calling: bool = True

    @abstractmethod
    def chat_completion(
        self,
        messages: list[dict],
        model: str,
        **kwargs,
    ) -> ChatResponse: ...

    @abstractmethod
    def validate_credentials(self) -> bool: ...

    def estimate_cost(
        self, prompt_tokens: int, completion_tokens: int
    ) -> float:
        """估算成本（美元）。"""
        ...
```

### 20.2.3 DeepSeek Provider 实现

```python
# model_providers/deepseek.py

class DeepSeekProvider(ProviderProfile):
    name = "deepseek"
    base_url = "https://api.deepseek.com"
    supports_vision = False

    def chat_completion(self, messages, model="deepseek-chat", **kwargs):
        # 调用 https://api.deepseek.com/chat/completions
        ...
```

---

## 20.3 web/ 网页搜索提供者（P2）

### 20.3.1 目标

目标支持 13 个搜索提供者（**已扩展到 39 个，含社交/购物/视频/IT/职位/地图/旅行领域** 🚀）：

| Provider | 优先级 | 描述 |
|----------|--------|------|
| Tavily | ✅ 已实现 | AI 优化搜索（`web_providers/tavily.py`） |
| Brave Search | ✅ 已实现 | 隐私搜索（`web_providers/brave.py`） |
| DuckDuckGo | ✅ 已实现 | 免费搜索（`web_providers/duckduckgo.py`） |
| Exa | ✅ 已实现 | 语义搜索（`web_providers/exa.py`） |
| Perplexity | ✅ 已实现 | AI 实时搜索（`web_providers/perplexity.py`） |
| SearXNG | ✅ 已实现 | 自托管聚合（`web_providers/searxng.py`） |
| Firecrawl | ✅ 已实现 | 网页抓取（`web_providers/firecrawl.py`） |
| Google CSE | ✅ 已实现 | Google Programmable Search（`web_providers/google_cse.py`） |
| Serper.dev | ✅ 已实现 | Google SERP 替代 API（`web_providers/serper.py`） |
| Kagi | ✅ 已实现 | 隐私优先搜索（`web_providers/kagi.py`） |
| You.com | ✅ 已实现 | AI 优先 + 摘要（`web_providers/yandex.py`） |
| Parallel | ✅ 已实现 | 多引擎并行搜索（`web_providers/parallel.py`） |
| Keenable | ✅ 已实现 | 知识图谱搜索（`web_providers/keenable.py`） |
| SerpAPI | ✅ 已实现 | 多引擎 30+ 搜索（`web_providers/serpapi.py`） |
| xAI Grok Search | ✅ 已实现 | AI 实时搜索 + 引用（`web_providers/grok_search.py`） |
| Yandex Search | ✅ 已实现 | Yandex 官方搜索 API（`web_providers/yandex_search.py`） |
| Mojeek | ✅ 已实现 | 独立爬虫隐私搜索（`web_providers/mojeek.py`） |
| 360 Search | ✅ 已实现 | 中国 360 搜索（`web_providers/search_360.py`） |
| Google Scholar | ✅ 已实现 | 学术论文搜索（`web_providers/google_scholar.py`） |
| Semantic Scholar | ✅ 已实现 | AI 学术搜索（`web_providers/semantic_scholar.py`） |
| Arxiv | ✅ 已实现 | 学术预印本（`web_providers/arxiv.py`） |
| PubMed | ✅ 已实现 | 生物医学文献（`web_providers/pubmed.py`） |
| Algolia | ✅ 已实现 | 企业级托管搜索（`web_providers/algolia.py`） |
| Baidu | ✅ 已实现 | 中国百度搜索（`web_providers/baidu.py`） |
| Naver | ✅ 已实现 | 韩国 Naver 搜索（`web_providers/naver.py`） |
| Sogou | ✅ 已实现 | 中国搜狗搜索（`web_providers/sogou.py`） |
| Bing Web | ✅ 已实现 | Azure Bing Web Search（`web_providers/bing_web.py`） |
| Yahoo Search | ✅ 已实现 | Yahoo 搜索（`web_providers/yahoo_search.py`） |

### 20.3.2 实现结构

```python
# web_providers/base.py

class SearchProvider(ABC):
    @abstractmethod
    def search(self, query: str, **kwargs) -> SearchResult: ...

class TavilyProvider(SearchProvider):
    name = "tavily"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, max_results: int = 5) -> SearchResult:
        response = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": self.api_key, "query": query, "max_results": max_results},
        )
        return SearchResult(urls=[r["url"] for r in response.json()["results"]])
```

---

## 20.4 image_gen/ 图像生成（P2）

### 20.4.1 目标

目标支持 8 个图像生成提供者（**已实现 8 个**）：

| Provider | 优先级 | 描述 |
|----------|--------|------|
| OpenAI DALL-E | ✅ 已实现 | `image_gen/dalle.py` |
| FAL | ✅ 已实现 | `image_gen/fal.py`（Flux / SDXL / Realistic） |
| Stability AI | ✅ 已实现 | `image_gen/stability.py`（SDXL / SD3） |
| DeepInfra | ✅ 已实现 | `image_gen/deepinfra.py`（FLUX.1-dev/schnell） |
| Krea | ✅ 已实现 | `image_gen/krea.py`（FLUX.1 / IP-Adapter） |
| xAI Grok Image | ✅ 已实现 | `image_gen/grok_image.py` |
| Meta AI | ✅ 已实现 | `image_gen/meta_ai.py` |
| Codex | P3 | 代码可视化 |

### 20.4.2 实现结构

```python
# image_gen/base.py

class ImageGenProvider(ABC):
    @abstractmethod
    def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
        **kwargs,
    ) -> ImageResult: ...

class FalProvider(ImageGenProvider):
    name = "fal"

    def generate(self, prompt: str, model: str = "fal-ai/flux", **kwargs) -> ImageResult:
        # 调用 FAL API
        ...
```

---

## 20.5 video_gen/ 视频生成（P3）

### 20.5.1 目标

支持 3 个视频生成提供者：DeepInfra、FAL、xAI（Grok Video）。

```python
# video_gen/base.py

class VideoGenProvider(ABC):
    @abstractmethod
    def generate_video(
        self,
        prompt: str,
        duration: int = 5,
        **kwargs,
    ) -> VideoResult: ...
```

---

## 20.6 browser/ 浏览器插件（P2）

### 20.6.1 目标

当前 `browser/` 包已实现 BrowserBase 和 Firecrawl 两个后端，另有 `browser_tools.py` 提供 11 个浏览器操作工具。扩展计划：

| Provider | 描述 |
|----------|------|
| browserbase | 云端浏览器（已实现） |
| firecrawl | 网页内容抓取（已实现） |
| playwright | 本地浏览器自动化（规划） |
| browser_use | AI 原生浏览器控制（规划） |

---

## 20.7 observability/ 可观测性（P2）

> ✅ **已实现**：`agent/langfuse_integration.py`

### 20.7.1 Langfuse 集成（已实现）

```python
# agent/langfuse_integration.py

class LangfuseObserver:
    def __init__(self, public_key: str, secret_key: str):
        self.client = Langfuse(public_key=public_key, secret_key=secret_key)

    def trace_llm_call(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
    ) -> None:
        self.client.trace(
            name="llm_call",
            metadata={
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": latency_ms,
            },
        )

    def trace_tool_call(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool,
    ) -> None:
        ...
```
