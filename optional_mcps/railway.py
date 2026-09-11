"""Railway MCP server — exposes Railway API v1 as MCP tools over stdio JSON-RPC."""

from __future__ import annotations

import os

from optional_mcps.base import MCPServer, make_tool

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


RAILWAY_BASE_URL = "https://backboard.railway.app/api/v1"


def _railway_get(path: str, params: dict | None = None) -> dict | list:
    token = os.environ.get("RAILWAY_TOKEN", "")
    url = f"{RAILWAY_BASE_URL}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=headers, params=params or {})
        resp.raise_for_status()
        return resp.json()


def _railway_post(path: str, data: dict | None = None) -> dict:
    token = os.environ.get("RAILWAY_TOKEN", "")
    url = f"{RAILWAY_BASE_URL}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, json=data or {})
        resp.raise_for_status()
        return resp.json()


def _format_project(project: dict) -> str:
    return (
        f"ID: {project.get('id', 'unknown')}\n"
        f"Name: {project.get('name', 'unknown')}\n"
        f"Description: {project.get('description', 'No description')}\n"
        f"Created At: {project.get('createdAt', 'unknown')}"
    )


def _format_deployment(deployment: dict) -> str:
    return (
        f"ID: {deployment.get('id', '?')} | "
        f"Status: {deployment.get('status', '?')} | "
        f"Service: {deployment.get('serviceName', '?')} | "
        f"Environment: {deployment.get('environment', '?')} | "
        f"Created: {deployment.get('createdAt', '?')}"
    )


if _HTTPX_AVAILABLE:

    @make_tool(
        name="railway_list_projects",
        description="List all Railway projects",
        input_schema={
            "type": "object",
            "properties": {},
        },
    )
    def railway_list_projects() -> str:
        data = _railway_get("project")
        projects = data if isinstance(data, list) else data.get("projects", [])
        if not projects:
            return "No projects found."
        return "\n\n---\n\n".join(_format_project(p) for p in projects)

    @make_tool(
        name="railway_get_project",
        description="Get details of a specific project",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
            },
            "required": ["project_id"],
        },
    )
    def railway_get_project(project_id: str) -> str:
        data = _railway_get(f"project/{project_id}")
        environments = data.get("environments", [])
        services = data.get("services", [])
        env_names = ", ".join(e.get("name", "?") for e in environments) or "None"
        service_names = ", ".join(s.get("name", "?") for s in services) or "None"
        return (
            f"Name: {data.get('name', 'unknown')}\n"
            f"ID: {data.get('id', 'unknown')}\n"
            f"Description: {data.get('description', 'No description')}\n"
            f"Environments: {env_names}\n"
            f"Services: {service_names}"
        )

    @make_tool(
        name="railway_list_deployments",
        description="List deployments for a project",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["project_id"],
        },
    )
    def railway_list_deployments(project_id: str, max_results: int = 10) -> str:
        data = _railway_get(f"project/{project_id}/deployment")
        deployments = data if isinstance(data, list) else data.get("deployments", [])
        deployments = deployments[:max_results]
        if not deployments:
            return "No deployments found."
        return "\n".join(_format_deployment(d) for d in deployments)

    @make_tool(
        name="railway_get_deployment",
        description="Get details of a specific deployment",
        input_schema={
            "type": "object",
            "properties": {
                "deployment_id": {"type": "string", "description": "Deployment ID"},
            },
            "required": ["deployment_id"],
        },
    )
    def railway_get_deployment(deployment_id: str) -> str:
        data = _railway_get(f"deployment/{deployment_id}")
        metadata = data.get("metadata", {})
        if isinstance(metadata, dict):
            logs_url = metadata.get("logsUrl", "N/A")
        else:
            logs_url = "N/A"
        return (
            f"ID: {data.get('id', 'unknown')}\n"
            f"Status: {data.get('status', 'unknown')}\n"
            f"Service: {data.get('serviceName', 'unknown')}\n"
            f"Environment: {data.get('environment', 'unknown')}\n"
            f"Logs URL: {logs_url}\n"
            f"Created At: {data.get('createdAt', 'unknown')}"
        )

    @make_tool(
        name="railway_trigger_deployment",
        description="Trigger a new deployment for a service",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "service_id": {"type": "string", "description": "Service ID"},
            },
            "required": ["project_id", "service_id"],
        },
    )
    def railway_trigger_deployment(project_id: str, service_id: str) -> str:
        data = _railway_post(f"project/{project_id}/service/{service_id}/deploy")
        return (
            f"Deployment triggered!\n"
            f"ID: {data.get('id', 'unknown')}\n"
            f"Status: {data.get('status', 'unknown')}"
        )

    TOOLS: list = [
        railway_list_projects,
        railway_get_project,
        railway_list_deployments,
        railway_get_deployment,
        railway_trigger_deployment,
    ]

else:
    TOOLS = []


def main() -> None:
    server = MCPServer(name="railway", version="1.0.0", tools=TOOLS)
    server.run()


if __name__ == "__main__":
    main()
