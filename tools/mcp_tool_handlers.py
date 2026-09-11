"""处理 MCP 工具调用的请求/响应。

提供统一的工具调用接口，处理 stdio 和 HTTP 两种传输方式。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def handle_mcp_tool_call(
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any],
    mcp_client: Any = None,
) -> dict[str, Any]:
    """调用 MCP 服务器的工具。

    构建 JSON-RPC 请求，发送到 MCP 服务器，解析响应并返回统一格式。

    Args:
        server_name: MCP 服务器名称
        tool_name: 要调用的工具名称
        arguments: 工具调用参数
        mcp_client: MCP 客户端实例（可选，如果提供则直接使用）

    Returns:
        统一格式的响应字典:
        {
            "success": bool,
            "content": list[dict],  # Anthropic content blocks 格式
            "error": str | None
        }
    """
    if mcp_client is None:
        from tools.mcp_tool import MCPClient

        client = MCPClient.get_instance()
        if client is None:
            return {
                "success": False,
                "content": [],
                "error": "MCP 客户端未初始化",
            }

        server = client.get_server(server_name)
        if server is None:
            return {
                "success": False,
                "content": [],
                "error": f"MCP 服务器未找到: {server_name}",
            }

        mcp_client = server

    try:
        result = await _call_tool_async(mcp_client, tool_name, arguments)
        content = _format_result_as_content(result)

        return {
            "success": True,
            "content": content,
            "error": None,
        }

    except TimeoutError as e:
        logger.warning("MCP 工具调用超时: %s.%s", server_name, tool_name)
        return {
            "success": False,
            "content": [],
            "error": f"工具调用超时: {e}",
        }

    except RuntimeError as e:
        logger.warning("MCP 工具调用错误: %s.%s - %s", server_name, tool_name, e)
        return {
            "success": False,
            "content": [],
            "error": str(e),
        }

    except Exception as e:
        logger.exception("MCP 工具调用异常: %s.%s", server_name, tool_name)
        return {
            "success": False,
            "content": [],
            "error": f"工具调用异常: {e}",
        }


async def _call_tool_async(
    client: Any,
    tool_name: str,
    arguments: dict[str, Any],
) -> Any:
    """异步调用 MCP 工具。

    Args:
        client: MCP 客户端实例
        tool_name: 工具名称
        arguments: 调用参数

    Returns:
        工具执行结果
    """
    loop = _get_event_loop()
    return await loop.run_in_executor(None, client.call_tool, tool_name, arguments)


def _get_event_loop():
    """获取当前事件循环。"""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def _format_result_as_content(result: Any) -> list[dict[str, Any]]:
    """将工具结果格式化为 Anthropic content blocks 格式。

    Args:
        result: 工具执行结果

    Returns:
        content blocks 列表
    """
    if result is None:
        return []

    if isinstance(result, str):
        return [{"type": "text", "text": result}]

    if isinstance(result, dict):
        if "content" in result:
            return result["content"]
        return [{"type": "text", "text": _format_dict_as_text(result)}]

    if isinstance(result, list):
        content = []
        for item in result:
            if isinstance(item, dict) and item.get("type") == "text":
                content.append(item)
            else:
                content.append({"type": "text", "text": str(item)})
        return content

    return [{"type": "text", "text": str(result)}]


def _format_dict_as_text(data: dict[str, Any], indent: int = 0) -> str:
    """将字典格式化为易读的文本。

    Args:
        data: 要格式化的字典
        indent: 缩进级别

    Returns:
        格式化后的文本
    """
    lines = []
    prefix = "  " * indent

    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(_format_dict_as_text(value, indent + 1))
        elif isinstance(value, list):
            lines.append(f"{prefix}{key}: [{len(value)} items]")
        else:
            lines.append(f"{prefix}{key}: {value}")

    return "\n".join(lines)


def handle_mcp_tool_list(
    server_name: str | None = None,
    mcp_client: Any = None,
) -> dict[str, Any]:
    """列出 MCP 服务器提供的工具。

    Args:
        server_name: 服务器名称（可选，不指定则列出所有服务器的工具）
        mcp_client: MCP 客户端实例

    Returns:
        工具列表响应
    """
    if mcp_client is None:
        from tools.mcp_tool import MCPClient

        client = MCPClient.get_instance()
        if client is None:
            return {
                "success": False,
                "content": [],
                "error": "MCP 客户端未初始化",
            }
        mcp_client = client

    try:
        if server_name:
            server = mcp_client.get_server(server_name)
            if server is None:
                return {
                    "success": False,
                    "content": [],
                    "error": f"MCP 服务器未找到: {server_name}",
                }
            tools = server.get_tools()
        else:
            tools = mcp_client.get_all_tools()

        content = [{"type": "text", "text": _format_tools_list(tools)}]

        return {
            "success": True,
            "content": content,
            "error": None,
        }

    except Exception as e:
        logger.exception("获取 MCP 工具列表失败")
        return {
            "success": False,
            "content": [],
            "error": f"获取工具列表失败: {e}",
        }


def _format_tools_list(tools: list[dict[str, Any]]) -> str:
    """格式化工具列表为文本。

    Args:
        tools: 工具列表

    Returns:
        格式化的工具列表文本
    """
    if not tools:
        return "(无可用工具)"

    lines = [f"# 可用 MCP 工具 ({len(tools)} 个)\n"]

    current_server = None
    for tool in tools:
        server = tool.get("server", "unknown")
        if server != current_server:
            lines.append(f"\n## {server}")
            current_server = server

        name = tool.get("name", "unnamed")
        desc = tool.get("description", "")
        lines.append(f"- **{name}**: {desc[:60]}{'...' if len(desc) > 60 else ''}")

    return "\n".join(lines)


def handle_mcp_server_status(
    server_name: str,
    mcp_client: Any = None,
) -> dict[str, Any]:
    """获取 MCP 服务器状态。

    Args:
        server_name: 服务器名称
        mcp_client: MCP 客户端实例

    Returns:
        服务器状态响应
    """
    if mcp_client is None:
        from tools.mcp_tool import MCPClient

        client = MCPClient.get_instance()
        if client is None:
            return {
                "success": False,
                "content": [],
                "error": "MCP 客户端未初始化",
            }
        mcp_client = client

    try:
        server = mcp_client.get_server(server_name)
        if server is None:
            return {
                "success": False,
                "content": [],
                "error": f"MCP 服务器未找到: {server_name}",
            }

        status = server.get_status()
        content = [{"type": "text", "text": _format_server_status(server_name, status)}]

        return {
            "success": True,
            "content": content,
            "error": None,
        }

    except Exception as e:
        logger.exception("获取 MCP 服务器状态失败")
        return {
            "success": False,
            "content": [],
            "error": f"获取服务器状态失败: {e}",
        }


def _format_server_status(server_name: str, status: dict[str, Any]) -> str:
    """格式化服务器状态为文本。

    Args:
        server_name: 服务器名称
        status: 状态字典

    Returns:
        格式化的状态文本
    """
    lines = [f"# MCP 服务器状态: {server_name}\n"]

    running = status.get("running", False)
    lines.append(f"- **运行状态**: {'运行中' if running else '已停止'}")
    lines.append(f"- **工具数量**: {status.get('tool_count', 0)}")
    lines.append(f"- **传输类型**: {status.get('transport', 'unknown')}")

    if "error" in status:
        lines.append(f"- **错误**: {status['error']}")

    if "uptime" in status:
        lines.append(f"- **运行时间**: {status['uptime']:.1f}s")

    return "\n".join(lines)


async def handle_mcp_batch_call(
    calls: list[dict[str, Any]],
    mcp_client: Any = None,
) -> list[dict[str, Any]]:
    """批量调用多个 MCP 工具。

    Args:
        calls: 调用列表，每个元素包含 server_name, tool_name, arguments
        mcp_client: MCP 客户端实例

    Returns:
        结果列表
    """
    results = []
    for call in calls:
        server_name = call.get("server_name", "")
        tool_name = call.get("tool_name", "")
        arguments = call.get("arguments", {})

        result = await handle_mcp_tool_call(
            server_name=server_name,
            tool_name=tool_name,
            arguments=arguments,
            mcp_client=mcp_client,
        )
        results.append({
            "server": server_name,
            "tool": tool_name,
            "result": result,
        })

    return results
