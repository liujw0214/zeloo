"""Grafana MCP Server — dashboards, alerts, and metrics exploration."""

from __future__ import annotations

import os
from typing import Any

from optional_mcps.base import MCPServer, make_tool


def _grafana_headers() -> dict[str, str]:
    token = os.environ.get("GRAFANA_TOKEN", "")
    if not token:
        raise RuntimeError("Set GRAFANA_TOKEN (or GRAFANA_KEY).")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _get_grafana_url() -> str:
    return os.environ.get("GRAFANA_URL", "http://localhost:3000").rstrip("/")


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    import httpx
    url = f"{_get_grafana_url()}/api{path}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=_grafana_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


def _post(path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    import httpx
    url = f"{_get_grafana_url()}/api{path}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=_grafana_headers(), json=data or {})
        resp.raise_for_status()
        return resp.json()


@make_tool(
    name="grafana_list_dashboards",
    description="List all dashboards accessible to the API key",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max results (default 50)", "default": 50},
        },
    },
)
def grafana_list_dashboards(limit: int = 50) -> str:
    data = _get("/search", {"type": "dash-db", "limit": limit})
    lines = []
    for d in data:
        lines.append(f"  {d.get('title', '?')} (uid={d.get('uid', '')}, uri={d.get('uri', '')})")
    return "\n".join(lines) if lines else "No dashboards found."


@make_tool(
    name="grafana_get_dashboard",
    description="Get a dashboard by UID",
    input_schema={
        "type": "object",
        "properties": {
            "uid": {"type": "string", "description": "Dashboard UID"},
        },
        "required": ["uid"],
    },
)
def grafana_get_dashboard(uid: str) -> str:
    data = _get(f"/dashboards/uid/{uid}")
    dash = data.get("dashboard", {})
    meta = data.get("meta", {})
    panels = dash.get("panels", [])
    panel_info = []
    for p in panels:
        panel_info.append(
            f"  [{p.get('type','?')}] {p.get('title','?')} "
            f"id={p.get('id')} gridPos={p.get('gridPos')}"
        )
    return (
        f"Title: {dash.get('title', '?')}\n"
        f"UID: {dash.get('uid', '?')}\n"
        f"Schema Version: {dash.get('schemaVersion', '?')}\n"
        f"Panels ({len(panels)}):\n" + "\n".join(panel_info) +
        f"\nFolder: {meta.get('folderTitle', '?')}"
    )


@make_tool(
    name="grafana_list_alerts",
    description="List all alerting rules",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max results", "default": 50},
        },
    },
)
def grafana_list_alerts(limit: int = 50) -> str:
    data = _get("/v1/rules", {"limit": limit})
    groups = data.get("groups", [])
    lines = []
    for group in groups:
        for rule in group.get("rules", []):
            health = rule.get("health", "?")
            lines.append(
                f"  [{rule.get('type','?')}] {rule.get('name','?')} "
                f"state={rule.get('state','?')} health={health}"
            )
    return "\n".join(lines) if lines else "No alert rules found."


@make_tool(
    name="grafana_query_prometheus",
    description="Execute a Prometheus query (instant or range) against Grafana datasource",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "PromQL query expression"},
            "datasource": {"type": "string", "description": "Datasource UID or name"},
            "instant": {
                "type": "boolean",
                "description": "Instant query (default true)",
                "default": True,
            },
        },
        "required": ["query"],
    },
)
def grafana_query_prometheus(query: str, datasource: str = "", instant: bool = True) -> str:
    params: dict[str, Any] = {"query": query}
    endpoint = "/ds/query"
    if instant:
        params["query_type"] = "instant"
    if datasource:
        params["datasource"] = datasource

    data = _post(endpoint, {
        "queries": [
            {
                "refId": "A",
                "expr": query,
                "datasourceUid": datasource or "prometheus",
            }
        ]
    })

    results = data.get("results", {}).get("A", {}).get("frames", [])
    if not results:
        return "No results returned."

    frames = []
    for frame in results:
        fields = frame.get("data", {}).get("values", [])
        if fields:
            frames.append(f"  {fields}")
    return "\n".join(frames) if frames else "No scalar results."


@make_tool(
    name="grafana_list_datasources",
    description="List all configured datasources",
    input_schema={
        "type": "object",
        "properties": {},
    },
)
def grafana_list_datasources() -> str:
    datasources = _get("/datasources")
    lines = []
    for ds in datasources:
        lines.append(
            f"  [{ds.get('type', '?')}] {ds.get('name', '?')} "
            f"uid={ds.get('uid', '')} url={ds.get('url', '?')}"
        )
    return "\n".join(lines) if lines else "No datasources found."


class GrafanaServer(MCPServer):
    name = "grafana"
    version = "1.0.0"
    TOOLS = [
        grafana_list_dashboards,
        grafana_get_dashboard,
        grafana_list_alerts,
        grafana_query_prometheus,
        grafana_list_datasources,
    ]


if __name__ == "__main__":
    server = GrafanaServer(tools=GrafanaServer.TOOLS)
    server.run()
