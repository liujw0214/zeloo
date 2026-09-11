"""MCP (Model Context Protocol) 客户端：连接 mcp_servers 配置的服务器。

提供 MCPServerTask 和 MCPClient 两个核心类，用于管理 MCP 服务器连接和工具调用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
PROTOCOL_VERSION = "2024-11-05"


class MCPServerTask:
    """一个 MCP 服务器连接。

    封装与单个 MCP 服务器的通信，支持 stdio 和 HTTP 两种传输方式。
    """

    def __init__(
        self,
        name: str,
        config: dict[str, Any],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._name = name
        self._config = config
        self._loop = loop
        self._transport = config.get("transport", "stdio")
        self._timeout = float(config.get("timeout", DEFAULT_TIMEOUT))
        self._running = False
        self._start_time: float | None = None
        self._tools: list[dict[str, Any]] = []
        self._request_id = 0
        self._lock = threading.Lock()

        self._proc: subprocess.Popen | None = None
        self._client = None

        if self._transport == "stdio":
            self._command = config.get("command", "")
            self._args = list(config.get("args", []))
            self._env = config.get("env")
            self._cwd = config.get("cwd")

    async def start(self) -> None:
        """启动 MCP 服务器并初始化会话。"""
        if self._running:
            logger.debug("MCP 服务器已在运行: %s", self._name)
            return

        if self._transport == "stdio":
            await self._start_stdio()
        elif self._transport == "http":
            await self._start_http()

        self._running = True
        self._start_time = time.time()
        logger.info("MCP 服务器已启动: %s (%s)", self._name, self._transport)

    async def stop(self) -> None:
        """停止 MCP 服务器。"""
        if not self._running:
            return

        if self._transport == "stdio" and self._proc is not None:
            try:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait()
            except Exception:
                logger.exception("停止 MCP 服务器时出错: %s", self._name)

        elif self._transport == "http" and self._client is not None:
            try:
                self._client.close()
            except Exception:
                logger.exception("关闭 HTTP 客户端时出错: %s", self._name)

        self._running = False
        self._start_time = None
        logger.info("MCP 服务器已停止: %s", self._name)

    async def _start_stdio(self) -> None:
        """通过 stdio 启动 MCP 服务器。"""
        import os

        cmd = [self._command, *self._args]
        env = dict(os.environ) if self._env is None else {**os.environ, **self._env}

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,
            cwd=self._cwd,
        )

        self._send_request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": "zeloo-mcp-client",
                "version": "1.0.0",
            },
        })
        self._send_notification("notifications/initialized")

        self._tools = self._send_request("tools/list", {}).get("result", {}).get("tools", [])

    async def _start_http(self) -> None:
        """通过 HTTP 启动 MCP 服务器连接。"""
        import httpx

        url = self._config.get("url", "")
        headers = self._config.get("headers", {})

        self._client = httpx.Client(timeout=self._timeout, headers=headers)

        self._http_request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": "zeloo-mcp-client",
                "version": "1.0.0",
            },
        })
        self._http_notification("notifications/initialized")

        resp = self._http_request("tools/list", {})
        self._tools = resp.get("result", {}).get("tools", [])

    def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """通过 stdio 发送 JSON-RPC 请求。"""
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError(f"MCP 服务器未运行: {self._name}")

        with self._lock:
            self._request_id += 1
            req_id = self._request_id

        message = json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        })

        self._proc.stdin.write(message + "\n")
        self._proc.stdin.flush()

        return self._read_response(req_id)

    def _send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """通过 stdio 发送 JSON-RPC 通知。"""
        if self._proc is None or self._proc.stdin is None:
            return

        message = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        })
        self._proc.stdin.write(message + "\n")
        self._proc.stdin.flush()

    def _read_response(self, req_id: int) -> dict[str, Any]:
        """读取 stdio 响应。"""
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError(f"MCP 服务器未运行: {self._name}")

        deadline = time.time() + self._timeout
        while time.time() < deadline:
            line = self._proc.stdout.readline()
            if not line:
                if self._proc.poll() is not None:
                    stderr = self._proc.stderr.read() if self._proc.stderr else ""
                    raise RuntimeError(f"MCP 服务器意外退出: {stderr}")
                continue

            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            if msg.get("id") == req_id:
                if "error" in msg:
                    raise RuntimeError(f"MCP 错误: {msg['error']}")
                return msg

        raise TimeoutError(f"MCP 响应超时: 请求 {req_id}")

    def _http_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """通过 HTTP 发送 JSON-RPC 请求。"""
        if self._client is None:
            raise RuntimeError(f"MCP HTTP 客户端未初始化: {self._name}")

        with self._lock:
            self._request_id += 1
            req_id = self._request_id

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        resp = self._client.post(self._config["url"], json=payload)
        resp.raise_for_status()

        data = resp.json()
        if data.get("id") != req_id:
            raise RuntimeError("MCP 响应 ID 不匹配")

        if "error" in data:
            raise RuntimeError(f"MCP 错误: {data['error']}")

        return data

    def _http_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """通过 HTTP 发送 JSON-RPC 通知。"""
        if self._client is None:
            return

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }

        try:
            self._client.post(self._config["url"], json=payload)
        except Exception as e:
            logger.debug("MCP 通知发送失败: %s - %s", method, e)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用 MCP 服务器上的工具。

        Args:
            name: 工具名称
            arguments: 工具参数

        Returns:
            工具执行结果（统一格式）
        """
        loop = asyncio.get_event_loop()

        if self._transport == "stdio":
            result = await loop.run_in_executor(
                None,
                self._call_tool_stdio,
                name,
                arguments,
            )
        else:
            result = await loop.run_in_executor(
                None,
                self._call_tool_http,
                name,
                arguments,
            )

        return result

    def _call_tool_stdio(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """通过 stdio 调用工具。"""
        resp = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })

        result = resp.get("result", {})
        content = result.get("content", [])

        return {
            "success": True,
            "content": content,
            "error": None,
        }

    def _call_tool_http(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """通过 HTTP 调用工具。"""
        resp = self._http_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })

        result = resp.get("result", {})
        content = result.get("content", [])

        return {
            "success": True,
            "content": content,
            "error": None,
        }

    def get_tools(self) -> list[dict[str, Any]]:
        """获取服务器提供的工具列表。

        Returns:
            工具列表，每个工具包含 name、description、inputSchema 等字段
        """
        return [
            {**tool, "server": self._name}
            for tool in self._tools
        ]

    def get_tool(self, tool_name: str) -> dict[str, Any] | None:
        """根据名称获取工具定义。

        Args:
            tool_name: 工具名称

        Returns:
            工具定义，或 None
        """
        for tool in self._tools:
            if tool.get("name") == tool_name:
                return {**tool, "server": self._name}
        return None

    def get_status(self) -> dict[str, Any]:
        """获取服务器状态。

        Returns:
            状态字典
        """
        uptime = None
        if self._start_time is not None:
            uptime = time.time() - self._start_time

        return {
            "name": self._name,
            "running": self._running,
            "transport": self._transport,
            "tool_count": len(self._tools),
            "uptime": uptime,
        }

    def get_health_status(self) -> dict[str, Any]:
        """获取健康检查状态。

        Returns:
            健康状态字典
        """
        if not self._running:
            return {
                "healthy": False,
                "error": "服务器未运行",
            }

        try:
            if self._transport == "stdio" and self._proc is not None:
                if self._proc.poll() is not None:
                    return {
                        "healthy": False,
                        "error": "进程已退出",
                    }
            return {"healthy": True}
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
            }


