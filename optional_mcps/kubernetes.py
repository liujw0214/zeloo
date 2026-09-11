"""Kubernetes MCP — cluster management via kubectl."""

from __future__ import annotations

import json
import os
import subprocess

from optional_mcps.base import MCPServer, make_tool

KUBE_CONFIG = os.environ.get("KUBECONFIG", "")
KUBE_CONTEXT = os.environ.get("KUBECTL_CONTEXT", "")


def _run_kubectl(args: list[str]) -> str:
    cmd = ["kubectl"]
    if KUBE_CONFIG:
        cmd.extend(["--kubeconfig", KUBE_CONFIG])
    if KUBE_CONTEXT:
        cmd.extend(["--context", KUBE_CONTEXT])
    cmd.extend(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return json.dumps({"error": result.stderr}, ensure_ascii=False)
        return result.stdout or json.dumps({"message": "Success"})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Command timed out"})
    except FileNotFoundError:
        return json.dumps({"error": "kubectl not found"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@make_tool
def k8s_get_pods(
    namespace: str = "default",
    label_selector: str = "",
    all_namespaces: bool = False,
) -> str:
    """Get pods in a Kubernetes namespace.

    Args:
        namespace: The namespace to query.
        label_selector: Optional label selector (e.g. 'app=myapp').
        all_namespaces: If True, list pods across all namespaces.
    """
    args = ["get", "pods", "-o", "wide"]
    if all_namespaces:
        args.append("--all-namespaces")
    else:
        args.extend(["-n", namespace])
    if label_selector:
        args.extend(["-l", label_selector])
    return _run_kubectl(args)


@make_tool
def k8s_get_services(
    namespace: str = "default",
) -> str:
    """Get services in a Kubernetes namespace.

    Args:
        namespace: The namespace to query.
    """
    return _run_kubectl(["get", "svc", "-n", namespace, "-o", "wide"])


@make_tool
def k8s_get_deployments(
    namespace: str = "default",
) -> str:
    """Get deployments in a Kubernetes namespace.

    Args:
        namespace: The namespace to query.
    """
    return _run_kubectl(["get", "deploy", "-n", namespace, "-o", "wide"])


@make_tool
def k8s_describe_pod(
    name: str,
    namespace: str = "default",
) -> str:
    """Describe a pod to get detailed information.

    Args:
        name: The pod name.
        namespace: The namespace.
    """
    return _run_kubectl(["describe", "pod", name, "-n", namespace])


@make_tool
def k8s_get_logs(
    name: str,
    namespace: str = "default",
    container: str = "",
    tail_lines: int = 100,
) -> str:
    """Get logs from a pod.

    Args:
        name: The pod name.
        namespace: The namespace.
        container: Optional container name (for multi-container pods).
        tail_lines: Number of lines to tail from the end.
    """
    args = ["logs", name, "-n", namespace, f"--tail={tail_lines}"]
    if container:
        args.extend(["-c", container])
    return _run_kubectl(args)


@make_tool
def k8s_scale_deployment(
    name: str,
    replicas: int,
    namespace: str = "default",
) -> str:
    """Scale a deployment to a specific number of replicas.

    Args:
        name: The deployment name.
        replicas: Target number of replicas.
        namespace: The namespace.
    """
    return _run_kubectl([
        "scale", "deployment", name,
        "--replicas", str(replicas),
        "-n", namespace,
    ])


TOOLS = [
    k8s_get_pods,
    k8s_get_services,
    k8s_get_deployments,
    k8s_describe_pod,
    k8s_get_logs,
    k8s_scale_deployment,
]


class KubernetesMCPServer(MCPServer):
    name = "kubernetes"
    description = "Kubernetes cluster management via kubectl"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["KubernetesMCPServer", "TOOLS"]
