"""GitHub MCP native — issues, PRs, repos, and actions via GitHub API."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", os.environ.get("GITHUB_API_TOKEN", ""))
GH_BASE_URL = "https://api.github.com"


def _gh_headers() -> dict[str, str]:
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN environment variable not set")
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


@make_tool
def github_list_repos(
    visibility: str = "all",
    sort: str = "updated",
    limit: int = 30,
) -> str:
    """List authenticated user's repositories.

    Args:
        visibility: Filter by visibility (all, public, private).
        sort: Sort by (created, updated, pushed, full_name).
        limit: Number of repos.
    """
    url = f"{GH_BASE_URL}/user/repos"
    params = {"visibility": visibility, "sort": sort, "per_page": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_gh_headers(), params=params)
        resp.raise_for_status()
    repos = [
        {"name": r["name"], "full_name": r["full_name"],
         "private": r["private"], "url": r["html_url"]}
        for r in resp.json()
    ]
    return json.dumps({"repos": repos}, indent=2, ensure_ascii=False)


@make_tool
def github_list_issues(
    owner: str,
    repo: str,
    state: str = "open",
    limit: int = 30,
) -> str:
    """List issues in a GitHub repository.

    Args:
        owner: Repository owner.
        repo: Repository name.
        state: Issue state (open, closed, all).
        limit: Number of issues.
    """
    url = f"{GH_BASE_URL}/repos/{owner}/{repo}/issues"
    params = {"state": state, "per_page": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_gh_headers(), params=params)
        resp.raise_for_status()
    issues = [
        {"number": i["number"], "title": i["title"],
         "state": i["state"], "labels": [lb["name"] for lb in i.get("labels", [])]}
        for i in resp.json() if "pull_request" not in i
    ]
    return json.dumps({"issues": issues}, indent=2, ensure_ascii=False)


@make_tool
def github_create_issue(
    owner: str,
    repo: str,
    title: str,
    body: str = "",
    labels: str = "",
) -> str:
    """Create a new GitHub issue.

    Args:
        owner: Repository owner.
        repo: Repository name.
        title: Issue title.
        body: Issue body description.
        labels: Comma-separated label names.
    """
    url = f"{GH_BASE_URL}/repos/{owner}/{repo}/issues"
    payload: dict[str, Any] = {"title": title}
    if body:
        payload["body"] = body
    if labels:
        payload["labels"] = [lb.strip() for lb in labels.split(",")]
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_gh_headers(), json=payload)
        resp.raise_for_status()
    issue = resp.json()
    return json.dumps({
        "number": issue["number"],
        "url": issue["html_url"],
        "title": issue["title"],
    }, indent=2, ensure_ascii=False)


@make_tool
def github_list_pulls(
    owner: str,
    repo: str,
    state: str = "open",
) -> str:
    """List pull requests in a repository.

    Args:
        owner: Repository owner.
        repo: Repository name.
        state: PR state (open, closed, all).
    """
    url = f"{GH_BASE_URL}/repos/{owner}/{repo}/pulls"
    params = {"state": state}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_gh_headers(), params=params)
        resp.raise_for_status()
    prs = [
        {"number": p["number"], "title": p["title"],
         "state": p["state"], "url": p["html_url"]}
        for p in resp.json()
    ]
    return json.dumps({"pulls": prs}, indent=2, ensure_ascii=False)


@make_tool
def github_get_workflow_runs(
    owner: str,
    repo: str,
    branch: str = "",
    limit: int = 20,
) -> str:
    """List recent GitHub Actions workflow runs.

    Args:
        owner: Repository owner.
        repo: Repository name.
        branch: Filter by branch.
        limit: Number of runs.
    """
    url = f"{GH_BASE_URL}/repos/{owner}/{repo}/actions/runs"
    params: dict[str, Any] = {"per_page": min(limit, 100)}
    if branch:
        params["branch"] = branch
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_gh_headers(), params=params)
        resp.raise_for_status()
    runs = [
        {"id": r["id"], "name": r["name"], "status": r["status"],
         "conclusion": r.get("conclusion"),
         "head_branch": r.get("head_branch"),
         "created_at": r.get("created_at", "")}
        for r in resp.json().get("workflow_runs", [])
    ]
    return json.dumps({"runs": runs}, indent=2, ensure_ascii=False)


TOOLS = [
    github_list_repos,
    github_list_issues,
    github_create_issue,
    github_list_pulls,
    github_get_workflow_runs,
]


class GitHubNativeMCPServer(MCPServer):
    name = "github-native"
    description = "GitHub issues, PRs, repos, and Actions via native API"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["GitHubNativeMCPServer", "TOOLS"]
