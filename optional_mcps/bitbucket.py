"""Bitbucket MCP — code repository and CI/CD."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

BB_USER = os.environ.get("BITBUCKET_USERNAME", "")
BB_APP_PASSWORD = os.environ.get("BITBUCKET_APP_PASSWORD", "")
BB_WORKSPACE = os.environ.get("BITBUCKET_WORKSPACE", "")
BB_BASE_URL = "https://api.bitbucket.org/2.0"


def _bb_headers() -> dict[str, str]:
    if not BB_USER or not BB_APP_PASSWORD:
        raise ValueError("BITBUCKET_USERNAME and BITBUCKET_APP_PASSWORD must be set")
    return {
        "Accept": "application/json",
    }


def _bb_auth() -> tuple[str, str]:
    return (BB_USER, BB_APP_PASSWORD)


@make_tool
def bitbucket_list_repos(limit: int = 50) -> str:
    """List Bitbucket repositories."""
    url = f"{BB_BASE_URL}/repositories/{BB_WORKSPACE}"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_bb_headers(), params=params, auth=_bb_auth())
        resp.raise_for_status()
    repos = [
        {"name": r["name"], "slug": r["slug"],
         "is_private": r.get("is_private"),
         "url": r.get("links", {}).get("html", {}).get("href")}
        for r in resp.json().get("values", [])
    ]
    return json.dumps({"repos": repos}, indent=2, ensure_ascii=False)


@make_tool
def bitbucket_list_pull_requests(repo_slug: str, limit: int = 50) -> str:
    """List pull requests in a Bitbucket repo."""
    url = (
        f"{BB_BASE_URL}/repositories/{BB_WORKSPACE}/{repo_slug}/pullrequests"
    )
    params = {"limit": min(limit, 100), "state": "OPEN"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_bb_headers(), params=params, auth=_bb_auth())
        resp.raise_for_status()
    prs = [
        {"id": pr["id"], "title": pr.get("title"),
         "state": pr.get("state"), "author": pr.get("author", {}).get("username")}
        for pr in resp.json().get("values", [])
    ]
    return json.dumps({"pull_requests": prs}, indent=2, ensure_ascii=False)


@make_tool
def bitbucket_list_issues(repo_slug: str, limit: int = 50) -> str:
    """List issues in a Bitbucket repo."""
    url = f"{BB_BASE_URL}/repositories/{BB_WORKSPACE}/{repo_slug}/issues"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_bb_headers(), params=params, auth=_bb_auth())
        resp.raise_for_status()
    issues = [
        {"id": i["id"], "title": i.get("title"),
         "state": i.get("state"), "priority": i.get("priority")}
        for i in resp.json().get("values", [])
    ]
    return json.dumps({"issues": issues}, indent=2, ensure_ascii=False)


@make_tool
def bitbucket_create_issue(
    repo_slug: str,
    title: str,
    content: str = "",
    kind: str = "bug",
) -> str:
    """Create a Bitbucket issue."""
    url = f"{BB_BASE_URL}/repositories/{BB_WORKSPACE}/{repo_slug}/issues"
    payload: dict[str, Any] = {
        "title": title,
        "kind": kind,
    }
    if content:
        payload["content"] = {"raw": content}
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_bb_headers(), json=payload, auth=_bb_auth())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def bitbucket_list_pipelines(repo_slug: str, limit: int = 25) -> str:
    """List Bitbucket Pipelines runs."""
    url = (
        f"{BB_BASE_URL}/repositories/{BB_WORKSPACE}/{repo_slug}/pipelines/"
    )
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_bb_headers(), params=params, auth=_bb_auth())
        resp.raise_for_status()
    pipelines = [
        {"uuid": p["uuid"], "state": p.get("state", {}).get("name"),
         "target": p.get("target", {}).get("ref_name")}
        for p in resp.json().get("values", [])
    ]
    return json.dumps({"pipelines": pipelines}, indent=2, ensure_ascii=False)


TOOLS = [
    bitbucket_list_repos,
    bitbucket_list_pull_requests,
    bitbucket_list_issues,
    bitbucket_create_issue,
    bitbucket_list_pipelines,
]


class BitbucketMCPServer(MCPServer):
    name = "bitbucket"
    description = "Bitbucket code repo and pipelines"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["BitbucketMCPServer", "TOOLS"]