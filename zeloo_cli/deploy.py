"""Zeloo CLI deploy — deploy Zeloo to various platforms."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DeployResult:
    success: bool
    platform: str
    url: str | None = None
    message: str = ""


def deploy_docker(
    image: str = "Zeloo/Zeloo:latest",
    port: int = 8000,
    env_file: str | None = None,
) -> DeployResult:
    """Deploy Zeloo using Docker."""
    try:
        import docker
    except ImportError:
        return DeployResult(
            success=False,
            platform="docker",
            message="docker Python package not installed (pip install docker)",
        )

    try:
        client = docker.from_env()
        env_vars = {}
        if env_file:
            for line in Path(env_file).read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    env_vars[key.strip()] = val.strip()

        container = client.containers.run(
            image,
            detach=True,
            ports={"8000/tcp": port},
            environment=env_vars,
            name="Zeloo",
            restart_policy={"Name": "unless-stopped"},
        )
        return DeployResult(
            success=True,
            platform="docker",
            url=f"http://localhost:{port}",
            message=f"Container {container.short_id} started",
        )
    except Exception as e:
        logger.error("Docker deploy failed: %s", e)
        return DeployResult(success=False, platform="docker", message=str(e))


def deploy_railway(
    api_key: str | None = None,
    project_id: str | None = None,
) -> DeployResult:
    """Deploy Zeloo to Railway."""
    try:
        import requests
    except ImportError:
        return DeployResult(
            success=False,
            platform="railway",
            message="requests package not installed",
        )

    api_key = api_key or os.environ.get("RAILWAY_API_KEY", "")
    if not api_key:
        return DeployResult(
            success=False,
            platform="railway",
            message="RAILWAY_API_KEY not set",
        )

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        resp = requests.post(
            "https://api.railway.app/v2/deploy",
            headers=headers,
            json={"projectId": project_id},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            return DeployResult(
                success=True,
                platform="railway",
                url=data.get("url"),
                message="Deployment initiated",
            )
        return DeployResult(
            success=False,
            platform="railway",
            message=f"HTTP {resp.status_code}: {resp.text}",
        )
    except Exception as e:
        return DeployResult(success=False, platform="railway", message=str(e))


def deploy_render(
    api_key: str | None = None,
    service_type: str = "web_service",
) -> DeployResult:
    """Deploy Zeloo to Render."""
    api_key = api_key or os.environ.get("RENDER_API_KEY", "")
    if not api_key:
        return DeployResult(
            success=False,
            platform="render",
            message="RENDER_API_KEY not set",
        )

    try:
        import requests

        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.post(
            "https://api.render.com/v1/services",
            headers=headers,
            json={
                "serviceType": service_type,
                "name": "Zeloo",
                "env": "python",
                "buildCommand": "pip install -e .",
                "startCommand": "uvicorn acp_adapter:app --host 0.0.0.0 --port 10000",
            },
            timeout=30,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return DeployResult(
                success=True,
                platform="render",
                url=data.get("service", {}).get("url"),
                message="Deployment initiated",
            )
        return DeployResult(
            success=False,
            platform="render",
            message=f"HTTP {resp.status_code}",
        )
    except Exception as e:
        return DeployResult(success=False, platform="render", message=str(e))


def deploy_fly(
    app_name: str = "Zeloo",
    region: str = "iad",
) -> DeployResult:
    """Deploy Zeloo to Fly.io.

    Args:
        app_name: Fly app name.
        region: Fly region.

    Returns:
        DeployResult with deployment status.
    """
    try:
        result = subprocess.run(
            ["fly", "launch", "--app", app_name, "--region", region, "--force"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            subprocess.run(["fly", "deploy"], capture_output=True, text=True)
            return DeployResult(
                success=True,
                platform="fly",
                url=f"https://{app_name}.fly.dev",
                message="Fly.io deployment complete",
            )
        return DeployResult(
            success=False,
            platform="fly",
            message=result.stderr or "fly launch failed",
        )
    except FileNotFoundError:
        return DeployResult(
            success=False,
            platform="fly",
            message="fly CLI not found. Install from: https://fly.io/docs/flyctl/",
        )
    except Exception as e:
        return DeployResult(success=False, platform="fly", message=str(e))
