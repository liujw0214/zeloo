"""GitHub MCP server — exposes GitHub API as MCP tools over stdio JSON-RPC."""

from __future__ import annotations

import os

from optional_mcps.base import MCPServer, make_tool

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


def _get_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _gh_get(path: str, params: dict | None = None) -> dict | list:
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    headers = _get_headers()
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()


def _format_repo(repo: dict) -> str:
    return (
        f"Repository: {repo.get('full_name', 'unknown')}\n"
        f"Description: {repo.get('description', '(no description)')}\n"
        f"Stars: {repo.get('stargazers_count', 0)} | "
        f"Forks: {repo.get('forks_count', 0)} | "
        f"Language: {repo.get('language', 'N/A')}\n"
        f"URL: {repo.get('html_url', 'N/A')}"
    )


def _format_issue(issue: dict) -> str:
    labels = ", ".join(lb.get("name", "") for lb in issue.get("labels", []))
    labels_str = f" | Labels: {labels}" if labels else ""
    return (
        f"#{issue.get('number', '?')} {issue.get('title', 'unknown')}\n"
        f"Status: {issue.get('state', 'unknown')}{labels_str}\n"
        f"Author: {issue.get('user', {}).get('login', 'unknown')}\n"
        f"URL: {issue.get('html_url', 'N/A')}\n"
        f"Body: {issue.get('body', '(no body)')[:300]}"
    )


def _format_pr(pr: dict) -> str:
    return (
        f"#{pr.get('number', '?')} {pr.get('title', 'unknown')}\n"
        f"Status: {pr.get('state', 'unknown')} | "
        f"Author: {pr.get('user', {}).get('login', 'unknown')}\n"
        f"URL: {pr.get('html_url', 'N/A')}\n"
        f"Body: {pr.get('body', '(no body)')[:300]}"
    )


if _HTTPX_AVAILABLE:

    @make_tool(
        name="github_search_repos",
        description="Search GitHub repositories by keyword",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'Zeloo agent python')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    )
    def github_search_repos(query: str, max_results: int = 5) -> str:
        data = _gh_get("search/repositories", {"q": query, "per_page": max_results})
        items = data.get("items", [])
        if not items:
            return "No repositories found."
        return "\n\n---\n\n".join(_format_repo(r) for r in items)

    @make_tool(
        name="github_get_repo",
        description="Get details of a specific repository",
        input_schema={
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repository owner"},
                "repo": {"type": "string", "description": "Repository name"},
            },
            "required": ["owner", "repo"],
        },
    )
    def github_get_repo(owner: str, repo: str) -> str:
        data = _gh_get(f"repos/{owner}/{repo}")
        return _format_repo(data)

    @make_tool(
        name="github_list_issues",
        description="List issues in a repository",
        input_schema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "state": {"type": "string", "description": "open/closed/all", "default": "open"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["owner", "repo"],
        },
    )
    def github_list_issues(
        owner: str, repo: str, state: str = "open", max_results: int = 10
    ) -> str:
        params = {"state": state, "per_page": max_results}
        data = _gh_get(f"repos/{owner}/{repo}/issues", params)
        issues = [i for i in data if not i.get("pull_request")]
        if not issues:
            return f"No {state} issues found."
        return "\n\n---\n\n".join(_format_issue(i) for i in issues)

    @make_tool(
        name="github_get_issue",
        description="Get a single issue or pull request by number",
        input_schema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "number": {"type": "integer"},
            },
            "required": ["owner", "repo", "number"],
        },
    )
    def github_get_issue(owner: str, repo: str, number: int) -> str:
        data = _gh_get(f"repos/{owner}/{repo}/issues/{number}")
        if "pull_request" in data:
            return _format_pr(data)
        return _format_issue(data)

    @make_tool(
        name="github_list_prs",
        description="List pull requests in a repository",
        input_schema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "state": {"type": "string", "default": "open"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["owner", "repo"],
        },
    )
    def github_list_prs(owner: str, repo: str, state: str = "open", max_results: int = 10) -> str:
        data = _gh_get(f"repos/{owner}/{repo}/pulls", {"state": state, "per_page": max_results})
        if not data:
            return f"No {state} pull requests found."
        return "\n\n---\n\n".join(_format_pr(pr) for pr in data)

    @make_tool(
        name="github_create_issue",
        description="Create a new issue in a repository",
        input_schema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string", "description": "Issue body"},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Label names",
                },
            },
            "required": ["owner", "repo", "title"],
        },
    )
    def github_create_issue(
        owner: str, repo: str, title: str, body: str = "", labels: list[str] | None = None
    ) -> str:
        import httpx
        base = os.environ.get("GITHUB_API_URL", "https://api.github.com")
        url = f"{base.rstrip('/')}/repos/{owner}/{repo}/issues"
        payload: dict[str, object] = {"Title": title, "body": body}
        if labels:
            payload["labels"] = labels
        headers = _get_headers()
        headers["Content-Type"] = "application/json"
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            issue = resp.json()
        url = issue.get("html_url", "")
        return f"Issue created: #{issue.get('number')} {issue.get('title')}\n{url}"

    TOOLS: list = [
        github_search_repos,
        github_get_repo,
        github_list_issues,
        github_get_issue,
        github_list_prs,
        github_create_issue,
    ]

else:
    TOOLS = []


def main() -> None:
    server = MCPServer(name="github", version="1.0.0", tools=TOOLS)
    server.run()


if __name__ == "__main__":
    main()
