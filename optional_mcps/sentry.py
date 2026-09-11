"""Sentry MCP server — exposes Sentry error tracking API as MCP tools over stdio JSON-RPC."""

from __future__ import annotations

import os

from optional_mcps.base import MCPServer, make_tool

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


SENTRY_API_BASE = "https://sentry.io/api/0"


def _sentry_get(path: str, params: dict | None = None) -> dict | list:
    token = os.environ.get("SENTRY_AUTH_TOKEN", "")
    url = SENTRY_API_BASE + path
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=headers, params=params or {})
        resp.raise_for_status()
        return resp.json()


def _sentry_post(path: str, payload: dict) -> dict:
    token = os.environ.get("SENTRY_AUTH_TOKEN", "")
    url = SENTRY_API_BASE + path
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


def _fmt_issue(issue: dict) -> str:
    sid = issue.get("id", "?")
    title = issue.get("title", "(no title)")
    culprit = issue.get("culprit", "?")
    count = issue.get("count", 0)
    user_count = issue.get("userCount", 0)
    status = issue.get("status", "unresolved")
    level = issue.get("level", "error")
    last_seen = issue.get("lastSeen", "?")
    permalink = issue.get("permalink", "?")
    return (
        f"[{sid}] {title}\n"
        f"Culprit: {culprit}\n"
        f"Level: {level} | Status: {status}\n"
        f"Events: {count} | Users: {user_count}\n"
        f"Last seen: {last_seen}\n"
        f"URL: {permalink}"
    )


def _fmt_event(event: dict) -> str:
    event_id = event.get("eventID", event.get("id", "?"))
    title = event.get("title", "(no title)")
    message = event.get("message", "")
    level = event.get("level", "error")
    timestamp = event.get("dateCreated", "?")
    return (
        f"Event {event_id}\n"
        f"Title: {title}\n"
        f"Message: {message[:200]}\n"
        f"Level: {level} | Timestamp: {timestamp}"
    )


def _fmt_project(project: dict) -> str:
    name = project.get("name", "?")
    slug = project.get("slug", "?")
    platform = project.get("platform", "?")
    return f"- {name} ({platform}) | slug: {slug}"


if _HTTPX_AVAILABLE:

    @make_tool(
        name="sentry_list_issues",
        description="List issues in a Sentry project",
        input_schema={
            "type": "object",
            "properties": {
                "organization_slug": {"type": "string", "description": "Organization slug"},
                "project_slug": {"type": "string", "description": "Project slug"},
                "max_results": {"type": "integer", "default": 20},
                "query": {
                    "type": "string",
                    "description": "Sentry search query (e.g. 'is:unresolved')",
                    "default": "is:unresolved",
                },
            },
            "required": ["organization_slug", "project_slug"],
        },
    )
    def sentry_list_issues(
        organization_slug: str,
        project_slug: str,
        max_results: int = 20,
        query: str = "is:unresolved",
    ) -> str:
        params = {"query": query, "limit": max_results}
        path = f"/projects/{organization_slug}/{project_slug}/issues/"
        data = _sentry_get(path, params)
        issues = data if isinstance(data, list) else []
        if not issues:
            return f"No issues found for {project_slug}"
        return "\n\n".join(_fmt_issue(i) for i in issues)

    @make_tool(
        name="sentry_get_issue",
        description="Get details of a specific issue",
        input_schema={
            "type": "object",
            "properties": {
                "organization_slug": {"type": "string"},
                "issue_id": {"type": "string", "description": "Issue ID or short ID"},
            },
            "required": ["organization_slug", "issue_id"],
        },
    )
    def sentry_get_issue(organization_slug: str, issue_id: str) -> str:
        path = f"/issues/{issue_id}/"
        data = _sentry_get(path)
        if isinstance(data, list) and data:
            data = data[0]
        return _fmt_issue(data)

    @make_tool(
        name="sentry_list_events",
        description="List recent events for an issue",
        input_schema={
            "type": "object",
            "properties": {
                "organization_slug": {"type": "string"},
                "issue_id": {"type": "string"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["organization_slug", "issue_id"],
        },
    )
    def sentry_list_events(
        organization_slug: str, issue_id: str, max_results: int = 10
    ) -> str:
        path = f"/issues/{issue_id}/events/"
        data = _sentry_get(path, {"limit": max_results})
        events = data if isinstance(data, list) else []
        if not events:
            return f"No events found for issue {issue_id}"
        return "\n\n---\n\n".join(_fmt_event(e) for e in events)

    @make_tool(
        name="sentry_list_projects",
        description="List projects in an organization",
        input_schema={
            "type": "object",
            "properties": {
                "organization_slug": {"type": "string"},
                "max_results": {"type": "integer", "default": 20},
            },
            "required": ["organization_slug"],
        },
    )
    def sentry_list_projects(
        organization_slug: str, max_results: int = 20
    ) -> str:
        path = f"/organizations/{organization_slug}/projects/"
        data = _sentry_get(path, {"limit": max_results})
        projects = data if isinstance(data, list) else []
        if not projects:
            return f"No projects in {organization_slug}"
        return f"{len(projects)} project(s):\n" + "\n".join(
            _fmt_project(p) for p in projects
        )

    @make_tool(
        name="sentry_resolve_issue",
        description="Mark an issue as resolved",
        input_schema={
            "type": "object",
            "properties": {
                "organization_slug": {"type": "string"},
                "issue_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "default": "resolved",
                    "description": "resolved, unresolved, ignored",
                },
            },
            "required": ["organization_slug", "issue_id"],
        },
    )
    def sentry_resolve_issue(
        organization_slug: str, issue_id: str, status: str = "resolved"
    ) -> str:
        path = f"/issues/{issue_id}/"
        payload = {"status": status}
        result = _sentry_post(path, payload)
        new_status = result.get("status", "?")
        return f"Issue {issue_id} set to status: {new_status}"

    TOOLS: list = [
        sentry_list_issues,
        sentry_get_issue,
        sentry_list_events,
        sentry_list_projects,
        sentry_resolve_issue,
    ]

else:
    TOOLS = []


def main() -> None:
    server = MCPServer(name="sentry", version="1.0.0", tools=TOOLS)
    server.run()


if __name__ == "__main__":
    main()