"""Octopus Deploy MCP — deployment automation server."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

OCTO_URL = os.environ.get("OCTOPUS_URL", "")
OCTO_TOKEN = os.environ.get("OCTOPUS_API_KEY", "")
OCTO_SPACE = os.environ.get("OCTOPUS_SPACE_NAME", "")


def _octo_headers() -> dict[str, str]:
    if not OCTO_TOKEN:
        raise ValueError("OCTOPUS_API_KEY must be set")
    return {
        "X-Octopus-ApiKey": OCTO_TOKEN,
        "Content-Type": "application/json",
    }


def _octo_url(path: str) -> str:
    if not OCTO_URL:
        raise ValueError("OCTOPUS_URL must be set")
    return f"{OCTO_URL}/api/{OCTO_SPACE}/{path.lstrip('/')}"


@make_tool
def octopus_list_projects() -> str:
    """List all Octopus deployment projects."""
    url = _octo_url("/projects")
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_octo_headers())
        resp.raise_for_status()
    projects = [
        {"id": p["Id"], "name": p.get("Name"),
         "deployment_process_id": p.get("DeploymentProcessId")}
        for p in resp.json()
    ]
    return json.dumps({"projects": projects}, indent=2, ensure_ascii=False)


@make_tool
def octopus_list_environments() -> str:
    """List all Octopus environments."""
    url = _octo_url("/environments")
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_octo_headers())
        resp.raise_for_status()
    envs = [
        {"id": e["Id"], "name": e.get("Name"),
         "sort_order": e.get("SortOrder")}
        for e in resp.json()
    ]
    return json.dumps({"environments": envs}, indent=2, ensure_ascii=False)


@make_tool
def octopus_list_releases(project_id: str, limit: int = 25) -> str:
    """List Octopus releases for project."""
    url = _octo_url(f"/projects/{project_id}/releases")
    params = {"take": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_octo_headers(), params=params)
        resp.raise_for_status()
    releases = [
        {"id": r["Id"], "version": r.get("Version"),
         "created": r.get("Created")}
        for r in resp.json()
    ]
    return json.dumps({"releases": releases}, indent=2, ensure_ascii=False)


@make_tool
def octopus_create_release(
    project_id: str,
    version: str,
    release_notes: str = "",
) -> str:
    """Create a new Octopus release."""
    url = _octo_url("/releases")
    payload = {
        "ProjectId": project_id,
        "Version": version,
        "ReleaseNotes": release_notes,
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_octo_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def octopus_list_deployments(project_id: str, limit: int = 25) -> str:
    """List Octopus deployments for project."""
    url = _octo_url("/deployments")
    params = {"take": min(limit, 100), "projects": project_id}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_octo_headers(), params=params)
        resp.raise_for_status()
    deployments = [
        {"id": d["Id"], "release_id": d.get("ReleaseId"),
         "environment_id": d.get("EnvironmentId"),
         "state": d.get("State"),
         "created": d.get("Created")}
        for d in resp.json()
    ]
    return json.dumps({"deployments": deployments}, indent=2, ensure_ascii=False)


TOOLS = [
    octopus_list_projects,
    octopus_list_environments,
    octopus_list_releases,
    octopus_create_release,
    octopus_list_deployments,
]


class OctopusMCPServer(MCPServer):
    name = "octopus"
    description = "Octopus Deploy deployment automation"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["OctopusMCPServer", "TOOLS"]