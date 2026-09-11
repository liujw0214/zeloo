"""Jira MCP server — exposes Jira Cloud REST API as MCP tools over stdio JSON-RPC."""

from __future__ import annotations

import base64
import os

from optional_mcps.base import MCPServer, make_tool

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


def _get_jira_headers() -> dict[str, str]:
    base_url = os.environ.get("JIRA_BASE_URL", "")
    email = os.environ.get("JIRA_EMAIL", "")
    api_token = os.environ.get("JIRA_API_TOKEN", "")
    auth_str = f"{email}:{api_token}"
    auth_bytes = auth_str.encode("ascii")
    auth_b64 = base64.b64encode(auth_bytes).decode("ascii")
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    return headers, base_url


def _jira_get(path: str, params: dict | None = None) -> dict:
    headers, base_url = _get_jira_headers()
    url = f"{base_url.rstrip('/')}/rest/api/3/{path.lstrip('/')}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=headers, params=params or {})
        resp.raise_for_status()
        return resp.json()


def _jira_post(path: str, data: dict) -> dict:
    headers, base_url = _get_jira_headers()
    url = f"{base_url.rstrip('/')}/rest/api/3/{path.lstrip('/')}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, json=data)
        resp.raise_for_status()
        return resp.json()


def _jira_put(path: str, data: dict) -> dict:
    headers, base_url = _get_jira_headers()
    url = f"{base_url.rstrip('/')}/rest/api/3/{path.lstrip('/')}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.put(url, headers=headers, json=data)
        resp.raise_for_status()
        return resp.json()


def _format_issue(issue: dict) -> str:
    fields = issue.get("fields", {})
    assignee = fields.get("assignee", {})
    reporter = fields.get("reporter", {})
    if isinstance(assignee, dict):
        assignee_name = assignee.get("displayName", "Unassigned")
    else:
        assignee_name = "Unassigned"
    if isinstance(reporter, dict):
        reporter_name = reporter.get("displayName", "Unknown")
    else:
        reporter_name = "Unknown"
    status = fields.get("status", {})
    if isinstance(status, dict):
        status_name = status.get("name", "unknown")
    else:
        status_name = "unknown"
    return (
        f"Key: {issue.get('key', 'unknown')}\n"
        f"Summary: {fields.get('summary', 'No summary')}\n"
        f"Status: {status_name}\n"
        f"Assignee: {assignee_name}\n"
        f"Reporter: {reporter_name}"
    )


def _format_project(project: dict) -> str:
    lead = project.get("lead", {})
    lead_name = lead.get("displayName", "No lead") if isinstance(lead, dict) else "No lead"
    return (
        f"Key: {project.get('key', 'unknown')}\n"
        f"Name: {project.get('name', 'unknown')}\n"
        f"Lead: {lead_name}\n"
        f"Type: {project.get('projectTypeKey', 'unknown')}"
    )


if _HTTPX_AVAILABLE:

    @make_tool(
        name="jira_search_issues",
        description="Search issues using JQL",
        input_schema={
            "type": "object",
            "properties": {
                "jql": {"type": "string", "description": "JQL query string"},
                "max_results": {"type": "integer", "default": 20},
            },
            "required": ["jql"],
        },
    )
    def jira_search_issues(jql: str, max_results: int = 20) -> str:
        data = _jira_get("search", {"jql": jql, "maxResults": max_results})
        issues = data.get("issues", [])
        if not issues:
            return "No issues found."
        return "\n\n---\n\n".join(_format_issue(i) for i in issues)

    @make_tool(
        name="jira_get_issue",
        description="Get details of a specific issue",
        input_schema={
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "Issue key (e.g. PROJ-123)"},
            },
            "required": ["issue_key"],
        },
    )
    def jira_get_issue(issue_key: str) -> str:
        data = _jira_get(f"issue/{issue_key}")
        fields = data.get("fields", {})
        assignee = fields.get("assignee", {})
        reporter = fields.get("reporter", {})
        if isinstance(assignee, dict):
            assignee_name = assignee.get("displayName", "Unassigned")
        else:
            assignee_name = "Unassigned"
        if isinstance(reporter, dict):
            reporter_name = reporter.get("displayName", "Unknown")
        else:
            reporter_name = "Unknown"
        description = fields.get("description", {})
        desc_text = ""
        if isinstance(description, dict):
            desc_text = description.get("content", [{"text": ""}][0].get("text", ""))
        elif isinstance(description, str):
            desc_text = description
        status = fields.get("status", {})
        if isinstance(status, dict):
            status_name = status.get("name", "unknown")
        else:
            status_name = "unknown"
        return (
            f"Key: {data.get('key', 'unknown')}\n"
            f"Summary: {fields.get('summary', 'No summary')}\n"
            f"Status: {status_name}\n"
            f"Description: {desc_text[:500] if desc_text else '(no description)'}\n"
            f"Assignee: {assignee_name}\n"
            f"Reporter: {reporter_name}\n"
            f"Created: {fields.get('created', 'unknown')}\n"
            f"Updated: {fields.get('updated', 'unknown')}"
        )

    @make_tool(
        name="jira_create_issue",
        description="Create a new issue",
        input_schema={
            "type": "object",
            "properties": {
                "project_key": {"type": "string", "description": "Project key (e.g. PROJ)"},
                "summary": {"type": "string", "description": "Issue summary/title"},
                "description": {"type": "string", "description": "Issue description"},
                "issue_type": {"type": "string", "default": "Task"},
            },
            "required": ["project_key", "summary"],
        },
    )
    def jira_create_issue(
        project_key: str, summary: str, description: str = "", issue_type: str = "Task"
    ) -> str:
        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": description or " "}],
                        }
                    ],
                },
                "issuetype": {"name": issue_type},
            }
        }
        result = _jira_post("issue", payload)
        return (
            f"Issue created successfully!\n"
            f"Key: {result.get('key', 'unknown')}\n"
            f"ID: {result.get('id', 'unknown')}"
        )

    @make_tool(
        name="jira_update_issue",
        description="Update an issue's status or assignee",
        input_schema={
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "Issue key (e.g. PROJ-123)"},
                "status": {"type": "string", "description": "New status name"},
                "assignee": {"type": "string", "description": "New assignee display name"},
            },
            "required": ["issue_key"],
        },
    )
    def jira_update_issue(issue_key: str, status: str = "", assignee: str = "") -> str:
        fields: dict[str, object] = {}
        if status:
            fields["status"] = {"name": status}
        if assignee:
            fields["assignee"] = {"name": assignee}
        payload = {"fields": fields} if fields else {}
        if not payload:
            return f"No updates provided for {issue_key}"
        _jira_put(f"issue/{issue_key}", payload)
        return f"Issue {issue_key} updated successfully!"

    @make_tool(
        name="jira_list_projects",
        description="List all projects",
        input_schema={
            "type": "object",
            "properties": {},
        },
    )
    def jira_list_projects() -> str:
        data = _jira_get("project")
        projects = data if isinstance(data, list) else []
        if not projects:
            return "No projects found."
        return "\n\n---\n\n".join(_format_project(p) for p in projects)

    TOOLS: list = [
        jira_search_issues,
        jira_get_issue,
        jira_create_issue,
        jira_update_issue,
        jira_list_projects,
    ]

else:
    TOOLS = []


def main() -> None:
    server = MCPServer(name="jira", version="1.0.0", tools=TOOLS)
    server.run()


if __name__ == "__main__":
    main()
