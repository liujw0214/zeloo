"""GitLab MCP server — exposes GitLab REST API as MCP tools over stdio JSON-RPC.

GitLab API reference: https://docs.gitlab.com/ee/api/

Supported tools:
- list_projects        — List visible projects
- get_project          — Get a single project by ID or path
- list_issues          — List project issues with filtering
- create_issue         — Create a new issue
- update_issue         — Update an issue
- list_merge_requests  — List merge requests
- create_mr            — Create a merge request
- list_files           — List repository tree
- read_file            — Get file content
- create_file          — Create a new file
- update_file          — Update an existing file
- list_pipelines       — List CI/CD pipelines
- trigger_pipeline     — Trigger a pipeline run
"""

from __future__ import annotations

import base64
import os
from typing import Any

from optional_mcps.base import MCPServer, make_tool

try:
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _HTTPX_AVAILABLE = False

GITLAB_API_BASE = "https://gitlab.com/api/v4"


def _get_url(path: str) -> str:
    return f"{GITLAB_API_BASE}/{path.lstrip('/')}"


def _get_headers() -> dict[str, str]:
    token = os.environ.get("GITLAB_API_KEY", "")
    return {
        "PRIVATE-TOKEN": token,
        "Content-Type": "application/json",
    }


def _fmt_issue(issue: dict) -> str:
    labels = issue.get("labels", [])
    return (
        f"[#{issue['iid']}] {issue['title']}\n"
        f"  state={issue['state']}  author={issue['author']['username']}\n"
        f"  labels={labels}\n"
        f"  {issue.get('web_url','')}"
    )


def _fmt_mr(mr: dict) -> str:
    return (
        f"!{mr['iid']} {mr['title']}\n"
        f"  state={mr['state']}  author={mr['author']['username']}\n"
        f"  {mr.get('web_url','')}"
    )


