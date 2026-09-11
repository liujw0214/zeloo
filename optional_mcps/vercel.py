"""Vercel MCP server — exposes Vercel API as MCP tools over stdio JSON-RPC."""

from __future__ import annotations

import os

from optional_mcps.base import MCPServer, make_tool

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


VERCEL_API_BASE = "https://api.vercel.com/v6"


def _vercel_get(path: str, params: dict | None = None) -> dict | list:
    token = os.environ.get("VERCEL_TOKEN", "")
    url = f"{VERCEL_API_BASE}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=headers, params=params or {})
        resp.raise_for_status()
        return resp.json()


def _vercel_post(path: str, payload: dict) -> dict:
    token = os.environ.get("VERCEL_TOKEN", "")
    url = f"{VERCEL_API_BASE}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


def _format_deployment(dep: dict) -> str:
    url = dep.get("url", "")
    state = dep.get("state", "?")
    name = dep.get("name", "?")
    created = dep.get("createdAt", "?")
    ready = dep.get("ready", "?")
    status = "ready" if ready else state
    return (
        f"{name} — [{status}]\n"
        f"URL: https://{url}\n"
        f"Created: {created}"
    )


if _HTTPX_AVAILABLE:

    @make_tool(
        name="vercel_list_deployments",
        description="List recent deployments for the Vercel account or team",
        input_schema={
            "type": "object",
            "properties": {
                "team_id": {
                    "type": "string",
                    "description": "Vercel team ID (optional)",
                },
                "max_results": {"type": "integer", "default": 10},
            },
        },
    )
    def vercel_list_deployments(team_id: str = "", max_results: int = 10) -> str:
        path = "deployments"
        params: dict[str, object] = {"limit": min(max_results, 100)}
        if team_id:
            params["teamId"] = team_id
            path = f"teams/{team_id}/deployments"
        data = _vercel_get(path, params)
        deps = data.get("deployments", []) if isinstance(data, dict) else []
        if not deps:
            return "No deployments found."
        return "\n\n".join(_format_deployment(d) for d in deps)

    @make_tool(
        name="vercel_get_deployment",
        description="Get details of a specific deployment",
        input_schema={
            "type": "object",
            "properties": {
                "deployment_id": {
                    "type": "string",
                    "description": "Deployment ID or URL slug",
                },
            },
            "required": ["deployment_id"],
        },
    )
    def vercel_get_deployment(deployment_id: str) -> str:
        data = _vercel_get(f"deployments/{deployment_id}")
        return _format_deployment(data)

    @make_tool(
        name="vercel_list_projects",
        description="List all Vercel projects",
        input_schema={
            "type": "object",
            "properties": {
                "team_id": {"type": "string", "description": "Vercel team ID (optional)"},
                "max_results": {"type": "integer", "default": 20},
            },
        },
    )
    def vercel_list_projects(team_id: str = "", max_results: int = 20) -> str:
        path = "projects"
        params: dict[str, object] = {"limit": min(max_results, 100)}
        if team_id:
            params["teamId"] = team_id
            path = f"projects?teamId={team_id}"
        data = _vercel_get(path, params)
        projects = data.get("projects", []) if isinstance(data, dict) else []
        if not projects:
            return "No projects found."
        lines: list[str] = []
        for p in projects:
            name = p.get("name", "?")
            framework = p.get("framework", "")
            framework_str = f" ({framework})" if framework else ""
            lines.append(f"- {name}{framework_str} | ID: {p.get('id', '?')}")
        return f"{len(projects)} project(s):\n" + "\n".join(lines)

    @make_tool(
        name="vercel_get_project",
        description="Get details of a specific project",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project name or ID"},
            },
            "required": ["project_id"],
        },
    )
    def vercel_get_project(project_id: str) -> str:
        data = _vercel_get(f"projects/{project_id}")
        framework = data.get("framework", "")
        repo = data.get("link", {}).get("repo", "")
        env_vars = data.get("env", [])
        lines = [
            f"Project: {data.get('name', '?')}",
            f"ID: {data.get('id', '?')}",
            f"Framework: {framework or '(none)'}",
            f"Repository: {repo or '(none)'}",
            f"Latest deployment: {data.get('latestDeployment', {}).get('url', '?')}",
            f"Environment variables: {len(env_vars)}",
        ]
        return "\n".join(lines)

    @make_tool(
        name="vercel_get_domain_records",
        description="List DNS records for a domain configured on Vercel",
        input_schema={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Domain name"},
            },
            "required": ["domain"],
        },
    )
    def vercel_get_domain_records(domain: str) -> str:
        data = _vercel_get(f"domains/{domain}/records")
        records = data.get("records", []) if isinstance(data, dict) else []
        if not records:
            return f"No DNS records found for {domain}."
        lines: list[str] = []
        for rec in records:
            name = rec.get("name", "@")
            rec_type = rec.get("type", "?")
            value = rec.get("value", "?")
            lines.append(f"{name}  {rec_type}  {value}")
        return f"DNS records for {domain}:\n" + "\n".join(lines)

    TOOLS: list = [
        vercel_list_deployments,
        vercel_get_deployment,
        vercel_list_projects,
        vercel_get_project,
        vercel_get_domain_records,
    ]

else:
    TOOLS = []


def main() -> None:
    server = MCPServer(name="vercel", version="1.0.0", tools=TOOLS)
    server.run()


if __name__ == "__main__":
    main()
