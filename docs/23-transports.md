# 23. agent/transports 传输适配器开发计划

> Zeloo 目前通过 ProviderRouter 直接调用 OpenAI SDK。本文档记录需要开发的传输适配器。

## 23.1 模块总览

| 适配器 | 优先级 | 说明 |
|--------|--------|------|
| `anthropic_adapter.py` | P1 | Anthropic Claude API（已部分实现） |
| `bedrock_adapter.py` | P2 | AWS Bedrock |
| `gemini_native_adapter.py` | P2 | Google Gemini 原生协议 |
| `azure_identity_adapter.py` | P2 | Azure OpenAI |
| `codex_runtime.py` | P3 | OpenAI Codex |

## 23.2 Transport 抽象层

所有适配器实现统一接口：

```python
# agent/transports/base.py

from abc import ABC, abstractmethod

class TransportAdapter(ABC):
    name: str

    @abstractmethod
    def chat_completion(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        stream: bool = False,
        **kwargs,
    ) -> Response:
        ...

    @abstractmethod
    def validate_credentials(self) -> bool:
        """验证 API 凭证是否有效。"""

    def supports_feature(self, feature: str) -> bool:
        """查询是否支持某特性（如 vision、streaming）。"""
```

## 23.3 AnthropicAdapter（P1）

### 23.3.1 实现

```python
# agent/transports/anthropic_adapter.py

class AnthropicAdapter(TransportAdapter):
    name = "anthropic"
    BASE_URL = "https://api.anthropic.com"

    def __init__(self, api_key: str, max_retries: int = 3):
        self.api_key = api_key
        self.max_retries = max_retries

    def chat_completion(
        self,
        messages: list[dict],
        model: str = "claude-3-5-sonnet-20241022",
        tools: list[dict] | None = None,
        stream: bool = False,
        **kwargs,
    ) -> Response:
        # Anthropic 使用 beta.customExtensions 传输 tools
        payload = {
            "model": model,
            "messages": self._convert_messages(messages),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.0),
        }
        if tools:
            payload["tools"] = self._convert_tools(tools)
            payload["anthropic_version"] = "vertex-2023-10-30"

        return self._post("/v1/messages", payload, stream=stream)
```

### 23.3.2 Anthropic 消息格式转换

```python
def _convert_messages(self, messages: list[dict]) -> list[dict]:
    """将 OpenAI 格式转换为 Anthropic 格式。"""
    result = []
    for msg in messages:
        if msg["role"] == "system":
            result.append({"role": "user", "content": f"System: {msg['content']}"})
        else:
            result.append({"role": msg["role"], "content": msg["content"]})
    return result
```

---

## 23.4 BedrockAdapter（P2）

### 23.4.1 实现

```python
# agent/transports/bedrock_adapter.py

class BedrockAdapter(TransportAdapter):
    name = "bedrock"

    def __init__(
        self,
        aws_access_key: str,
        aws_secret_key: str,
        aws_region: str = "us-east-1",
    ):
        self.aws_access_key = aws_access_key
        self.aws_secret_key = aws_secret_key
        self.aws_region = aws_region
        self._signer = AWSV4Signer(...)

    def chat_completion(self, messages, model, tools=None, stream=False, **kwargs):
        # Bedrock 使用 AI21/Llama/Cohere 等模型
        # 通过 AWS SigV4 签名认证
        payload = {
            "messages": messages,
            "anthropic_version": "bedrock-2023-05-31",
        }
        return self._signed_post(model, payload, stream)
```

### 23.4.2 支持模型

| 模型族 | 示例 |
|--------|------|
| Anthropic Claude | anthropic.claude-3-5-sonnet |
| Meta Llama | meta.llama3-70b-instruct-v1 |
| AI21 Jurassic | ai21.j2-ultra-v1 |
| Cohere Command | cohere.command-r-plus-v1 |

---

## 23.5 GeminiNativeAdapter（P2）

### 23.5.1 实现

```python
# agent/transports/gemini_native_adapter.py

class GeminiNativeAdapter(TransportAdapter):
    name = "gemini"
    BASE_URL = "https://generativelanguage.googleapis.com"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def chat_completion(
        self,
        messages: list[dict],
        model: str = "gemini-2.0-flash",
        tools: list[dict] | None = None,
        stream: bool = False,
        **kwargs,
    ) -> Response:
        # Gemini 使用 /v1beta/models/{model}:generateContent
        payload = {
            "contents": self._convert_to_gemini_contents(messages),
            "tools": self._convert_tools(tools) if tools else None,
        }
        return self._post(f"/v1beta/models/{model}:generateContent", payload, stream)
```

---

## 23.6 AzureIdentityAdapter（P2）

### 23.6.1 实现

```python
# agent/transports/azure_identity_adapter.py

class AzureIdentityAdapter(TransportAdapter):
    name = "azure"

    def __init__(
        self,
        endpoint: str,  # https://<resource>.openai.azure.com
        api_key: str | None = None,
        azure_ad_token: str | None = None,
        api_version: str = "2024-06-01",
    ):
        self.endpoint = endpoint
        self.api_key = api_key
        self.azure_ad_token = azure_ad_token
        self.api_version = api_version

    def chat_completion(self, messages, model, tools=None, stream=False, **kwargs):
        # Azure OpenAI 使用 /openai/deployments/{deployment}/chat/completions
        url = f"{self.endpoint}/openai/deployments/{model}/chat/completions"
        params = {"api-version": self.api_version}
        ...
```

---

## 23.7 CodexRuntime（P3）

### 23.7.1 实现

```python
# agent/transports/codex_runtime.py

class CodexRuntime(TransportAdapter):
    name = "codex"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def chat_completion(self, messages, model="gpt-4o", tools=None, stream=False, **kwargs):
        # Codex 使用 OpenAI 兼容端点，但有特定 header
        headers = {
            "x-codex-session-token": self._get_session_token(),
        }
        return self._post("/v1/chat/completions", ..., headers=headers)
```

---

## 23.8 TransportFactory

```python
# agent/transports/__init__.py

def get_transport_adapter(provider: str, **kwargs) -> TransportAdapter:
    """工厂函数，按 provider 名称返回对应适配器。"""
    adapters = {
        "openai": OpenAIAdapter,
        "anthropic": AnthropicAdapter,
        "bedrock": BedrockAdapter,
        "gemini": GeminiNativeAdapter,
        "azure": AzureIdentityAdapter,
        "codex": CodexRuntime,
    }
    adapter_cls = adapters.get(provider)
    if not adapter_cls:
        raise ValueError(f"Unknown provider: {provider}")
    return adapter_cls(**kwargs)
```