class MCPClient:
    """MCP 客户端主类。

    管理多个 MCP 服务器连接，提供统一的工具调用接口。
    """

    _instance: MCPClient | None = None

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._servers: dict[str, MCPServerTask] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._initialized = False

        MCPClient._instance = self

    @classmethod
    def get_instance(cls) -> MCPClient | None:
        """获取 MCPClient 单例实例。"""
        return cls._instance

    async def start_all(self) -> dict[str, bool]:
        """启动所有配置的 MCP 服务器。

        Returns:
            服务器名称到启动结果（bool）的映射
        """
        from tools.mcp_tool_discovery import discover_mcp_servers, filter_discovered_servers
        from tools.mcp_tool_config import validate_server_config

        servers = discover_mcp_servers(self._config)
        servers = filter_discovered_servers(servers)

        self._loop = asyncio.get_event_loop()
        results = {}

        for server_config in servers:
            name = server_config.get("name", "unnamed")

            is_valid, error_msg = validate_server_config(server_config)
            if not is_valid:
                logger.warning("跳过无效的 MCP 服务器配置: %s - %s", name, error_msg)
                results[name] = False
                continue

            try:
                server = MCPServerTask(name, server_config, self._loop)
                await server.start()
                self._servers[name] = server
                results[name] = True
                logger.info("MCP 服务器已启动: %s", name)

            except Exception as e:
                logger.exception("启动 MCP 服务器失败: %s - %s", name, e)
                results[name] = False

        self._initialized = True
        return results

    async def stop_all(self) -> None:
        """停止所有 MCP 服务器。"""
        for name, server in list(self._servers.items()):
            try:
                await server.stop()
                logger.info("MCP 服务器已停止: %s", name)
            except Exception:
                logger.exception("停止 MCP 服务器时出错: %s", name)

        self._servers.clear()
        self._initialized = False

    def get_all_tools(self) -> list[dict[str, Any]]:
        """获取所有 MCP 服务器提供的工具。

        Returns:
            所有工具的列表
        """
        all_tools = []
        for server in self._servers.values():
            all_tools.extend(server.get_tools())
        return all_tools

    def get_tool(self, tool_name: str) -> dict[str, Any] | None:
        """获取指定工具的定义。

        在所有服务器中查找指定名称的工具。

        Args:
            tool_name: 工具名称（不含 mcp_ 前缀）

        Returns:
            工具定义，或 None
        """
        for server in self._servers.values():
            tool = server.get_tool(tool_name)
            if tool is not None:
                return tool
        return None

    def get_server(self, name: str) -> MCPServerTask | None:
        """获取指定名称的服务器实例。

        Args:
            name: 服务器名称

        Returns:
            服务器实例，或 None
        """
        return self._servers.get(name)

    def get_all_servers(self) -> dict[str, MCPServerTask]:
        """获取所有服务器实例。

        Returns:
            服务器名称到实例的映射
        """
        return dict(self._servers)

    def is_initialized(self) -> bool:
        """检查客户端是否已初始化。"""
        return self._initialized

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """调用指定服务器上的工具。

        Args:
            server_name: 服务器名称
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            工具执行结果
        """
        server = self.get_server(server_name)
        if server is None:
            return {
                "success": False,
                "content": [],
                "error": f"MCP 服务器未找到: {server_name}",
            }

        try:
            return await server.call_tool(tool_name, arguments)
        except TimeoutError as e:
            return {
                "success": False,
                "content": [],
                "error": f"工具调用超时: {e}",
            }
        except RuntimeError as e:
            return {
                "success": False,
                "content": [],
                "error": str(e),
            }
        except Exception as e:
            return {
                "success": False,
                "content": [],
                "error": f"工具调用异常: {e}",
            }