class GitLabServer(MCPServer):
    name = "gitlab"
    version = "1.0.0"

    if _HTTPX_AVAILABLE:

        @make_tool(
            name="gitlab_list_projects",
            description="List visible GitLab projects",
            input_schema={
                "type": "object",
                "properties": {
                    "membership": {"type": "boolean", "default": True},
                    "page": {"type": "integer", "default": 1},
                    "per_page": {"type": "integer", "default": 20},
                },
            },
        )
        def gitlab_list_projects(
            self, membership: bool = True, page: int = 1, per_page: int = 20
        ) -> str:
            headers = _get_headers()
            params = {"membership": membership, "page": page, "per_page": per_page}
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(_get_url("projects"), headers=headers, params=params)
                resp.raise_for_status()
                projects: list[dict] = resp.json()
            if not projects:
                return "No projects found."
            lines = [
                f"{p['id']}  {p['path_with_namespace']}  ({p['visibility']})"
                for p in projects
            ]
            return "Projects:\n" + "\n".join(lines)

        @make_tool(
            name="gitlab_get_project",
            description="Get a single project by ID or namespace/path",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                },
                "required": ["project_id"],
            },
        )
        def gitlab_get_project(self, project_id: str) -> str:
            headers = _get_headers()
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(_get_url(f"projects/{project_id}"), headers=headers)
                resp.raise_for_status()
                p = resp.json()
            return (
                f"Project: {p['path_with_namespace']}\n"
                f"  id={p['id']}  visibility={p['visibility']}\n"
                f"  default_branch={p.get('default_branch','?')}\n"
                f"  {p.get('web_url','')}"
            )

        @make_tool(
            name="gitlab_list_issues",
            description="List project issues with optional state/label filtering",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "state": {"type": "string", "default": "opened"},
                    "labels": {"type": "string"},
                    "per_page": {"type": "integer", "default": 20},
                },
                "required": ["project_id"],
            },
        )
        def gitlab_list_issues(
            self,
            project_id: str,
            state: str = "opened",
            labels: str | None = None,
            per_page: int = 20,
        ) -> str:
            headers = _get_headers()
            params: dict[str, Any] = {"state": state, "per_page": per_page}
            if labels:
                params["labels"] = labels
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    _get_url(f"projects/{project_id}/issues"), headers=headers, params=params
                )
                resp.raise_for_status()
                issues: list[dict] = resp.json()
            if not issues:
                return "No issues found."
            return "Issues:\n\n" + "\n\n".join(_fmt_issue(i) for i in issues)

        @make_tool(
            name="gitlab_create_issue",
            description="Create a new issue in a project",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["project_id", "title"],
            },
        )
        def gitlab_create_issue(
            self,
            project_id: str,
            title: str,
            description: str = "",
            labels: list[str] | None = None,
        ) -> str:
            headers = _get_headers()
            payload: dict[str, Any] = {"title": title}
            if description:
                payload["description"] = description
            if labels:
                payload["labels"] = ",".join(labels)
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    _get_url(f"projects/{project_id}/issues"),
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                issue: dict = resp.json()
            return "Created: " + _fmt_issue(issue)

        @make_tool(
            name="gitlab_list_merge_requests",
            description="List merge requests for a project",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "state": {"type": "string", "default": "opened"},
                    "per_page": {"type": "integer", "default": 20},
                },
                "required": ["project_id"],
            },
        )
        def gitlab_list_merge_requests(
            self, project_id: str, state: str = "opened", per_page: int = 20
        ) -> str:
            headers = _get_headers()
            params = {"state": state, "per_page": per_page}
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    _get_url(f"projects/{project_id}/merge_requests"),
                    headers=headers,
                    params=params,
                )
                resp.raise_for_status()
                mrs: list[dict] = resp.json()
            if not mrs:
                return "No merge requests found."
            return "Merge Requests:\n\n" + "\n\n".join(_fmt_mr(mr) for mr in mrs)

        @make_tool(
            name="gitlab_list_files",
            description="List repository file tree",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "path": {"type": "string", "default": ""},
                    "ref": {"type": "string", "default": "main"},
                },
                "required": ["project_id"],
            },
        )
        def gitlab_list_files(
            self, project_id: str, path: str = "", ref: str = "main"
        ) -> str:
            headers = _get_headers()
            params = {"ref": ref}
            if path:
                params["path"] = path
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    _get_url(f"projects/{project_id}/repository/tree"),
                    headers=headers,
                    params=params,
                )
                resp.raise_for_status()
                tree: list[dict] = resp.json()
            if not tree:
                return "Repository is empty or path not found."
            lines = [f"{f['type'][0]}  {f['path']}" for f in tree]
            return "Repository tree:\n" + "\n".join(lines)

        @make_tool(
            name="gitlab_read_file",
            description="Get the content of a file from the repository",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "file_path": {"type": "string"},
                    "ref": {"type": "string", "default": "main"},
                },
                "required": ["project_id", "file_path"],
            },
        )
        def gitlab_read_file(
            self, project_id: str, file_path: str, ref: str = "main"
        ) -> str:
            headers = _get_headers()
            params = {"ref": ref}
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    _get_url(f"projects/{project_id}/repository/files/{file_path}"),
                    headers=headers,
                    params=params,
                )
                resp.raise_for_status()
                data: dict = resp.json()
            content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
            return f"File: {file_path}\n\n{content}"

        @make_tool(
            name="gitlab_create_file",
            description="Create a new file in the repository",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                    "branch": {"type": "string", "default": "main"},
                    "commit_message": {"type": "string"},
                },
                "required": ["project_id", "file_path", "content", "commit_message"],
            },
        )
        def gitlab_create_file(
            self,
            project_id: str,
            file_path: str,
            content: str,
            commit_message: str,
            branch: str = "main",
        ) -> str:
            headers = _get_headers()
            payload = {
                "branch": branch,
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "commit_message": commit_message,
            }
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    _get_url(f"projects/{project_id}/repository/files/{file_path}"),
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
            return f"Created file {file_path}: {data.get('file_path', file_path)}"

        @make_tool(
            name="gitlab_list_pipelines",
            description="List CI/CD pipelines for a project",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "per_page": {"type": "integer", "default": 20},
                },
                "required": ["project_id"],
            },
        )
        def gitlab_list_pipelines(
            self, project_id: str, per_page: int = 20
        ) -> str:
            headers = _get_headers()
            params = {"per_page": per_page}
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    _get_url(f"projects/{project_id}/pipelines"),
                    headers=headers,
                    params=params,
                )
                resp.raise_for_status()
                pipelines: list[dict] = resp.json()
            if not pipelines:
                return "No pipelines found."
            lines = [
                f"#{p['id']}  {p['status']}  ref={p.get('ref','?')}  {p.get('web_url','')}"
                for p in pipelines
            ]
            return "Pipelines:\n" + "\n".join(lines)

        @make_tool(
            name="gitlab_trigger_pipeline",
            description="Trigger a CI/CD pipeline run on a branch or tag",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "ref": {"type": "string"},
                },
                "required": ["project_id", "ref"],
            },
        )
        def gitlab_trigger_pipeline(
            self, project_id: str, ref: str
        ) -> str:
            headers = _get_headers()
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    _get_url(f"projects/{project_id}/pipeline"),
                    headers=headers,
                    json={"ref": ref},
                )
                resp.raise_for_status()
                pipeline: dict = resp.json()
            return (
                f"Pipeline triggered: #{pipeline['id']}\n"
                f"  status={pipeline['status']}  ref={pipeline['ref']}\n"
                f"  {pipeline.get('web_url','')}"
            )

        TOOLS = [
            gitlab_list_projects,
            gitlab_get_project,
            gitlab_list_issues,
            gitlab_create_issue,
            gitlab_list_merge_requests,
            gitlab_list_files,
            gitlab_read_file,
            gitlab_create_file,
            gitlab_list_pipelines,
            gitlab_trigger_pipeline,
        ]
    else:
        TOOLS = []


server = GitLabServer(name="gitlab", version="1.0.0")
server.tools = GitLabServer.TOOLS
if __name__ == "__main__":
    server.run()
