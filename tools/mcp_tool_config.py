"""MCP 服务器配置解析。

解析 config.yaml 中的 mcp_servers 配置，处理命令路径解析和环境变量。
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_KEY_MCP_SERVERS = "mcp.servers"
ENV_VAR_MCP_SERVERS = "ZELOO_MCP_SERVERS"


def parse_mcp_servers_config(config_yaml: dict[str, Any]) -> list[dict[str, Any]]:
    """解析 config.yaml 中的 mcp_servers 配置。

    支持两种配置格式：

    1. 标准格式（config.yaml）:
       mcp:
         servers:
           - name: filesystem
             transport: stdio
             command: npx
             args: ["-y", "@modelcontextprotocol/server-filesystem", "/path"]

    2. 环境变量格式（ZELOO_MCP_SERVERS）:
       ZELOO_MCP_SERVERS=filesystem=npx -y @modelcontextprotocol/server-filesystem /path,remote=http://localhost:8080/sse

    Args:
        config_yaml: 解析后的 config.yaml 字典

    Returns:
        服务器配置列表，每个配置包含 name、transport 等字段
    """
    servers: list[dict[str, Any]] = []

    if config_yaml:
        mcp_config = config_yaml.get("mcp", {})
        if isinstance(mcp_config, dict):
            config_servers = mcp_config.get("servers", [])
            if isinstance(config_servers, list):
                servers = _normalize_server_configs(config_servers)

    if not servers:
        servers = _parse_env_var_servers()

    return servers


def _normalize_server_configs(configs: list[Any]) -> list[dict[str, Any]]:
    """标准化服务器配置列表。

    确保每个配置都有必要的字段和正确的类型。

    Args:
        configs: 原始配置列表

    Returns:
        标准化后的配置列表
    """
    result = []
    for config in configs:
        if not isinstance(config, dict):
            continue

        normalized: dict[str, Any] = {
            "name": config.get("name", ""),
            "transport": config.get("transport", "stdio"),
            "enabled": config.get("enabled", True),
            "dangerous": config.get("dangerous", False),
            "timeout": config.get("timeout", 30.0),
        }

        transport = normalized["transport"]
        if transport == "stdio":
            normalized["command"] = config.get("command", "")
            normalized["args"] = _normalize_args(config.get("args"))
            normalized["env"] = _normalize_env(config.get("env"))
            normalized["cwd"] = config.get("cwd")
        elif transport == "http":
            normalized["url"] = config.get("url", "")
            normalized["headers"] = _normalize_headers(config.get("headers"))

        if "tool_filter" in config:
            normalized["tool_filter"] = config["tool_filter"]

        result.append(normalized)

    return result


def _normalize_args(args: Any) -> list[str]:
    """标准化 args 参数。"""
    if args is None:
        return []
    if isinstance(args, str):
        return args.split()
    if isinstance(args, list):
        return [str(arg) for arg in args]
    return []


def _normalize_env(env: Any) -> dict[str, str] | None:
    """标准化环境变量配置。"""
    if env is None:
        return None
    if isinstance(env, dict):
        return {str(k): str(v) for k, v in env.items()}
    return None


def _normalize_headers(headers: Any) -> dict[str, str] | None:
    """标准化 HTTP headers 配置。"""
    if headers is None:
        return None
    if isinstance(headers, dict):
        return {str(k): str(v) for k, v in headers.items()}
    return None


def _parse_env_var_servers() -> list[dict[str, Any]]:
    """从 ZELOO_MCP_SERVERS 环境变量解析服务器配置。

    格式: name1=command arg1 arg2,name2=http://localhost:8080/sse

    Returns:
        服务器配置列表
    """
    env_value = os.environ.get(ENV_VAR_MCP_SERVERS, "")
    if not env_value:
        return []

    servers = []
    for entry in env_value.split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue

        name, target = entry.split("=", 1)
        name = name.strip()
        target = target.strip()

        if not name or not target:
            continue

        if target.startswith("http://") or target.startswith("https://"):
            servers.append({
                "name": name,
                "transport": "http",
                "url": target,
                "enabled": True,
                "dangerous": False,
                "timeout": 30.0,
            })
        else:
            parts = target.split()
            if parts:
                servers.append({
                    "name": name,
                    "transport": "stdio",
                    "command": parts[0],
                    "args": parts[1:],
                    "enabled": True,
                    "dangerous": False,
                    "timeout": 30.0,
                })

    return servers


def resolve_command(command: str, args: list[str]) -> tuple[str, list[str]]:
    """解析命令，支持 npx / uvx / 直接路径。

    自动查找命令的可执行路径，支持：
    - 直接路径（如 /usr/bin/node）
    - 命令名（如 npx, uvx, python）
    - 相对路径（如 ./script.sh）

    Args:
        command: 命令字符串
        args: 命令参数列表

    Returns:
        (resolved_command, resolved_args) 元组

    Raises:
        FileNotFoundError: 如果命令找不到
    """
    resolved = _find_executable(command)
    if resolved is None:
        raise FileNotFoundError(f"Command not found: {command}")

    return resolved, list(args)


def _find_executable(command: str) -> str | None:
    """查找可执行命令的完整路径。

    Args:
        command: 命令名称或路径

    Returns:
        完整路径，或 None 如果找不到
    """
    if os.path.isabs(command) and os.path.exists(command):
        return command

    if os.path.sep in command:
        if os.path.exists(command):
            return os.path.abspath(command)
        return None

    path_env = os.environ.get("PATH", os.defpath)
    return shutil.which(command, path=path_env)


def get_mcp_env(server_config: dict[str, Any]) -> dict[str, str] | None:
    """获取服务器环境变量。

    合并服务器配置中的 env 与当前进程环境变量。

    Args:
        server_config: 服务器配置字典

    Returns:
        合并后的环境变量字典，或 None
    """
    custom_env = server_config.get("env")
    if not custom_env:
        return None

    merged = dict(os.environ)
    merged.update(custom_env)
    return merged


def validate_server_config(config: dict[str, Any]) -> tuple[bool, str]:
    """验证服务器配置是否有效。

    Args:
        config: 服务器配置字典

    Returns:
        (is_valid, error_message) 元组
    """
    if not isinstance(config, dict):
        return False, "配置必须是字典类型"

    name = config.get("name")
    if not name:
        return False, "服务器配置缺少 name 字段"

    if not isinstance(name, str):
        return False, f"服务器 name 必须是字符串，实际为 {type(name).__name__}"

    transport = config.get("transport", "stdio")
    if transport not in {"stdio", "http"}:
        return False, f"不支持的传输类型: {transport}"

    if transport == "stdio":
        command = config.get("command")
        if not command:
            return False, f"stdio 传输需要 command 字段 (服务器: {name})"
        if not isinstance(command, str):
            return False, f"command 必须是字符串 (服务器: {name})"

    elif transport == "http":
        url = config.get("url")
        if not url:
            return False, f"http 传输需要 url 字段 (服务器: {name})"
        if not isinstance(url, str):
            return False, f"url 必须是字符串 (服务器: {name})"
        if not (url.startswith("http://") or url.startswith("https://")):
            return False, f"url 必须以 http:// 或 https:// 开头 (服务器: {name})"

    timeout = config.get("timeout")
    if timeout is not None:
        try:
            timeout_float = float(timeout)
            if timeout_float <= 0:
                return False, f"timeout 必须大于 0 (服务器: {name})"
        except (ValueError, TypeError):
            return False, f"timeout 必须是数字 (服务器: {name})"

    return True, ""


def get_server_config_summary(config: dict[str, Any]) -> str:
    """获取服务器配置的摘要信息。

    Args:
        config: 服务器配置字典

    Returns:
        格式化的配置摘要
    """
    name = config.get("name", "unknown")
    transport = config.get("transport", "stdio")
    enabled = config.get("enabled", True)
    dangerous = config.get("dangerous", False)

    summary = f"{name} ({transport})"

    if not enabled:
        summary += " [disabled]"
    if dangerous:
        summary += " [dangerous]"

    if transport == "stdio":
        command = config.get("command", "")
        args = config.get("args", [])
        summary += f": {command} {' '.join(args)}"
    elif transport == "http":
        url = config.get("url", "")
        summary += f": {url}"

    return summary
