"""Datadog MCP server — exposes Datadog API as MCP tools over stdio JSON-RPC."""

from __future__ import annotations

import os

from optional_mcps.base import MCPServer, make_tool

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


DATADOG_API_BASE = "https://api.datadoghq.com/api/v1"


def _datadog_get(path: str, params: dict | None = None) -> dict | list:
    url = f"{DATADOG_API_BASE}/{path.lstrip('/')}"
    params = params or {}
    params["api_key"] = os.environ.get("DD_API_KEY", "")
    params["application_key"] = os.environ.get("DD_APP_KEY", "")
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def _format_monitor(m: dict) -> str:
    name = m.get("name", "?")
    m_type = m.get("type", "?")
    state = m.get("overall_state", "?")
    message = m.get("message", "")
    tags = m.get("tags", [])
    tags_str = ", ".join(tags) if tags else "(none)"
    result = f"{name} — [{state}] ({m_type})\nTags: {tags_str}"
    if message:
        result += f"\nMessage: {message}"
    return result


def _format_host(h: dict) -> str:
    hostname = h.get("hostname", "?")
    last_report = h.get("last_report_time", "?")
    status = h.get("status", "?")
    tags = h.get("tags_by_source", [])
    tags_str = ", ".join(tags) if tags else "(none)"
    return f"{hostname} — [{status}]\nLast report: {last_report}\nTags: {tags_str}"


if _HTTPX_AVAILABLE:

    @make_tool(
        name="datadog_search_metrics",
        description="Search for metrics matching a query",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Metric search query"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    )
    def datadog_search_metrics(query: str, max_results: int = 10) -> str:
        data = _datadog_get("search", {"q": query})
        results = data.get("results", {}).get("metrics", []) if isinstance(data, dict) else []
        results = results[:max_results]
        if not results:
            return f"No metrics found matching '{query}'."
        return "\n".join(results)

    @make_tool(
        name="datadog_query_metrics",
        description="Query metric data points",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Metric query (e.g., avg:system.cpu.user{*})",
                },
                "from_sec": {
                    "type": "integer",
                    "default": 3600,
                    "description": "Seconds ago to query from",
                },
                "max_points": {"type": "integer", "default": 100},
            },
            "required": ["query"],
        },
    )
    def datadog_query_metrics(
        query: str, from_sec: int = 3600, max_points: int = 100
    ) -> str:
        data = _datadog_get("query", {"query": query, "from": -from_sec})
        series = data.get("series", []) if isinstance(data, dict) else []
        points: list[tuple[int, float]] = []
        for s in series:
            for pt in s.get("pointlist", []):
                if pt and len(pt) >= 2:
                    points.append((int(pt[0]), pt[1]))
        points = points[:max_points]
        if not points:
            return "No data points found."
        return "\n".join(f"{ts},{val}" for ts, val in points)

    @make_tool(
        name="datadog_list_monitors",
        description="List all monitors",
        input_schema={
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "default": 10},
            },
        },
    )
    def datadog_list_monitors(max_results: int = 10) -> str:
        data = _datadog_get("monitor")
        monitors = data if isinstance(data, list) else []
        monitors = monitors[:max_results]
        if not monitors:
            return "No monitors found."
        return "\n\n".join(_format_monitor(m) for m in monitors)

    @make_tool(
        name="datadog_get_monitor",
        description="Get details of a specific monitor",
        input_schema={
            "type": "object",
            "properties": {
                "monitor_id": {"type": "string", "description": "Monitor ID"},
            },
            "required": ["monitor_id"],
        },
    )
    def datadog_get_monitor(monitor_id: str) -> str:
        data = _datadog_get(f"monitor/{monitor_id}")
        return _format_monitor(data)

    @make_tool(
        name="datadog_list_hosts",
        description="List all hosts",
        input_schema={
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "default": 20},
            },
        },
    )
    def datadog_list_hosts(max_results: int = 20) -> str:
        data = _datadog_get("hosts", {"count": max_results})
        hosts = data.get("host_list", []) if isinstance(data, dict) else []
        hosts = hosts[:max_results]
        if not hosts:
            return "No hosts found."
        return "\n\n".join(_format_host(h) for h in hosts)

    TOOLS: list = [
        datadog_search_metrics,
        datadog_query_metrics,
        datadog_list_monitors,
        datadog_get_monitor,
        datadog_list_hosts,
    ]

else:
    TOOLS = []


def main() -> None:
    server = MCPServer(name="datadog", version="1.0.0", tools=TOOLS)
    server.run()


if __name__ == "__main__":
    main()
