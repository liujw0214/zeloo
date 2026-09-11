# 07. 多平台网关与终端后端

## 7.1 多平台消息网关

Zeloo 的消息网关是一个**单进程多平台**的统一接入层：

```
┌─────────────────────────────────────────────────┐
│                    网关 (Gateway)                 │
│                                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Telegram │  │ 飞书     │  │ Slack    │  ...  │
│  │ Adapter  │  │ Adapter  │  │ Adapter  │       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│       │             │             │              │
│       └─────────────┼─────────────┘              │
│                     ▼                            │
│            ┌──────────────┐                      │
│            │ Session Mgr  │                      │
│            └──────┬───────┘                      │
│                   ▼                              │
│            ┌──────────────┐                      │
│            │ AIAgent Core │                      │
│            └──────────────┘                      │
│                   │                              │
│            ┌──────┴───────┐                      │
│            │ Skill Router │                      │
│            └──────────────┘                      │
└─────────────────────┬────────────────────────────┘
                      │
          ┌───────────┴──────────────┐
          │                          │
    ┌─────┴─────┐              ┌─────┴──────┐
    │  CLI/TUI  │              │  Tool Exec │
    └───────────┘              └────────────┘
```

### 7.1.2 支持平台

支持 18 个平台适配器 + CLI/TUI/API 3 个内置终端，共 21 个消息接入点：

| 平台 | 接入方式 | 消息类型 |
|------|----------|----------|
| CLI | 本地 PTY | 文本 |
| TUI | 终端 UI | 文本 + 富文本 |
| Telegram | Bot API | 文本/图片/语音/文件 |
| Discord | Bot API | 文本/图片/语音频道 |
| Slack | Bot API | 文本/图片 |
| WhatsApp | Business API | 文本/图片 |
| Signal | Bot API | 文本 |
| 飞书 (Feishu) | Bot API | 文本/卡片/文件 |
| 钉钉 (DingTalk) | Bot API | 文本/卡片 |
| 企业微信 (WeCom) | Bot API | 文本/卡片 |
| Microsoft Teams | Bot API | 文本/卡片 |
| Matrix | Client-Server API | 文本 |
| Google Chat | Bot API | 文本/卡片 |
| Email | IMAP/SMTP | 文本/附件 |
| SMS | SMS Gateway | 文本 |
| QQ Bot | Bot API | 文本/图片 |
| IRC | IRC Protocol | 文本 |
| LINE | Messaging API | 文本/图片 |
| Mattermost | Bot API | 文本 |
| Home Assistant | Webhook | 文本/事件 |
| API | HTTP | 文本 (OpenAI 兼容) |

所有平台由**单个网关进程**统一管理，通过平台适配器隔离 SDK 差异。

### 7.1.3 配置格式

```yaml
# config.yaml
gateway:
  platforms:
    telegram:
      enabled: true
      token: ${TELEGRAM_BOT_TOKEN}
      allowed_users: [123456789]  # 白名单
      extra:
        rich_messages: true
    discord:
      enabled: true
      token: ${DISCORD_BOT_TOKEN}
      guild_id: 123456789
```

### 7.1.4 平台适配器开发规范

新平台适配器需实现以下接口：

```python
class PlatformAdapter(ABC):
    @abstractmethod
    def start(self, handler: Callable[[str, str, str], str]) -> None:
        """启动平台适配器，注册消息回调"""
        pass

    @abstractmethod
    def stop(self) -> None:
        """停止平台适配器，释放资源"""
        pass

    @abstractmethod
    def send_message(self, user_id: str, text: str) -> None:
        """发送消息到指定用户"""
        pass

    @abstractmethod
    def parse_incoming(self, body: bytes, headers: dict) -> tuple[str, str] | None:
        """解析传入消息，返回 (user_id, message_text) 或 None"""
        pass
```

### 7.1.5 会话管理

网关内置 Session Manager，负责：

1. **会话生命周期**：用户发起对话 → 创建会话 → 路由到 AIAgent → 返回响应
2. **会话隔离**：不同平台/用户的消息在独立会话中处理
3. **空闲回收**：可配置空闲超时自动释放会话资源

