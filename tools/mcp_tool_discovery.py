"""发现和加载 MCP 服务器配置。

从各种来源发现 MCP 服务器：config.yaml、环境变量、Zeloo 配置目录。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ZELOO_CONFIG_DIR = Path.home() / ".Zeloo"
ZELOO_CONFIG_FILE = "config.yaml"
MCP_CONFIG_KEY = "mcp"
SERVERS_KEY = "servers"


def discover_mcp_servers(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """从 config.yaml 读取 mcp_servers 配置。

    按以下优先级查找配置：
    1. 传入的 config 参数中的 mcp.servers
    2. ~/.Zeloo/config.yaml 中的 mcp.servers
    3. ZELOO_MCP_SERVERS 环境变量

    Args:
        config: 可选的预加载配置字典

    Returns:
        服务器配置列表
    """
    from tools.mcp_tool_config import parse_mcp_servers_config

    if config:
        servers = parse_mcp_servers_config(config)
        if servers:
            logger.debug("从传入配置中发现 %d 个 MCP 服务器", len(servers))
            return servers

    local_config = _load_zeloo_config()
    if local_config:
        servers = parse_mcp_servers_config(local_config)
        if servers:
            logger.debug("从 ~/.Zeloo/config.yaml 中发现 %d 个 MCP 服务器", len(servers))
            return servers

    servers = parse_mcp_servers_config({})
    if servers:
        logger.debug("从环境变量中发现 %d 个 MCP 服务器", len(servers))

    return servers


def _load_zeloo_config() -> dict[str, Any] | None:
    """加载 ~/.Zeloo/config.yaml 配置文件。

    Returns:
        解析后的配置字典，或 None
    """
    config_path = ZELOO_CONFIG_DIR / ZELOO_CONFIG_FILE

    if not config_path.exists():
        logger.debug("Zeloo 配置文件不存在: %s", config_path)
        return None

    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        if config and isinstance(config, dict):
            logger.debug("成功加载 Zeloo 配置: %s", config_path)
            return config
    except ImportError:
        logger.debug("PyYAML 未安装，无法解析配置文件")
    except Exception as e:
        logger.warning("加载 Zeloo 配置失败: %s", e)

    return None


def validate_server_config(config: dict[str, Any]) -> tuple[bool, str]:
    """验证服务器配置。

    检查配置是否包含必需字段、类型是否正确。

    Args:
        config: 服务器配置字典

    Returns:
        (is_valid, error_message) 元组
    """
    from tools.mcp_tool_config import validate_server_config as config_validate

    return config_validate(config)


def get_server_capabilities(config: dict[str, Any]) -> dict[str, Any]:
    """获取服务器能力信息。

    根据服务器配置推断其能力，包括：
    - 支持的传输类型
    - 是否支持工具调用
    - 是否支持资源访问
    - 是否支持提示

    Args:
        config: 服务器配置字典

    Returns:
        能力信息字典
    """
    transport = config.get("transport", "stdio")

    capabilities: dict[str, Any] = {
        "transport": transport,
        "tools": True,
        "resources": True,
        "prompts": False,
    }

    if transport == "stdio":
        command = config.get("command", "")
        capabilities["local"] = True

        if "npx" in command or "node" in command:
            capabilities["node_based"] = True
        elif "python" in command or "uv" in command:
            capabilities["python_based"] = True

    elif transport == "http":
        url = config.get("url", "")
        capabilities["local"] = url.startswith("http://localhost") or url.startswith("http://127.0.0.1")
        capabilities["remote"] = not capabilities["local"]

    return capabilities


def filter_discovered_servers(
    servers: list[dict[str, Any]],
    enabled_only: bool = True,
) -> list[dict[str, Any]]:
    """过滤发现的服务列表。

    Args:
        servers: 原始服务器列表
        enabled_only: 是否只返回启用的服务器

    Returns:
        过滤后的服务器列表
    """
    if not enabled_only:
        return list(servers)

    return [s for s in servers if s.get("enabled", True)]


def get_server_by_name(
    servers: list[dict[str, Any]],
    name: str,
) -> dict[str, Any] | None:
    """根据名称查找服务器配置。

    Args:
        servers: 服务器列表
        name: 服务器名称

    Returns:
        服务器配置，或 None
    """
    for server in servers:
        if server.get("name") == name:
            return server
    return None


def merge_server_configs(
    base: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    """合并服务器配置。

    override 中的值会覆盖 base 中的值。

    Args:
        base: 基础配置
        override: 覆盖配置

    Returns:
        合并后的配置
    """
    result = dict(base)

    for key, value in override.items():
        if key == "env" and value:
            existing_env = result.get("env", {})
            if isinstance(existing_env, dict):
                result["env"] = {**existing_env, **value}
            else:
                result["env"] = value
        elif key == "headers" and value:
            existing_headers = result.get("headers", {})
            if isinstance(existing_headers, dict):
                result["headers"] = {**existing_headers, **value}
            else:
                result["headers"] = value
        elif key == "args" and isinstance(value, list):
            existing_args = result.get("args", [])
            if isinstance(existing_args, list):
                result["args"] = existing_args + value
            else:
                result["args"] = value
        else:
            result[key] = value

    return result


def get_default_server_config(name: str) -> dict[str, Any]:
    """获取默认服务器配置。

    Args:
        name: 服务器名称

    Returns:
        默认配置字典
    """
    return {
        "name": name,
        "transport": "stdio",
        "enabled": True,
        "dangerous": False,
        "timeout": 30.0,
        "command": "",
        "args": [],
    }


def list_server_names(servers: list[dict[str, Any]]) -> list[str]:
    """获取服务器名称列表。

    Args:
        servers: 服务器列表

    Returns:
        名称列表
    """
    return [s.get("name", "") for s in servers if s.get("name")]


def get_enabled_server_count(servers: list[dict[str, Any]]) -> int:
    """获取已启用服务器的数量。

    Args:
        servers: 服务器列表

    Returns:
        启用服务器数量
    """
    return sum(1 for s in servers if s.get("enabled", True))
