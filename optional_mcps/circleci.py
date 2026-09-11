"""CircleCI MCP server — exposes CircleCI API v2 as MCP tools over stdio JSON-RPC."""

from __future__ import annotations

import os

from optional_mcps.base import MCPServer, make_tool

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


CIRCLECI_BASE_URL = "https://circleci.com/api/v2"


def _circleci_get(path: str, params: dict | None = None) -> dict | list:
    token = os.environ.get("CIRCLECI_TOKEN", "")
    url = f"{CIRCLECI_BASE_URL}/{path.lstrip('/')}"
    headers = {"Circle-Token": token}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=headers, params=params or {})
        resp.raise_for_status()
        return resp.json()


def _circleci_post(path: str, data: dict | None = None) -> dict:
    token = os.environ.get("CIRCLECI_TOKEN", "")
    url = f"{CIRCLECI_BASE_URL}/{path.lstrip('/')}"
    headers = {"Circle-Token": token}
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, json=data or {})
        resp.raise_for_status()
        return resp.json()


def _format_project(project: dict) -> str:
    vcs_url = project.get("vcs_url", "unknown")
    reponame = project.get("username", "") + "/" + project.get("reponame", "")
    default_branch = project.get("default_branch", "unknown")
    last_built = project.get("last_built", "never")
    return (
        f"VCS URL: {vcs_url}\n"
        f"Project: {reponame}\n"
        f"Default Branch: {default_branch}\n"
        f"Last Built: {last_built}"
    )


def _format_pipeline(pipeline: dict) -> str:
    return (
        f"ID: {pipeline.get('id', 'unknown')}\n"
        f"Number: {pipeline.get('number', '?')}\n"
        f"State: {pipeline.get('state', 'unknown')}\n"
        f"Created At: {pipeline.get('created_at', 'unknown')}"
    )


if _HTTPX_AVAILABLE:

    @make_tool(
        name="circleci_list_projects",
        description="List all projects the token has access to",
        input_schema={
            "type": "object",
            "properties": {},
        },
    )
    def circleci_list_projects() -> str:
        data = _circleci_get("project")
        projects = data if isinstance(data, list) else data.get("items", [])
        if not projects:
            return "No projects found."
        return "\n\n---\n\n".join(_format_project(p) for p in projects)

    @make_tool(
        name="circleci_list_pipelines",
        description="List pipelines for a project",
        input_schema={
            "type": "object",
            "properties": {
                "vcs": {
                    "type": "string",
                    "description": "VCS provider (gh or bb)",
                    "default": "gh",
                },
                "username": {"type": "string", "description": "Username or organization"},
                "project": {"type": "string", "description": "Project name"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["username", "project"],
        },
    )
    def circleci_list_pipelines(
        username: str, project: str, vcs: str = "gh", max_results: int = 10
    ) -> str:
        path = f"project/{vcs}/{username}/{project}/pipeline"
        data = _circleci_get(path, {"page-token": ""})
        items = data.get("items", []) if isinstance(data, dict) else data
        items = items[:max_results]
        if not items:
            return "No pipelines found."
        lines = []
        for p in items:
            trigger = p.get("trigger", {})
            if isinstance(trigger, dict):
                triggered_by = trigger.get("type", "unknown")
            else:
                triggered_by = "unknown"
            lines.append(
                f"ID: {p.get('id', '?')} | Number: {p.get('number', '?')} | "
                f"State: {p.get('state', '?')} | Triggered by: {triggered_by} | "
                f"Created: {p.get('created_at', '?')}"
            )
        return "\n".join(lines)

    @make_tool(
        name="circleci_trigger_pipeline",
        description="Trigger a new pipeline for a project",
        input_schema={
            "type": "object",
            "properties": {
                "vcs": {
                    "type": "string",
                    "description": "VCS provider (gh or bb)",
                    "default": "gh",
                },
                "username": {"type": "string", "description": "Username or organization"},
                "project": {"type": "string", "description": "Project name"},
                "branch": {"type": "string", "description": "Branch to trigger", "default": "main"},
            },
            "required": ["username", "project"],
        },
    )
    def circleci_trigger_pipeline(
        username: str, project: str, vcs: str = "gh", branch: str = "main"
    ) -> str:
        path = f"project/{vcs}/{username}/{project}/pipeline"
        data = _circleci_post(path, {"branch": branch})
        return (
            f"Pipeline triggered successfully!\n"
            f"ID: {data.get('id', 'unknown')}\n"
            f"Number: {data.get('number', 'unknown')}"
        )

    @make_tool(
        name="circleci_list_workflows",
        description="List jobs for a workflow",
        input_schema={
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Workflow ID"},
            },
            "required": ["workflow_id"],
        },
    )
    def circleci_list_workflows(workflow_id: str) -> str:
        data = _circleci_get(f"workflow/{workflow_id}/job")
        items = data.get("items", []) if isinstance(data, dict) else data
        if not items:
            return "No jobs found."
        lines = []
        for job in items:
            started = job.get("started_at", "N/A")
            stopped = job.get("stopped_at", "running")
            duration = ""
            if started and stopped:
                try:
                    from datetime import datetime
                    fmt = "%Y-%m-%dT%H:%M:%SZ"
                    s = datetime.strptime(started[:19], fmt)
                    e = datetime.strptime(stopped[:19], fmt)
                    duration = f" ({int((e - s).total_seconds())}s)"
                except Exception:
                    duration = ""
            lines.append(
                f"Job: {job.get('name', '?')} | ID: {job.get('id', '?')} | "
                f"Status: {job.get('status', '?')} | Duration: {stopped}{duration}"
            )
        return "\n".join(lines)

    @make_tool(
        name="circleci_get_pipeline",
        description="Get details of a pipeline",
        input_schema={
            "type": "object",
            "properties": {
                "pipeline_id": {"type": "string", "description": "Pipeline ID"},
            },
            "required": ["pipeline_id"],
        },
    )
    def circleci_get_pipeline(pipeline_id: str) -> str:
        data = _circleci_get(f"pipeline/{pipeline_id}")
        if not data:
            return "Pipeline not found."
        trigger = data.get("trigger", {})
        if isinstance(trigger, dict):
            trigger_type = trigger.get("type", "unknown")
        else:
            trigger_type = "unknown"
        return (
            f"ID: {data.get('id', 'unknown')}\n"
            f"State: {data.get('state', 'unknown')}\n"
            f"Created At: {data.get('created_at', 'unknown')}\n"
            f"Trigger: {trigger_type}"
        )

    TOOLS: list = [
        circleci_list_projects,
        circleci_list_pipelines,
        circleci_trigger_pipeline,
        circleci_list_workflows,
        circleci_get_pipeline,
    ]

else:
    TOOLS = []


def main() -> None:
    server = MCPServer(name="circleci", version="1.0.0", tools=TOOLS)
    server.run()


if __name__ == "__main__":
    main()
