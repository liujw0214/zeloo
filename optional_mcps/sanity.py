"""Sanity MCP — headless CMS with structured content."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

SANITY_PROJECT_ID = os.environ.get("SANITY_PROJECT_ID", "")
SANITY_DATASET = os.environ.get("SANITY_DATASET", "production")
SANITY_TOKEN = os.environ.get("SANITY_API_TOKEN", "")
SANITY_BASE_URL = "https://{api}.sanity.io/{version}"


def _sanity_headers() -> dict[str, str]:
    if not SANITY_TOKEN:
        raise ValueError("SANITY_API_TOKEN must be set")
    return {
        "Authorization": f"Bearer {SANITY_TOKEN}",
        "Content-Type": "application/json",
    }


def _sanity_url(path: str) -> str:
    return (
        f"https://{SANITY_PROJECT_ID}.api.sanity.io/v2022-03-07"
        f"/data/query/{SANITY_DATASET}{path}"
    )


@make_tool
def sanity_query(groq_query: str) -> str:
    """Execute a GROQ query against Sanity dataset."""
    url = _sanity_url("")
    params = {"query": groq_query}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_sanity_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def sanity_list_documents(query: str = "*[_type == 'article']", limit: int = 50) -> str:
    """List documents by GROQ query."""
    full_query = f"{query} | order(_createdAt desc)[0:{min(limit, 100)}]"
    url = _sanity_url("")
    params = {"query": full_query}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_sanity_headers(), params=params)
        resp.raise_for_status()
    docs = resp.json().get("result", [])
    return json.dumps({"documents": docs}, indent=2, ensure_ascii=False)


@make_tool
def sanity_get_document(document_id: str) -> str:
    """Get a single Sanity document by ID."""
    url = _sanity_url(f"/{document_id}")
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_sanity_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def sanity_create_document(
    doc_type: str,
    body: str = "{}",
) -> str:
    """Create a new document in Sanity."""
    import time
    import uuid
    url = (
        f"https://{SANITY_PROJECT_ID}.api.sanity.io/v2022-03-07"
        f"/data/mutate/{SANITY_DATASET}"
    )
    payload = {
        "mutations": [{
            "create": {
                "_type": doc_type,
                **json.loads(body),
                "_createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "_id": f"{doc_type}.{uuid.uuid4().hex[:8]}",
            }
        }]
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_sanity_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def sanity_list_schemas() -> str:
    """List all schema types defined in Sanity dataset."""
    url = _sanity_url("")
    query = '*[_type == "schemaType"] { name, _id }'
    params = {"query": query}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_sanity_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    sanity_query,
    sanity_list_documents,
    sanity_get_document,
    sanity_create_document,
    sanity_list_schemas,
]


class SanityMCPServer(MCPServer):
    name = "sanity"
    description = "Sanity structured content CMS"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["SanityMCPServer", "TOOLS"]