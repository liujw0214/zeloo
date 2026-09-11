# mcp/AGENTS.md

## 本包职责

Model Context Protocol (MCP) 集成：负责 MCP Server/Client 实现与第三方 MCP 服务器桥接。

## 核心模块

- `server.py`：MCP Server 实现（stdio/sse 传输）
- `client.py`：MCP Client 实现
- `registry.py`：MCP 服务器注册表
- `optional_mcps/`：16 个第三方 MCP 服务器（GitHub/Notion/Slack 等）

## 注意事项

- MCP 通信必须使用标准 JSON-RPC 2.0 协议
- 所有 MCP 服务器必须经过授权检查（authz_mixin）
- 敏感数据不得通过 MCP 通道传输
- Client 连接必须支持自动重连
