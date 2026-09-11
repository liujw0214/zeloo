"""n8n MCP — workflow automation platform."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

N8N_BASE_URL = os.environ.get("N8N_BASE_URL", "http://localhost:5678")
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")


def _n8n_headers() -> dict[str, str]:
    if not N8N_API_KEY:
        raise ValueError("N8N_API_KEY must be set")
    return {
        "X-N8N-API-KEY": N8N_API_KEY,
        "Content-Type": "application/json",
    }


@make_tool
def n8n_list_workflows(limit: int = 50) -> str:
    """List all n8n workflows."""
    url = f"{N8N_BASE_URL}/api/v1/workflows"
    params = {"limit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_n8n_headers(), params=params)
        resp.raise_for_status()
    workflows = [
        {"id": w["id"], "name": w["name"],
         "active": w.get("active", False),
         "created_at": w.get("createdAt", "")}
        for w in resp.json().get("data", [])
    ]
    return json.dumps({"workflows": workflows}, indent=2, ensure_ascii=False)


@make_tool
def n8n_get_workflow(workflow_id: str) -> str:
    """Get workflow details."""
    url = f"{N8N_BASE_URL}/api/v1/workflows/{workflow_id}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_n8n_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def n8n_activate_workflow(workflow_id: str) -> str:
    """Activate a workflow."""
    url = f"{N8N_BASE_URL}/api/v1/workflows/{workflow_id}/activate"
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_n8n_headers())
        resp.raise_for_status()
    return json.dumps({"status": "activated"})


@make_tool
def n8n_deactivate_workflow(workflow_id: str) -> str:
    """Deactivate a workflow."""
    url = f"{N8N_BASE_URL}/api/v1/workflows/{workflow_id}/deactivate"
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_n8n_headers())
        resp.raise_for_status()
    return json.dumps({"status": "deactivated"})


@make_tool
def n8n_list_executions(
    workflow_id: str = "",
    limit: int = 50,
) -> str:
    """List workflow executions."""
    url = f"{N8N_BASE_URL}/api/v1/executions"
    params: dict[str, Any] = {"limit": min(limit, 100)}
    if workflow_id:
        params["workflowId"] = workflow_id
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_n8n_headers(), params=params)
        resp.raise_for_status()
    executions = [
        {"id": e["id"], "workflow_id": e.get("workflowId"),
         "status": e.get("status"),
         "started_at": e.get("startedAt", "")}
        for e in resp.json().get("data", [])
    ]
    return json.dumps({"executions": executions}, indent=2, ensure_ascii=False)


TOOLS = [
    n8n_list_workflows,
    n8n_get_workflow,
    n8n_activate_workflow,
    n8n_deactivate_workflow,
    n8n_list_executions,
]


class N8nMCPServer(MCPServer):
    name = "n8n"
    description = "n8n workflow automation platform"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["N8nMCPServer", "TOOLS"]