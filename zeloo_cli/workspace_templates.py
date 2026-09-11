"""Workspace profile templates — pre-configured starters.

Each template packages a :class:`TemplateSpec` so new workspaces
can be created with a single command:

    from zeloo_cli.workspace_templates import create_from_template
    create_from_template("python-dev", target_root=Path("~/.Zeloo/workspace"))

Built-in templates:

* ``python-dev``   — Python backend development (pytest, ruff, FastAPI)
* ``data-science`` — Jupyter, pandas, sklearn, visualization
* ``web-frontend`` — React/Vue/Next.js frontend with hot-reload
* ``devops``       — Kubernetes, Terraform, Ansible ops tooling
* ``research``     — Paper reading, citation extraction, summarization
* ``minimal``      — Bare-bones (only memory/MEMORY.md + USER.md)

The registry is open — third-party packages can register templates
via :func:`register_template`.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "TemplateSpec",
    "register_template",
    "list_templates",
    "create_from_template",
    "get_template",
]


@dataclass
class TemplateSpec:
    """A pre-configured workspace template."""

    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    memory_backend: str = "localfile"
    config_yaml: str = ""
    env_template: str = ""  # placeholder values for .env
    memory_files: dict[str, str] = field(default_factory=dict)
    metadata_extras: dict[str, Any] = field(default_factory=dict)

    def to_bundle_dict(self) -> dict[str, Any]:
        """Serialize to the workspace.bundle.json format."""
        files: dict[str, str] = {}
        if self.config_yaml:
            files["profile/config.yaml"] = self.config_yaml
        if self.env_template:
            files["profile/.env"] = self.env_template
        for name, content in self.memory_files.items():
            files[f"memory/{name}"] = content

        return {
            "version": 1,
            "name": f"from-{self.name}",
            "description": self.description,
            "tags": self.tags,
            "memory_backend": self.memory_backend,
            "created_at": 0,
            "files": files,
            "metadata": {"template": self.name, **self.metadata_extras},
        }


_REGISTRY: dict[str, TemplateSpec] = {}


def register_template(spec: TemplateSpec) -> None:
    """Register a template under its name (lowercased)."""
    _REGISTRY[spec.name.lower()] = spec
    logger.debug("Registered workspace template: %s", spec.name)


def list_templates() -> list[str]:
    """Return all registered template names sorted."""
    return sorted(_REGISTRY.keys())


def get_template(name: str) -> TemplateSpec | None:
    """Return the template registered under *name*, or None."""
    return _REGISTRY.get(name.lower())


def create_from_template(
    name: str,
    target_root: Path,
    *,
    workspace_name: str | None = None,
    overwrite: bool = False,
) -> Path:
    """Create a new workspace from a built-in template.

    Args:
        name: Template name (e.g. ``"python-dev"``).
        target_root: Root containing workspace subdirs
            (e.g. ``~/.Zeloo/workspace``).
        workspace_name: Workspace dir name. Defaults to ``from-<template>``.
        overwrite: Replace an existing workspace of the same name.

    Returns:
        Path to the created workspace dir.
    """
    spec = get_template(name)
    if spec is None:
        raise KeyError(
            f"Unknown template: {name!r}. "
            f"Available: {', '.join(list_templates())}"
        )

    import json

    from workspace.importer import WorkspaceBundle, import_workspace

    bundle_data = spec.to_bundle_dict()
    bundle = WorkspaceBundle.from_json(json.dumps(bundle_data))
    bundle.created_at = 0

    ws_name = workspace_name or f"from-{spec.name}"
    bundle.name = ws_name

    target = target_root / ws_name
    if target.exists():
        if not overwrite:
            raise FileExistsError(f"Workspace already exists: {target}")
        shutil.rmtree(target)

    return import_workspace(bundle, target_root, overwrite=overwrite)


# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------


_BUILTIN_TEMPLATES: list[TemplateSpec] = [
    TemplateSpec(
        name="minimal",
        description="Minimal workspace with empty MEMORY.md and USER.md",
        tags=["starter", "blank"],
        memory_files={
            "MEMORY.md": "# Memory\n\nThis workspace stores your project knowledge.\n",
            "USER.md": "# User\n\nTell the agent about yourself here.\n",
        },
    ),
    TemplateSpec(
        name="python-dev",
        description="Python backend development with pytest + ruff",
        tags=["python", "backend", "fastapi"],
        config_yaml=(
            "model: gpt-4o\n"
            "provider: openai\n"
            "tools:\n"
            "  enabled:\n"
            "    - file_read\n"
            "    - file_write\n"
            "    - shell\n"
            "    - python_run\n"
            "  testing: pytest\n"
            "  linting: ruff\n"
            "memory:\n"
            "  backend: localfile\n"
            "  paths:\n"
            "    - ./src\n"
            "    - ./tests\n"
        ),
        env_template=(
            "# Required: OPENAI_API_KEY=sk-...\n"
            "zeloo_MODEL=gpt-4o\n"
            "zeloo_PROVIDER=openai\n"
        ),
        memory_files={
            "MEMORY.md": (
                "# Memory — Python Development\n\n"
                "## Project Conventions\n"
                "- Use type hints on all public functions\n"
                "- Prefer pytest fixtures over setUp/tearDown\n"
                "- Run `ruff check` and `pytest` before committing\n\n"
                "## Frameworks in Use\n"
                "- FastAPI for HTTP APIs\n"
                "- pydantic for data validation\n"
            ),
            "USER.md": "# User\n\nTell the agent about yourself.\n",
        },
        metadata_extras={"languages": ["python"], "lint": "ruff", "test": "pytest"},
    ),
    TemplateSpec(
        name="data-science",
        description="Data science workspace with pandas / sklearn / Jupyter",
        tags=["data-science", "jupyter", "ml"],
        config_yaml=(
            "model: gpt-4o\n"
            "provider: openai\n"
            "tools:\n"
            "  enabled:\n"
            "    - file_read\n"
            "    - file_write\n"
            "    - shell\n"
            "    - python_run\n"
            "    - jupyter\n"
            "memory:\n"
            "  backend: localfile\n"
        ),
        env_template=(
            "# OPENAI_API_KEY=sk-...\n"
            "zeloo_MODEL=gpt-4o\n"
        ),
        memory_files={
            "MEMORY.md": (
                "# Memory — Data Science\n\n"
                "## Datasets\n- Document each dataset with schema, source, license.\n\n"
                "## Notebooks\n- Prefer numbered notebooks: 01-eda.ipynb, 02-feat.ipynb.\n"
            ),
        },
        metadata_extras={"domains": ["pandas", "sklearn", "matplotlib"]},
    ),
    TemplateSpec(
        name="web-frontend",
        description="Frontend dev with React/Vue/Next.js",
        tags=["frontend", "react", "nextjs"],
        config_yaml=(
            "model: gpt-4o\n"
            "provider: openai\n"
            "tools:\n"
            "  enabled:\n"
            "    - file_read\n"
            "    - file_write\n"
            "    - shell\n"
            "    - browser\n"
        ),
        env_template=(
            "# OPENAI_API_KEY=sk-...\n"
            "zeloo_MODEL=gpt-4o\n"
        ),
        memory_files={
            "MEMORY.md": (
                "# Memory — Frontend Development\n\n"
                "## Build Pipeline\n"
                "- `npm run dev` starts the dev server\n"
                "- `npm run build` produces a production bundle\n"
                "- E2E tests via Playwright in /e2e\n"
            ),
        },
        metadata_extras={"frameworks": ["react", "vite", "nextjs"]},
    ),
    TemplateSpec(
        name="devops",
        description="DevOps workspace (Kubernetes, Terraform, Ansible)",
        tags=["devops", "k8s", "terraform"],
        config_yaml=(
            "model: gpt-4o\n"
            "provider: openai\n"
            "tools:\n"
            "  enabled:\n"
            "    - file_read\n"
            "    - file_write\n"
            "    - shell\n"
            "    - terraform\n"
            "    - kubectl\n"
        ),
        env_template=(
            "# OPENAI_API_KEY=sk-...\n"
            "# KUBECONFIG=~/.kube/config\n"
            "zeloo_MODEL=gpt-4o\n"
        ),
        memory_files={
            "MEMORY.md": (
                "# Memory — DevOps\n\n"
                "## Cluster Topology\n"
                "- dev: 3 nodes (kind)\n"
                "- staging: 5 nodes (EKS)\n"
                "- prod: 12 nodes (GKE)\n\n"
                "## Deploy Procedure\n"
                "1. `terraform plan` and review\n"
                "2. `kubectl apply -k overlays/staging/`\n"
                "3. Monitor SLOs for 30 minutes\n"
            ),
        },
        metadata_extras={"tools": ["terraform", "kubectl", "ansible"]},
    ),
    TemplateSpec(
        name="research",
        description="Research workspace with paper reading / summarization",
        tags=["research", "papers", "writing"],
        config_yaml=(
            "model: gpt-4o\n"
            "provider: openai\n"
            "skills:\n"
            "  enabled:\n"
            "    - paper_summarize\n"
            "    - citation_extract\n"
            "    - literature_review\n"
        ),
        env_template=(
            "# OPENAI_API_KEY=sk-...\n"
            "zeloo_MODEL=gpt-4o\n"
        ),
        memory_files={
            "MEMORY.md": (
                "# Memory — Research\n\n"
                "## Reading List\n- Add papers here as you read them.\n\n"
                "## Notes\n- Use the literature_review skill for batch processing.\n"
            ),
        },
        metadata_extras={"domain": "research"},
    ),
]


# Register built-in templates on import.
def _register_builtins() -> None:
    for spec in _BUILTIN_TEMPLATES:
        register_template(spec)


_register_builtins()