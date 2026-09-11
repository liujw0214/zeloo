"""Elasticsearch MCP — search and analytics."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

ES_BASE_URL = os.environ.get(
    "ELASTICSEARCH_URL", "http://localhost:9200"
)
ES_USER = os.environ.get("ELASTICSEARCH_USER", "")
ES_PASSWORD = os.environ.get("ELASTICSEARCH_PASSWORD", "")


def _es_auth() -> dict[str, str]:
    if ES_USER and ES_PASSWORD:
        import base64

        creds = base64.b64encode(
            f"{ES_USER}:{ES_PASSWORD}".encode()
        ).decode()
        return {"Authorization": f"Basic {creds}"}
    return {}


@make_tool
def elasticsearch_search(
    index: str,
    query: str,
    size: int = 10,
    from_: int = 0,
) -> str:
    """Search Elasticsearch index with a query string.

    Args:
        index: The index name to search.
        query: The Elasticsearch query DSL (JSON string or simple query).
        size: Number of results to return.
        from_: Offset for pagination.
    """
    url = f"{ES_BASE_URL}/{index}/_search"

    try:
        parsed = json.loads(query)
        body = parsed
    except (json.JSONDecodeError, TypeError):
        body = {"query": {"query_string": {"query": query}}}

    body.setdefault("size", size)
    body["from"] = from_

    headers = {"Content-Type": "application/json", **_es_auth()}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    hits = data.get("hits", {}).get("hits", [])
    total = data.get("hits", {}).get("total", {}).get("value", 0)
    results = []
    for hit in hits:
        results.append(
            {
                "_id": hit.get("_id"),
                "_score": hit.get("_score"),
                "_source": hit.get("_source"),
            }
        )
    return json.dumps({"total": total, "hits": results}, indent=2, ensure_ascii=False)


@make_tool
def elasticsearch_index_doc(
    index: str,
    doc_id: str | None,
    document: str,
) -> str:
    """Index a document into Elasticsearch.

    Args:
        index: The index name.
        doc_id: Optional document ID (auto-generated if not provided).
        document: The document JSON to index.
    """
    url = f"{ES_BASE_URL}/{index}/_doc"
    if doc_id:
        url = f"{ES_BASE_URL}/{index}/_doc/{doc_id}"

    doc = json.loads(document)
    headers = {"Content-Type": "application/json", **_es_auth()}
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, json=doc, headers=headers)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@make_tool
def elasticsearch_list_indices() -> str:
    """List all Elasticsearch indices."""
    url = f"{ES_BASE_URL}/_cat/indices?format=json"
    headers = {**_es_auth()}
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def elasticsearch_get_cluster_health() -> str:
    """Get Elasticsearch cluster health status."""
    url = f"{ES_BASE_URL}/_cluster/health"
    headers = {**_es_auth()}
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def elasticsearch_aggregate(
    index: str,
    agg_spec: str,
    size: int = 0,
) -> str:
    """Run an aggregation query on an Elasticsearch index.

    Args:
        index: The index name.
        agg_spec: The aggregation specification (JSON string).
        size: Number of top results (default 0 for aggregations only).
    """
    url = f"{ES_BASE_URL}/{index}/_search"
    body = json.loads(agg_spec)
    body["size"] = size
    headers = {"Content-Type": "application/json", **_es_auth()}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, json=body, headers=headers)
        resp.raise_for_status()
    data = resp.json()
    return json.dumps(data.get("aggregations", {}), indent=2, ensure_ascii=False)


TOOLS = [
    elasticsearch_search,
    elasticsearch_index_doc,
    elasticsearch_list_indices,
    elasticsearch_get_cluster_health,
    elasticsearch_aggregate,
]


class ElasticsearchMCPServer(MCPServer):
    name = "elasticsearch"
    description = "Elasticsearch search and analytics platform"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["ElasticsearchMCPServer", "TOOLS"]
