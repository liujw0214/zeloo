# 13. OAuth 设备码授权

## 13.1 概述

部分 LLM Provider（如 OpenAI Codex、Nous Research）不提供静态 API Key，而是要求通过 **OAuth 2.0 设备授权流**（Device Authorization Grant, RFC 8628）进行身份验证。Zeloo 在 `agent/oauth.py` 中实现了完整的设备码登录流程。

## 13.2 OAuth 2.0 设备授权流

```
用户启动登录
       │
       ▼
Zeloo → Provider 授权端点 ──► 返回 device_code + user_code + verification_uri
       │
       ▼
显示：打开 https://xxx.com 并输入 user_code
       │
       ▼
用户浏览器授权 ──► Provider
       │
       ▼
Zeloo 轮询 Provider token 端点
       │
  授权成功？──否──► 继续轮询（间隔 interval 秒）
       │
      是
       ▼
返回 access_token + refresh_token
       │
       ▼
存储到 ~/.Zeloo/oauth_tokens.json
```

## 13.3 核心 API

### 登录

```python
from agent.oauth import login

token = login("codex")   # 完整设备码流程，自动保存
```

### 获取 Token

```python
from agent.oauth import get_access_token

token = get_access_token("codex")
# 若 token 过期，自动尝试 refresh
# 若无可用 token，返回 None
```

### Token 管理

```python
from agent.oauth import OAuthTokenStore

store = OAuthTokenStore()
store.save(token)               # 保存 token
store.get("codex")             # 获取 token
store.delete("codex")          # 删除 token
store.list_providers()         # 列出已登录的 Provider
```

## 13.4 OAuthToken 数据结构

```python
@dataclass
class OAuthToken:
    provider: str            # "codex"
    access_token: str      # 访问令牌
    refresh_token: str | None  # 刷新令牌
    expires_at: float      # 过期时间戳（Unix）；0=永不过期
    token_type: str        # "Bearer"
    scope: str             # 授权范围

    @property
    def is_expired(self) -> bool:
        # 提前 60 秒刷新，避免竞态
        return time.time() >= (self.expires_at - 60)
```

## 13.5 内置 Provider 配置

```python
_BUILTIN_OAUTH_PROVIDERS = {
    "codex": OAuthProviderConfig(
        name="codex",
        authorization_url="https://auth.openai.com/authorize",
        token_url="https://auth.openai.com/oauth/token",
        client_id="auth0-openai-client",
        scope="openid profile email offline_access",
        audience="https://api.openai.com/v1",
    ),
    "nous": OAuthProviderConfig(
        name="nous",
        authorization_url="https://nousresearch.auth0.com/oauth/device/code",
        token_url="https://nousresearch.auth0.com/oauth/token",
        client_id="nous-cli",
        scope="offline_access",
    ),
}
```

## 13.6 自定义 Provider

在 `config.yaml` 中添加：

```yaml
oauth:
  providers:
    my_provider:
      authorization_url: "https://my-provider.com/oauth/device/code"
      token_url: "https://my-provider.com/oauth/token"
      client_id: "my-client-id"
      scope: "read write"
      audience: "https://api.my-provider.com"
```

配置优先级：`config.yaml` > 内置默认值。

## 13.7 Token 刷新

```python
from agent.oauth import refresh_token, get_oauth_provider_config, OAuthTokenStore

store = OAuthTokenStore()
token = store.get("codex")

config = get_oauth_provider_config("codex")
new_token = refresh_token(config, token)  # 使用 refresh_token 获取新 access_token
store.save(new_token)
```

## 13.8 与 ProviderRouter 集成

OAuth Token 通过 `get_access_token()` 被 ProviderRouter 使用：

```python
# agent/provider_router.py
def resolve(self, provider: str) -> str:
    oauth_token = get_access_token(provider)
    if oauth_token:
        return oauth_token
    return self._credential_pool.get_key(provider)
```

## 13.9 安全特性

- Token 文件权限：Unix 下设置为 `0600`（仅所有者读写），Windows 下跳过
- Token 存储路径：`~/.Zeloo/oauth_tokens.json`
- 自动提前刷新：过期前 60 秒自动刷新，避免请求时 token 失效
- 零第三方依赖：使用标准库 `urllib.request` 完成 HTTP 请求
