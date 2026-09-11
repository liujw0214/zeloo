"""MCP 公共常量和工具函数。

提供 MCP 工具的 JSON Schema、默认值、字段访问兼容函数等公共组件。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MCP_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "server_name": {
            "type": "string",
            "description": "MCP 服务器名称",
        },
        "tool_name": {
            "type": "string",
            "description": "要调用的 MCP 工具名称",
        },
        "arguments": {
            "type": "object",
            "description": "工具调用参数",
            "additionalProperties": True,
        },
    },
    "required": ["server_name", "tool_name"],
}

MCP_TOOL_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "server_name": {
            "type": "string",
            "description": "MCP 服务器名称（可选，不指定则列出所有服务器的工具）",
        },
        "include_internal": {
            "type": "boolean",
            "description": "是否包含内部工具（默认 false）",
            "default": False,
        },
    },
    "required": [],
}

MCP_SERVER_STATUS_SCHEMA = {
    "type": "object",
    "properties": {
        "server_name": {
            "type": "string",
            "description": "MCP 服务器名称",
        },
    },
    "required": ["server_name"],
}

DEFAULT_TIMEOUT = 30.0

DEFAULT_PROTOCOL_VERSION = "2024-11-05"

MCP_JSONRPC_VERSION = "2.0"

TRANSPORT_STDIO = "stdio"
TRANSPORT_HTTP = "http"

SUPPORTED_TRANSPORTS = {TRANSPORT_STDIO, TRANSPORT_HTTP}


def mcp_field(result: object, *names: str) -> Any:
    """兼容访问 snake_case / camelCase 字段。

    尝试按顺序查找给定的字段名，返回第一个找到的值。
    如果都找不到，返回 None。

    Args:
        result: 要访问的对象（dict 或 dataclass）
        *names: 可能的字段名列表（按优先级排序）

    Returns:
        找到的字段值，或 None

    Example:
        >>> data = {"serverName": "test", "server_name": "test2"}
        >>> mcp_field(data, "serverName", "server_name")
        'test'
    """
    if result is None:
        return None

    if isinstance(result, dict):
        for name in names:
            if name in result:
                return result[name]
    else:
        for name in names:
            if hasattr(result, name):
                return getattr(result, name)
            snake_name = _camel_to_snake(name)
            if hasattr(result, snake_name):
                return getattr(result, snake_name)
            kebab_name = _snake_to_kebab(name)
            if hasattr(result, kebab_name):
                return getattr(result, kebab_name)

    return None


def _camel_to_snake(name: str) -> str:
    """将 camelCase 转换为 snake_case。"""
    result = []
    for i, char in enumerate(name):
        if char.isupper() and i > 0:
            result.append("_")
        result.append(char.lower())
    return "".join(result)


def _snake_to_kebab(name: str) -> str:
    """将 snake_case 转换为 kebab-case。"""
    return name.replace("_", "-")


def format_mcp_error(error: dict[str, Any]) -> str:
    """格式化 MCP 错误为可读字符串。

    Args:
        error: MCP 错误对象，通常包含 code、message、data 字段

    Returns:
        格式化的错误字符串

    Example:
        >>> err = {"code": -32600, "message": "Invalid Request"}
        >>> format_mcp_error(err)
        '[MCP Error -32600] Invalid Request'
    """
    if not isinstance(error, dict):
        return f"[MCP Error] {error}"

    code = error.get("code", 0)
    message = error.get("message", "Unknown error")
    data = error.get("data")

    result = f"[MCP Error {code}] {message}"
    if data is not None:
        result += f" | Data: {data}"

    return result


def format_mcp_content(content: list[dict[str, Any]]) -> str:
    """将 MCP 内容块格式化为文本。

    MCP 响应通常包含 content 数组，每项可能是 text、image、audio 等类型。
    此函数将所有文本内容连接起来。

    Args:
        content: MCP 内容块列表

    Returns:
        格式化的文本内容

    Example:
        >>> content = [{"type": "text", "text": "Hello"}, {"type": "text", "text": "World"}]
        >>> format_mcp_content(content)
        'Hello\\nWorld'
    """
    if not content:
        return ""

    parts = []
    for block in content:
        block_type = mcp_field(block, "type", "type")
        if block_type == "text":
            text = mcp_field(block, "text", "text")
            if text:
                parts.append(text)
        elif block_type == "image":
            parts.append("[Image content]")
        elif block_type == "audio":
            parts.append("[Audio content]")
        elif block_type == "resource":
            parts.append(f"[Resource: {mcp_field(block, 'uri', 'resource')}]")
        else:
            parts.append(str(block))

    return "\n".join(parts)


def parse_timeout(config: dict[str, Any] | None) -> float:
    """从配置中解析超时值。

    Args:
        config: 服务器配置字典

    Returns:
        超时时间（秒），默认 DEFAULT_TIMEOUT
    """
    if not config:
        return DEFAULT_TIMEOUT

    timeout = config.get("timeout", DEFAULT_TIMEOUT)
    try:
        return float(timeout)
    except (ValueError, TypeError):
        return DEFAULT_TIMEOUT


def get_error_code_name(code: int) -> str:
    """获取 JSON-RPC 错误码的友好名称。

    Args:
        code: JSON-RPC 错误码

    Returns:
        错误码对应的名称
    """
    error_names = {
        -32700: "Parse Error",
        -32600: "Invalid Request",
        -32601: "Method Not Found",
        -32602: "Invalid Params",
        -32603: "Internal Error",
        -32000: "Server Error",
    }
    return error_names.get(code, f"Error {code}")


def build_jsonrpc_request(
    method: str,
    params: dict[str, Any] | None = None,
    request_id: int | None = None,
) -> dict[str, Any]:
    """构建 JSON-RPC 2.0 请求对象。

    Args:
        method: 要调用的方法名
        params: 方法参数
        request_id: 请求 ID（可选，自动生成）

    Returns:
        JSON-RPC 2.0 请求字典
    """
    request: dict[str, Any] = {
        "jsonrpc": MCP_JSONRPC_VERSION,
        "method": method,
    }
    if params:
        request["params"] = params
    if request_id is not None:
        request["id"] = request_id
    return request


def is_jsonrpc_success(response: dict[str, Any]) -> bool:
    """检查 JSON-RPC 响应是否成功。

    Args:
        response: JSON-RPC 响应对象

    Returns:
        True 如果响应表示成功
    """
    if not isinstance(response, dict):
        return False
    return "result" in response and "error" not in response


def extract_result(response: dict[str, Any]) -> Any:
    """从 JSON-RPC 响应中提取结果。

    Args:
        response: JSON-RPC 响应对象

    Returns:
        响应结果，或 None（如果响应失败）

    Raises:
        RuntimeError: 如果响应包含错误
    """
    if "error" in response:
        error = response["error"]
        raise RuntimeError(format_mcp_error(error))
    return response.get("result")
