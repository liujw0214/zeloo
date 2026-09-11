"""MCP 服务器生命周期管理。

管理 MCP 服务器的启动、停止、重启等生命周期操作。
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_global_servers: dict[str, Any] = {}
_shutdown_registered = False


async def start_mcp_servers(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """启动所有配置的 MCP 服务器。

    从配置中发现服务器，验证配置，然后逐个启动。

    Args:
        config: 可选的配置字典

    Returns:
        服务器名称到服务器实例的映射
    """
    global _global_servers, _shutdown_registered

    from tools.mcp_tool_discovery import discover_mcp_servers, filter_discovered_servers
    from tools.mcp_tool_config import validate_server_config, get_server_config_summary

    servers = discover_mcp_servers(config)
    servers = filter_discovered_servers(servers)

    if not servers:
        logger.debug("未发现需要启动的 MCP 服务器")
        return _global_servers

    logger.info("发现 %d 个 MCP 服务器配置", len(servers))

    _register_shutdown_hook()

    for server_config in servers:
        name = server_config.get("name", "unnamed")

        is_valid, error_msg = validate_server_config(server_config)
        if not is_valid:
            logger.warning("跳过无效的 MCP 服务器配置: %s - %s", name, error_msg)
            continue

        logger.debug("启动 MCP 服务器: %s", get_server_config_summary(server_config))

        try:
            from tools.mcp_tool import MCPServerTask

            server = MCPServerTask(name, server_config, asyncio.get_event_loop())
            await server.start()
            _global_servers[name] = server

            logger.info("MCP 服务器已启动: %s", name)

        except Exception as e:
            logger.exception("启动 MCP 服务器失败: %s", name)

    return _global_servers


async def stop_mcp_servers(servers: dict[str, Any] | None = None) -> None:
    """停止所有 MCP 服务器。

    Args:
        servers: 服务器映射，如果为 None 则停止全局服务器
    """
    global _global_servers

    if servers is None:
        servers = _global_servers

    if not servers:
        return

    logger.info("停止 %d 个 MCP 服务器", len(servers))

    stop_tasks = []
    for name, server in servers.items():
        task = _stop_server_safe(name, server)
        stop_tasks.append(task)

    await asyncio.gather(*stop_tasks, return_exceptions=True)

    for name in servers:
        if name in _global_servers:
            del _global_servers[name]


async def _stop_server_safe(name: str, server: Any) -> None:
    """安全地停止服务器。

    Args:
        name: 服务器名称
        server: 服务器实例
    """
    try:
        await server.stop()
        logger.info("MCP 服务器已停止: %s", name)
    except Exception:
        logger.exception("停止 MCP 服务器时出错: %s", name)


async def restart_server(name: str, server: Any) -> bool:
    """重启单个服务器。

    Args:
        name: 服务器名称
        server: 服务器实例

    Returns:
        重启是否成功
    """
    logger.info("重启 MCP 服务器: %s", name)

    try:
        await server.stop()
        await asyncio.sleep(0.5)
        await server.start()
        logger.info("MCP 服务器重启成功: %s", name)
        return True

    except Exception as e:
        logger.exception("重启 MCP 服务器失败: %s - %s", name, e)
        return False


async def restart_all_servers() -> dict[str, bool]:
    """重启所有 MCP 服务器。

    Returns:
        服务器名称到重启结果（bool）的映射
    """
    global _global_servers

    results = {}
    for name, server in list(_global_servers.items()):
        results[name] = await restart_server(name, server)

    return results


def shutdown_mcp_servers() -> None:
    """同步关闭钩子（用于程序退出）。

    通过 atexit 注册，确保程序退出时所有服务器被正确停止。
    """
    global _global_servers

    if not _global_servers:
        return

    logger.info("执行同步关闭: 停止 %d 个 MCP 服务器", len(_global_servers))

    for name, server in list(_global_servers.items()):
        try:
            if hasattr(server, "stop"):
                server.stop()
            logger.debug("MCP 服务器已停止: %s", name)
        except Exception:
            logger.exception("停止 MCP 服务器时出错: %s", name)

    _global_servers.clear()


def _register_shutdown_hook() -> None:
    """注册程序退出时的清理钩子。"""
    global _shutdown_registered

    if not _shutdown_registered:
        atexit.register(shutdown_mcp_servers)
        _shutdown_registered = True
        logger.debug("已注册 MCP 服务器关闭钩子")


def get_running_servers() -> dict[str, Any]:
    """获取当前运行的服务器映射。

    Returns:
        服务器名称到实例的映射
    """
    global _global_servers
    return dict(_global_servers)


def get_server_health(name: str) -> dict[str, Any]:
    """获取服务器健康状态。

    Args:
        name: 服务器名称

    Returns:
        健康状态字典
    """
    global _global_servers

    if name not in _global_servers:
        return {
            "running": False,
            "error": "服务器未运行",
        }

    server = _global_servers[name]
    return server.get_health_status()


def check_all_servers_health() -> dict[str, dict[str, Any]]:
    """检查所有服务器的运行状态。

    Returns:
        服务器名称到健康状态的映射
    """
    global _global_servers

    health = {}
    for name in _global_servers:
        health[name] = get_server_health(name)

    return health


class ServerLifecycleManager:
    """服务器生命周期管理器。

    提供更细粒度的生命周期控制，支持统计和监控。
    """

    def __init__(self) -> None:
        self._servers: dict[str, Any] = {}
        self._start_times: dict[str, float] = {}
        self._restart_counts: dict[str, int] = {}
        self._error_counts: dict[str, int] = {}

    async def start(self, config: dict[str, Any] | None = None) -> int:
        """启动服务器并返回成功启动的数量。

        Args:
            config: 配置字典

        Returns:
            成功启动的服务器数量
        """
        from tools.mcp_tool_discovery import discover_mcp_servers, filter_discovered_servers
        from tools.mcp_tool_config import validate_server_config

        servers = discover_mcp_servers(config)
        servers = filter_discovered_servers(servers)

        started_count = 0
        for server_config in servers:
            name = server_config.get("name", "unnamed")

            is_valid, _ = validate_server_config(server_config)
            if not is_valid:
                continue

            try:
                from tools.mcp_tool import MCPServerTask

                server = MCPServerTask(name, server_config, asyncio.get_event_loop())
                await server.start()

                self._servers[name] = server
                self._start_times[name] = time.time()
                self._restart_counts[name] = 0

                started_count += 1

            except Exception as e:
                logger.exception("启动服务器失败: %s", name)
                self._error_counts[name] = self._error_counts.get(name, 0) + 1

        _register_shutdown_hook()
        return started_count

    async def stop(self) -> None:
        """停止所有服务器。"""
        for server in list(self._servers.values()):
            try:
                await server.stop()
            except Exception:
                logger.exception("停止服务器时出错")

        self._servers.clear()

    def get_server(self, name: str) -> Any | None:
        """获取服务器实例。"""
        return self._servers.get(name)

    def get_uptime(self, name: str) -> float | None:
        """获取服务器运行时间（秒）。"""
        start_time = self._start_times.get(name)
        if start_time is None:
            return None
        return time.time() - start_time

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息。"""
        return {
            "total_servers": len(self._servers),
            "uptimes": {name: self.get_uptime(name) for name in self._servers},
            "restart_counts": dict(self._restart_counts),
            "error_counts": dict(self._error_counts),
        }
