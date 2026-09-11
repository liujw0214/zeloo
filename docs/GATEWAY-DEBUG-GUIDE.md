# Zeloo Gateway 服务调试环境配置指南

> 本指南帮助你在 VS Code 中配置 Zeloo Gateway 的完整调试环境，支持断点调试、API 测试、平台适配器调试等。

---

## 目录

1. [Gateway 架构概览](#1-gateway-架构概览)
2. [创建调试配置](#2-创建调试配置)
3. [API 测试脚本](#3-api-测试脚本)
4. [平台适配器调试](#4-平台适配器调试)
5. [常见问题排查](#5-常见问题排查)

---

## 1. Gateway 架构概览

### 1.1 组件关系

```
gateway/run.py (main)
    └── Gateway (主控制器)
        ├── SessionManager (会话管理)
        ├── APIServer (OpenAI 兼容 API)
        │   ├── /health (健康检查)
        │   ├── /v1/models (模型列表)
        │   ├── /v1/chat/completions (聊天补全)
        │   └── /v1/skills (Skills 列表)
        └── Platform Adapters (平台适配器)
            ├── Telegram
            ├── Discord
            ├── Slack
            ├── 飞书
            ├── 钉钉
            ├── 企业微信
            └── ... (20+ 平台)
```

### 1.2 端口配置

| 组件 | 默认端口 | 说明 |
|---|---|---|
| **Gateway API** | `9113` | OpenAI 兼容 REST API |
| **Gateway WebSocket** | `9113` | WebSocket 实时通信 |
| **Web Dashboard** | `3000` | Web UI 界面 |
| **Metrics** | `9090` | Prometheus 指标 |

---

## 2. 创建调试配置

在 `.vscode/launch.json` 中添加以下配置：

```json
{
  "version": "0.2.0",
  "configurations": [

    // ============================================================
    // Gateway: 仅 API Server
    // ============================================================
    {
      "name": "Gateway: API Only",
      "type": "debugpy",
      "request": "launch",
      "module": "gateway.api_server",
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1",
        "OPENAI_API_KEY": "${env:OPENAI_API_KEY}"
      },
      "console": "integratedTerminal",
      "justMyCode": true
    },

    // ============================================================
    // Gateway: 完整服务（API + 平台适配器）
    // ============================================================
    {
      "name": "Gateway: Full Service",
      "type": "debugpy",
      "request": "launch",
      "module": "gateway.run",
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1",
        "OPENAI_API_KEY": "${env:OPENAI_API_KEY}",
        "ANTHROPIC_API_KEY": "${env:ANTHROPIC_API_KEY}"
      },
      "console": "integratedTerminal",
      "justMyCode": true
    },

    // ============================================================
    // Gateway: Telegram 适配器
    // ============================================================
    {
      "name": "Gateway: Telegram",
      "type": "debugpy",
      "request": "launch",
      "module": "gateway.run",
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1",
        "TELEGRAM_BOT_TOKEN": "${env:TELEGRAM_BOT_TOKEN}",
        "OPENAI_API_KEY": "${env:OPENAI_API_KEY}"
      },
      "console": "integratedTerminal",
      "justMyCode": true
    },

    // ============================================================
    // Gateway: Discord 适配器
    // ============================================================
    {
      "name": "Gateway: Discord",
      "type": "debugpy",
      "request": "launch",
      "module": "gateway.run",
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1",
        "DISCORD_BOT_TOKEN": "${env:DISCORD_BOT_TOKEN}",
        "OPENAI_API_KEY": "${env:OPENAI_API_KEY}"
      },
      "console": "integratedTerminal",
      "justMyCode": true
    },

    // ============================================================
    // Gateway: 飞书适配器
    // ============================================================
    {
      "name": "Gateway: 飞书 (Feishu)",
      "type": "debugpy",
      "request": "launch",
      "module": "gateway.run",
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1",
        "FEISHU_APP_ID": "${env:FEISHU_APP_ID}",
        "FEISHU_APP_SECRET": "${env:FEISHU_APP_SECRET}",
        "OPENAI_API_KEY": "${env:OPENAI_API_KEY}"
      },
      "console": "integratedTerminal",
      "justMyCode": true
    },

    // ============================================================
    // Gateway: Slack 适配器
    // ============================================================
    {
      "name": "Gateway: Slack",
      "type": "debugpy",
      "request": "launch",
      "module": "gateway.run",
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1",
        "SLACK_BOT_TOKEN": "${env:SLACK_BOT_TOKEN}",
        "SLACK_SIGNING_SECRET": "${env:SLACK_SIGNING_SECRET}",
        "OPENAI_API_KEY": "${env:OPENAI_API_KEY}"
      },
      "console": "integratedTerminal",
      "justMyCode": true
    },

    // ============================================================
    // Gateway: 健康检查（curl 友好）
    // ============================================================
    {
      "name": "Gateway: Health Check",
      "type": "debugpy",
      "request": "launch",
      "module": "gateway.api_server",
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_DISABLE_UPDATE_CHECK": "1"
      },
      "console": "integratedTerminal",
      "justMyCode": true,
      "postDebugTask": "gateway-health-check"
    },

    // ============================================================
    // Gateway: 调试 WebSocket
    // ============================================================
    {
      "name": "Gateway: WebSocket Debug",
      "type": "debugpy",
      "request": "launch",
      "module": "gateway.api_server",
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1",
        "OPENAI_API_KEY": "${env:OPENAI_API_KEY}"
      },
      "console": "integratedTerminal",
      "justMyCode": true
    },

    // ============================================================
    // Gateway: Session 管理器
    // ============================================================
    {
      "name": "Gateway: Session Manager",
      "type": "debugpy",
      "request": "launch",
      "module": "gateway.session",
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1"
      },
      "console": "integratedTerminal",
      "justMyCode": true
    },

    // ============================================================
    // Gateway: Metrics 导出
    // ============================================================
    {
      "name": "Gateway: Metrics",
      "type": "debugpy",
      "request": "launch",
      "module": "gateway.api_server",
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "INFO",
        "ZELOO_DISABLE_UPDATE_CHECK": "1"
      },
      "console": "integratedTerminal",
      "justMyCode": true
    },

    // ============================================================
    // Gateway: SSE 流式响应
    // ============================================================
    {
      "name": "Gateway: SSE Streaming",
      "type": "debugpy",
      "request": "launch",
      "module": "gateway.api_server",
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1",
        "OPENAI_API_KEY": "${env:OPENAI_API_KEY}"
      },
      "console": "integratedTerminal",
      "justMyCode": true
    },

    // ============================================================
    // Gateway: Middleware 链
    // ============================================================
    {
      "name": "Gateway: Middleware",
      "type": "debugpy",
      "request": "launch",
      "module": "gateway.middleware",
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1"
      },
      "console": "integratedTerminal",
      "justMyCode": true
    },

    // ============================================================
    // Gateway: 指定端口
    // ============================================================
    {
      "name": "Gateway: Custom Port (8080)",
      "type": "debugpy",
      "request": "launch",
      "module": "gateway.api_server",
      "cwd": "${workspaceFolder}",
      "env": {
        "ZELOO_ENV": "development",
        "ZELOO_HOME": "${workspaceFolder}/.zeloo-test",
        "ZELOO_LOG_LEVEL": "DEBUG",
        "ZELOO_DISABLE_UPDATE_CHECK": "1",
        "OPENAI_API_KEY": "${env:OPENAI_API_KEY}"
      },
      "console": "integratedTerminal",
      "justMyCode": true,
      "env": {
        "PORT": "8080"
      }
    }

  ],
  "compounds": [
    {
      "name": "Gateway: API + WebSocket",
      "configurations": [
        "Gateway: API Only",
        "Gateway: WebSocket Debug"
      ],
      "stopAll": true
    },
    {
      "name": "Gateway: Full + Telegram",
      "configurations": [
        "Gateway: Full Service",
        "Gateway: Telegram"
      ],
      "stopAll": true
    }
  ]
}
```

---

## 3. API 测试脚本

创建 `scripts/test_gateway_api.py` 用于调试：

```python
#!/usr/bin/env python3
"""Gateway API 调试测试脚本"""

import json
import sys
import time
import httpx
import asyncio

BASE_URL = "http://localhost:9113"
HEADERS = {
    "Authorization": f"Bearer {sys.argv[1] if len(sys.argv) > 1 else 'test-api-key'}",
    "Content-Type": "application/json",
}


def test_health():
    """测试健康检查端点"""
    print("\n[GET] /health")
    resp = httpx.get(f"{BASE_URL}/health", timeout=5)
    print(f"Status: {resp.status_code}")
    print(f"Body: {resp.json()}")
    return resp.status_code == 200


def test_models():
    """测试模型列表端点"""
    print("\n[GET] /v1/models")
    resp = httpx.get(f"{BASE_URL}/v1/models", headers=HEADERS, timeout=5)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        models = data.get("data", [])
        print(f"Models count: {len(models)}")
        for m in models[:3]:
            print(f"  - {m.get('id')}")
    return resp.status_code == 200


def test_skills():
    """测试 Skills 列表端点"""
    print("\n[GET] /v1/skills")
    resp = httpx.get(f"{BASE_URL}/v1/skills", headers=HEADERS, timeout=5)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        skills = data.get("data", [])
        print(f"Skills count: {len(skills)}")
    return resp.status_code == 200


def test_chat_completions():
    """测试聊天补全端点"""
    print("\n[POST] /v1/chat/completions")

    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is 2+2?"}
        ],
        "max_tokens": 100,
        "temperature": 0.7
    }

    resp = httpx.post(
        f"{BASE_URL}/v1/chat/completions",
        headers=HEADERS,
        json=payload,
        timeout=30
    )

    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"Response: {content[:200]}")
    else:
        print(f"Error: {resp.text[:200]}")

    return resp.status_code == 200


async def test_chat_streaming():
    """测试流式聊天补全"""
    print("\n[POST] /v1/chat/completions (streaming)")

    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "Count from 1 to 5"}
        ],
        "stream": True,
        "max_tokens": 50
    }

    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            f"{BASE_URL}/v1/chat/completions",
            headers=HEADERS,
            json=payload
        ) as resp:
            print(f"Status: {resp.status_code}")
            full_content = ""

            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            full_content += delta
                    except json.JSONDecodeError:
                        pass

            print(f"Streaming complete: {len(full_content)} chars")


def test_with_tools():
    """测试 function calling / tools"""
    print("\n[POST] /v1/chat/completions (with tools)")

    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "What is the weather in Beijing?"}
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a city",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"}
                        },
                        "required": ["city"]
                    }
                }
            }
        ]
    }

    resp = httpx.post(
        f"{BASE_URL}/v1/chat/completions",
        headers=HEADERS,
        json=payload,
        timeout=30
    )

    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        choice = data.get("choices", [{}])[0]
        tool_calls = choice.get("message", {}).get("tool_calls", [])
        if tool_calls:
            print(f"Tool calls: {len(tool_calls)}")
            for tc in tool_calls:
                print(f"  - {tc.get('function', {}).get('name')}")
    return resp.status_code == 200


def test_auth_fail():
    """测试认证失败"""
    print("\n[GET] /v1/models (no auth)")
    resp = httpx.get(f"{BASE_URL}/v1/models", timeout=5)
    print(f"Status: {resp.status_code} (should be 401)")
    return resp.status_code == 401


def test_rate_limit():
    """测试速率限制"""
    print("\n[POST] /v1/chat/completions (rate limit test)")

    for i in range(5):
        payload = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 10
        }
        resp = httpx.post(
            f"{BASE_URL}/v1/chat/completions",
            headers=HEADERS,
            json=payload,
            timeout=10
        )
        print(f"  Request {i+1}: {resp.status_code}")
        time.sleep(0.2)


def main():
    print("=" * 60)
    print("Zeloo Gateway API 调试测试")
    print(f"Base URL: {BASE_URL}")
    print("=" * 60)

    results = {}

    # 基础测试
    results["health"] = test_health()
    results["models"] = test_models()
    results["skills"] = test_skills()
    results["chat"] = test_chat_completions()
    results["tools"] = test_with_tools()
    results["auth_fail"] = test_auth_fail()

    # 流式测试（异步）
    asyncio.run(test_chat_streaming())

    # 速率限制测试
    test_rate_limit()

    # 总结
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {name:20s}: {status}")

    passed = sum(results.values())
    total = len(results)
    print(f"\n通过率: {passed}/{total} ({100*passed//total}%)")


if __name__ == "__main__":
    main()
```

---

## 4. 平台适配器调试

### 4.1 Telegram 调试

1. **创建 Bot**：
   - 在 Telegram 中搜索 `@BotFather`
   - 发送 `/newbot`
   - 获取 Bot Token

2. **配置环境变量**：
   ```json
   {
     "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF..."
   }
   ```

3. **创建测试配置** `config.yaml`：
   ```yaml
   gateway:
     api:
       enabled: true
       host: 0.0.0.0
       port: 9113
       rate_limit_capacity: 60
       rate_limit_rate: 1.0

   platforms:
     telegram:
       enabled: true
       token: ${TELEGRAM_BOT_TOKEN}
       allowed_users: []
   ```

4. **启动调试**：
   - 选择 `Gateway: Telegram` 配置
   - F5 开始调试
   - 在 Telegram 中给 Bot 发消息测试

### 4.2 飞书调试

1. **创建飞书应用**：
   - 登录 [飞书开放平台](https://open.feishu.cn/)
   - 创建企业自建应用
   - 获取 App ID 和 App Secret

2. **配置环境变量**：
   ```json
   {
     "FEISHU_APP_ID": "cli_xxx",
     "FEISHU_APP_SECRET": "xxx"
   }
   ```

3. **启动调试**：
   - 选择 `Gateway: 飞书 (Feishu)` 配置
   - F5 开始调试

### 4.3 Webhook 本地调试（ngrok）

对于需要公网 Webhook 的平台（飞书、钉钉等），使用 ngrok：

```bash
# 1. 安装 ngrok
# https://ngrok.com/download

# 2. 启动 ngrok 转发
ngrok http 9113

# 3. 获取公网地址
# Forwarding: https://abc123.ngrok.io -> http://localhost:9113

# 4. 在平台配置 Webhook URL
# 飞书: https://abc123.ngrok.io/feishu/webhook
# 钉钉: https://abc123.ngrok.io/dingtalk/webhook
```

---

## 5. 常见问题排查

### Q1: 端口被占用

```bash
# Windows
netstat -ano | findstr :9113
taskkill /PID <PID> /F

# Linux/macOS
lsof -i :9113
kill -9 <PID>
```

### Q2: 认证失败 401

检查：
1. 环境变量 `OPENAI_API_KEY` 是否设置
2. 请求头 `Authorization: Bearer <key>` 格式是否正确
3. Gateway 配置中的 `auth_tokens` 是否包含该 key

### Q3: CORS 跨域错误

```python
# 在调试时临时禁用 CORS
# gateway/api_server.py 中添加：
headers["Access-Control-Allow-Origin"] = "*"
```

### Q4: WebSocket 连接失败

```python
# 检查 WebSocket 端点
ws://localhost:9113/ws  # 正确
ws://localhost:9113/api/ws  # 错误
```

### Q5: 流式响应卡住

检查：
1. LLM API Key 额度是否充足
2. 网络是否稳定
3. 超时设置是否合理（默认 60s）

### Q6: 平台适配器无法启动

```python
# 检查依赖是否安装
import telegram
import discord
import slack
# 如果 ImportError，运行：
# pip install python-telegram-bot discord.py slack-sdk
```

---

## 6. 调试工作流

### 6.1 API 端点调试

```
1. 启动 Gateway (F5)
2. 打开终端
3. 运行测试脚本：
   python scripts/test_gateway_api.py <YOUR_API_KEY>

4. 或手动 curl 测试：
   curl http://localhost:9113/health

   curl -X POST http://localhost:9113/v1/chat/completions \
     -H "Authorization: Bearer <KEY>" \
     -H "Content-Type: application/json" \
     -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}'
```

### 6.2 WebSocket 调试

```python
# scripts/test_ws.py
import websockets
import asyncio
import json

async def test_ws():
    uri = "ws://localhost:9113/ws?token=<YOUR_KEY>"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "type": "chat",
            "content": "Hello!"
        }))
        async for msg in ws:
            print(json.loads(msg))

asyncio.run(test_ws())
```

### 6.3 平台 Webhook 调试

```
1. 启动 ngrok：ngrok http 9113
2. 复制公网地址
3. 配置平台 Webhook URL
4. 触发事件测试
5. 在 VS Code 中设置断点
6. 观察请求流程
```

---

## 7. 环境变量速查

| 变量 | 用途 | 示例 |
|---|---|---|
| `ZELOO_ENV` | 环境模式 | `development` |
| `ZELOO_HOME` | 数据目录 | `./.zeloo-test` |
| `ZELOO_LOG_LEVEL` | 日志级别 | `DEBUG` |
| `ZELOO_DISABLE_UPDATE_CHECK` | 禁用版本检查 | `1` |
| `OPENAI_API_KEY` | OpenAI API Key | `sk-...` |
| `ANTHROPIC_API_KEY` | Anthropic API Key | `sk-ant-...` |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | `123:abc` |
| `DISCORD_BOT_TOKEN` | Discord Bot Token | `MTI...` |
| `SLACK_BOT_TOKEN` | Slack Bot Token | `xoxb-...` |
| `FEISHU_APP_ID` | 飞书 App ID | `cli_xxx` |
| `FEISHU_APP_SECRET` | 飞书 App Secret | `xxx` |

---

## 8. 快速启动命令

```bash
# 1. 启动 API Server（默认端口 9113）
python -m gateway.api_server

# 2. 启动完整 Gateway
python -m gateway.run

# 3. 启动并指定端口
python -m gateway.run --port 8080

# 4. 测试健康检查
curl http://localhost:9113/health

# 5. 测试聊天
curl -X POST http://localhost:9113/v1/chat/completions \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}'
```
