"""GCP MCP — Compute Engine, Cloud Storage, Cloud Functions management."""

from __future__ import annotations

import json
import os
from typing import Any

from optional_mcps.base import MCPServer, make_tool

GCP_PROJECT = os.environ.get("GCP_PROJECT", "")
GCP_REGION = os.environ.get("GCP_REGION", "us-central1")


def _get_gcp_service(service: str, version: str = "v1") -> Any:
    try:
        from google.cloud import discovery
        return discovery.build(service, version)
    except ImportError:
        return None


@make_tool
def gcp_list_compute_instances(
    project: str = "",
    zone: str = "us-central1-a",
) -> str:
    """List Compute Engine instances in a project.

    Args:
        project: GCP project ID (defaults to GCP_PROJECT env var).
        zone: Zone to query.
    """
    project = project or GCP_PROJECT
    if not project:
        return json.dumps({"error": "GCP_PROJECT not set"})
    try:
        from google.cloud import compute_v1
        client = compute_v1.InstancesClient()
        request = compute_v1.ListInstancesRequest(
            project=project,
            zone=zone,
        )
        instances = []
        for instance in client.list(request=request):
            instances.append({
                "name": instance.name,
                "status": instance.status,
                "machine_type": instance.machine_type.split("/")[-1],
                "zone": zone,
            })
        return json.dumps({"instances": instances, "count": len(instances)}, indent=2, ensure_ascii=False)
    except ImportError:
        return json.dumps({"error": "google-cloud-compute not installed"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@make_tool
def gcp_list_storage_buckets(
    project: str = "",
) -> str:
    """List Cloud Storage buckets in a project.

    Args:
        project: GCP project ID (defaults to GCP_PROJECT env var).
    """
    project = project or GCP_PROJECT
    if not project:
        return json.dumps({"error": "GCP_PROJECT not set"})
    try:
        from google.cloud import storage
        client = storage.Client(project=project)
        buckets = [{"name": b.name, "location": b.location} for b in client.list_buckets()]
        return json.dumps({"buckets": buckets, "count": len(buckets)}, indent=2, ensure_ascii=False)
    except ImportError:
        return json.dumps({"error": "google-cloud-storage not installed"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@make_tool
def gcp_list_cloud_functions(
    project: str = "",
    region: str = "",
) -> str:
    """List Cloud Functions in a project.

    Args:
        project: GCP project ID.
        region: Region to query (defaults to GCP_REGION env var).
    """
    project = project or GCP_PROJECT
    region = region or GCP_REGION
    if not project:
        return json.dumps({"error": "GCP_PROJECT not set"})
    try:
        from google.cloud import functions_v2
        client = functions_v2.FunctionServiceClient()
        parent = f"projects/{project}/locations/{region}"
        resp = client.list_functions(request={"parent": parent})
        functions = [
            {
                "name": f.name.split("/")[-1],
                "state": str(f.state),
                "entry_point": f.entry_point,
            }
            for f in resp.functions
        ]
        return json.dumps({"functions": functions, "count": len(functions)}, indent=2, ensure_ascii=False)
    except ImportError:
        return json.dumps({"error": "google-cloud-functions not installed"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@make_tool
def gcp_list_bigquery_datasets(
    project: str = "",
) -> str:
    """List BigQuery datasets in a project.

    Args:
        project: GCP project ID.
    """
    project = project or GCP_PROJECT
    if not project:
        return json.dumps({"error": "GCP_PROJECT not set"})
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=project)
        datasets = [{"dataset_id": d.dataset_id, "project": d.project} for d in client.list_datasets()]
        return json.dumps({"datasets": datasets, "count": len(datasets)}, indent=2, ensure_ascii=False)
    except ImportError:
        return json.dumps({"error": "google-cloud-bigquery not installed"})
    except Exception as e:
        return json.dumps({"error": str(e)})


TOOLS = [
    gcp_list_compute_instances,
    gcp_list_storage_buckets,
    gcp_list_cloud_functions,
    gcp_list_bigquery_datasets,
]


class GCPMCPServer(MCPServer):
    name = "gcp"
    description = "GCP Compute Engine, Cloud Storage, Cloud Functions, BigQuery"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["GCPMCPServer", "TOOLS"]