### 7.1.6 OpenAI 兼容 API

网关提供 OpenAI 兼容的 `/v1/chat/completions` 接口，可被第三方应用直接调用作为 AI 对话后端。

#### APIServer 类

`gateway/api_server.py` 的 `APIServer` 是独立的 OpenAI 兼容服务器，基于 stdlib `ThreadingHTTPServer`：

```python
from gateway.api_server import APIServer

server = APIServer(
    agent_factory=my_agent_factory,
    host="0.0.0.0",
    port=8080,
    model_name="Zeloo",
    rate_limit_capacity=60,   # 每分钟最大请求数
    rate_limit_rate=1.0,
    auth_tokens=["sk-secret-key"],  # Bearer token 白名单
)
server.start()
```

#### 端点列表

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| `GET` | `/health` | 无 | 健康检查 |
| `GET` | `/v1/models` | Bearer token | 列出可用模型 |
| `GET` | `/v1/skills` | Bearer token | 列出可用技能 |
| `POST` | `/v1/chat/completions` | Bearer token | 对话补全 |
| `POST` | `/v1/mcp/reload` | Bearer token | 热重载 MCP 工具 |

#### Chat Completions 请求

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer sk-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Zeloo",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

#### 请求校验

- `messages[-1].role` 必须为 `user`
- 输入经过 `sanitize_input()` 扫描威胁模式
- 输出经过 `validate_output()` 清洗
- 每 IP 限流：`rate_limit_capacity` / `rate_limit_rate`

#### 响应格式

```json
{
  "id": "chatcmpl-20260907_120000",
  "object": "chat.completion",
  "created": 0,
  "model": "Zeloo",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "Hello! How can I help?"},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
}
```

## 7.2 终端后端

### 7.2.1 架构概览

所有终端后端实现 `terminal.base.TerminalBackend` 接口，统一返回 `CommandResult`：

```python
@dataclass
class CommandResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.returncode == 0
```

```
terminal/
├── base.py           # CommandResult + TerminalBackend 协议
├── local.py          # LocalBackend（subprocess）
├── docker.py         # DockerBackend（容器隔离）
├── ssh.py            # SSHBackend（Paramiko）
├── modal.py          # ModalBackend（Modal Sandbox API）
├── daytona.py        # DaytonaBackend（REST API）
├── vercel_sandbox.py # VercelSandboxBackend（REST API）
└── singularity.py   # SingularityBackend
```

### 7.2.2 LocalBackend

在本地主机通过 `subprocess.run()` 直接执行命令：

```python
from terminal.local import LocalBackend

backend = LocalBackend()
result = backend.execute("git status", timeout=30)
print(result.stdout, result.stderr, result.returncode)
```

- 依赖：stdlib only
- 超时：subprocess 层面硬超时

### 7.2.3 DockerBackend

在 Docker 容器中执行命令，提供完全隔离的执行环境：

```python
from terminal.docker import DockerBackend

backend = DockerBackend(
    image="python:3.12-slim",
    container_name="Zeloo-sandbox",
    volumes={"/host/path": "/container/path"},
    working_dir="/workspace",
)
result = backend.execute("python test.py", timeout=60)
backend.close()
```

- 依赖：`docker` Python 包
- 容器复用：同名容器优先复用，避免每次创建开销
- 隔离级别：文件系统、网络、进程完全隔离

### 7.2.4 SSHBackend

通过 SSH 在远程服务器执行命令：

```python
from terminal.ssh import SSHBackend

backend = SSHBackend(
    host="example.com",
    user="root",
    port=22,
    key_file="~/.ssh/id_rsa",
    password=None,
    connect_timeout=10,
)
result = backend.execute("uptime", timeout=30)
```

- 依赖：`paramiko`
- 认证：支持密钥文件或密码
- 超时：连接超时 + 命令执行超时

### 7.2.5 ModalBackend

通过 Modal 平台的无服务器沙箱执行命令，按实际执行时间计费：

```python
from terminal.modal import ModalBackend

backend = ModalBackend(
    image="python:3.12-slim",
    cpu=2.0,
    memory=1024,
    gpu="T4",      # 可选：T4/A10G/A100
)
result = backend.execute("python train.py --epochs 10", timeout=300)
```

