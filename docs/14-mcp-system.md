# 14. MCP 系统（Model Context Protocol）

## 14.1 概述

MCP（Model Context Protocol）是一个开放协议，用于在 AI 应用和数据源之间建立双向通信。Zeloo 通过 `mcp/` 包提供 MCP 客户端，支持从 MCP 服务器发现并注册工具到 Agent 的工具注册表。

```
MCP Server（N pino/ Files/数据库/...）
    │  stdio 或 HTTP/SSE
    ▼
mcp/stdio_client.py  ──► StdioMCPClient  ──► tool registry
mcp/http_client.py   ──► HttpMCPClient   ──► tool registry
mcp/manager.py      ──► MCPServerManager ──统一生命周期管理
```

## 14.2 架构

| 文件 | 职责 |
|------|------|
| `mcp/__init__.py` | 包初始化 |
| `mcp/manager.py` | MCPServerManager：启动服务器 + 注册工具 + 生命周期管理 |
| `mcp/stdio_client.py` | StdioMCPClient：子进程 stdio 通信，JSON-RPC 2.0 |
| `mcp/http_client.py` | HttpMCPClient：HTTP/SSE 通信（需 httpx） |
| `mcp/tool_filter.py` | 按配置过滤/选择工具 |

## 14.3 MCPServerManager API

```python
from mcp.manager import MCPServerManager

manager = MCPServerManager()

# 启动所有配置的 MCP 服务器并注册工具
count = manager.load_and_register(config=my_config)

# 关闭所有服务器并注销工具
manager.shutdown()
```

### 14.3.1 配置来源

1. `config.yaml` → `mcp.servers` 列表
2. 环境变量 `zeloo_MCP_SERVERS` → 逗号分隔的 `name=transport://target` 格式

## 14.4 StdioMCPClient

### 14.4.1 构造参数

```python
from mcp.stdio_client import StdioMCPClient

client = StdioMCPClient(
    command="npx",                          # 启动命令
    args=["-y", "@modelcontextprotocol/server-filesystem", "/path"],
    env={"PATH": "/usr/bin"},             # 环境变量
    timeout=30.0,                          # 请求超时
)
```

### 14.4.2 生命周期

```python
client.start()   # 启动子进程
tools = client.list_tools()  # 获取工具列表
result = client.call_tool("tool_name", arguments={})  # 调用工具
client.stop()    # 终止子进程
```

### 14.4.3 协议

- JSON-RPC 2.0 over subprocess stdin/stdout
- 每个请求有唯一递增 ID
- 线程安全（`_lock` 保护）

## 14.5 HttpMCPClient

### 14.5.1 构造参数

```python
from mcp.http_client import HttpMCPClient

client = HttpMCPClient(
    url="https://mcp.example.com/sse",   # MCP 服务器地址
    headers={"Authorization": "Bearer token"},  # 请求头
    timeout=30.0,
)
```

### 14.5.2 传输方式

使用 **Streamable HTTP + SSE**（Server-Sent Events）传输：
- HTTP POST 发送 JSON-RPC 请求
- GET 请求接收 SSE 事件流（用于 notifications）

## 14.6 配置示例

### 14.6.1 config.yaml 格式

```yaml
mcp:
  servers:
    - name: filesystem
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
    - name: memory
      transport: http
      url: https://mcp.example.com/sse
      headers:
        Authorization: "Bearer ${MCP_TOKEN}"
```

### 14.6.2 环境变量格式

```bash
export zeloo_MCP_SERVERS="filesystem=npx:-y:@modelcontextprotocol/server-filesystem:/home/user,memory=http://localhost:8080/sse"
```

## 14.7 工具注册

MCPServerManager 启动服务器后，调用服务器的 `tools/list` 端点获取工具清单，将每个工具包装为 Zeloo 的 `Tool` 实例并注册到全局注册表。注册后，Agent 可以像调用内置工具一样调用 MCP 工具。

## 14.8 与 mcp_serve.py 的关系

| 组件 | 方向 | 说明 |
|------|------|------|
| `mcp/manager.py` | MCP Client（消费方） | 启动 MCP 服务器并注册其工具 |
| `mcp_serve.py` | MCP Server（提供方） | 将 Zeloo 暴露为 MCP 服务器 |

两者互为补充：Manager 负责引入外部 MCP 工具，`mcp_serve.py` 负责将 Zeloo 自身暴露为 MCP 服务。
