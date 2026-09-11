"""Jenkins MCP — CI/CD server."""

from __future__ import annotations

import base64
import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

JENKINS_URL = os.environ.get("JENKINS_URL", "http://localhost:8080")
JENKINS_USER = os.environ.get("JENKINS_USER", "")
JENKINS_TOKEN = os.environ.get("JENKINS_API_TOKEN", "")


def _jenkins_headers() -> dict[str, str]:
    if not JENKINS_USER or not JENKINS_TOKEN:
        raise ValueError("JENKINS_USER and JENKINS_API_TOKEN must be set")
    creds = base64.b64encode(
        f"{JENKINS_USER}:{JENKINS_TOKEN}".encode()
    ).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/json",
    }


@make_tool
def jenkins_list_jobs() -> str:
    """List all Jenkins jobs."""
    url = f"{JENKINS_URL}/api/json"
    params = {"tree": "jobs[name,url,color,lastBuild[number,result]]"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_jenkins_headers(), params=params)
        resp.raise_for_status()
    jobs = [
        {"name": j["name"], "url": j.get("url"),
         "color": j.get("color"),
         "last_build": j.get("lastBuild", {}).get("number")}
        for j in resp.json().get("jobs", [])
    ]
    return json.dumps({"jobs": jobs}, indent=2, ensure_ascii=False)


@make_tool
def jenkins_get_job(job_name: str) -> str:
    """Get Jenkins job details."""
    url = f"{JENKINS_URL}/job/{job_name}/api/json"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_jenkins_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def jenkins_trigger_build(job_name: str) -> str:
    """Trigger a Jenkins job build."""
    url = f"{JENKINS_URL}/job/{job_name}/build"
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=_jenkins_headers())
        resp.raise_for_status()
    queue_url = resp.headers.get("Location", "")
    return json.dumps({"status": "triggered", "queue_url": queue_url})


@make_tool
def jenkins_get_build_status(
    job_name: str, build_number: int
) -> str:
    """Get status of a specific build."""
    url = f"{JENKINS_URL}/job/{job_name}/{build_number}/api/json"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_jenkins_headers())
        resp.raise_for_status()
    data = resp.json()
    return json.dumps({
        "result": data.get("result"),
        "duration": data.get("duration"),
        "building": data.get("building"),
        "timestamp": data.get("timestamp"),
    }, indent=2)


@make_tool
def jenkins_list_nodes() -> str:
    """List all Jenkins build nodes (agents)."""
    url = f"{JENKINS_URL}/computer/api/json"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_jenkins_headers())
        resp.raise_for_status()
    nodes = [
        {"name": n["displayName"], "online": n.get("online"),
         "executors": n.get("numExecutors")}
        for n in resp.json().get("computer", [])
    ]
    return json.dumps({"nodes": nodes}, indent=2, ensure_ascii=False)


TOOLS = [
    jenkins_list_jobs,
    jenkins_get_job,
    jenkins_trigger_build,
    jenkins_get_build_status,
    jenkins_list_nodes,
]


class JenkinsMCPServer(MCPServer):
    name = "jenkins"
    description = "Jenkins CI/CD server"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["JenkinsMCPServer", "TOOLS"]