- 依赖：`modal` Python 包 + Modal API Token
- GPU 支持：可指定 T4/A10G/A100
- 适用：机器学习训练、大模型推理

### 7.2.6 DaytonaBackend

通过 Daytona Dev Environment 的 REST API 创建工作区并执行命令：

```python
from terminal.daytona import DaytonaBackend

backend = DaytonaBackend(
    api_url="https://app.daytona.io/api",
    api_key="${DAYTONA_API_KEY}",
    image="ubuntu:22.04",
)
result = backend.execute("make build", timeout=120)
```

- 依赖：stdlib only（urllib）
- 适用：云端开发环境管理

### 7.2.7 VercelSandboxBackend

通过 Vercel 沙箱 API 执行临时命令：

```python
from terminal.vercel_sandbox import VercelSandboxBackend

backend = VercelSandboxBackend(
    api_token="${VERCEL_API_TOKEN}",
    team_id="${VERCEL_TEAM_ID}",
)
result = backend.execute("npm run build", timeout=60)
```

- 依赖：stdlib only（urllib）
- 适用：Serverless 临时构建任务

### 7.2.8 SingularityBackend

通过 Singularity 容器在 HPC 环境执行命令：

```python
from terminal.singularity import SingularityBackend

backend = SingularityBackend(
    image="python-3.12.sif",
    bind_paths=["/data:/data"],
)
result = backend.execute("python job.py", timeout=300)
```

- 适用：高性能计算集群、科研环境

### 7.2.9 后端对比

| 后端 | 隔离 | GPU | 计费 | 依赖 | 适用场景 |
|------|------|-----|------|------|----------|
| local | 无 | 无 | 免费 | stdlib | 开发调试 |
| docker | 容器级 | 无 | 按资源 | docker | 轻量隔离 |
| ssh | 无（网络） | 可用 | 按主机 | paramiko | 远程服务器 |
| modal | 沙箱 | T4/A100 | 按执行时间 | modal | ML 训练/推理 |
| daytona | 沙箱 | 可用 | 按订阅 | stdlib | 云端开发 |
| vercel | 沙箱 | 无 | 按执行时间 | stdlib | Serverless 构建 |
| singularity | 容器级 | 可用 | 按集群 | singularity | HPC 科研 |

### 7.2.10 配置

```yaml
terminal:
  backend: docker
  timeout: 30
  working_dir: ~/workspace
```

### 7.2.11 终端命令白名单

出于安全考虑，终端执行支持命令白名单：

```yaml
terminal:
  allowed_commands:
    - git
    - npm
    - python
    - docker
  blocked_commands:
    - rm -rf /
    - format
```

## 7.3 ACP 适配器（IDE 集成）

### 7.3.1 概述

`acp_adapter.py` 实现了 ACP（Agent Client Protocol），允许从 IDE（VS Code、Cursor、Zed 等）控制 Zeloo。通过 stdio JSON-RPC 通信，将 IDE 的消息路由到 AIAgent 并返回结果。

### 7.3.2 支持的消息类型

| 方向 | 消息类型 | 说明 |
|------|----------|------|
| client→agent | `initialize` | 协议握手 |
| agent→client | `initialized` | 握手确认 |
| client→agent | `session/new` | 创建新会话 |
| client→agent | `message` | 用户消息 |
| agent→client | `message/update` | 流式响应（增量） |
| agent→client | `message/end` | 最终响应 |
| agent→client | `session/end` | 会话结束 |

### 7.3.3 使用方式

```python
from acp_adapter import ACPAdapter

adapter = ACPAdapter()
adapter.run_stdio()  # 阻塞，运行 stdio JSON-RPC 服务器
```

### 7.3.4 与 Gateway 的区别

| 维度 | ACP 适配器 | 消息网关 |
|------|------------|----------|
| 协议 | ACP (JSON-RPC) | 各平台原生协议 |
| 用途 | IDE 集成 | 多消息平台 |
| 传输 | stdio | HTTP/WebSocket/长轮询 |
| 会话 | 按 `session/new` 创建 | 按平台会话 ID |
