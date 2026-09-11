"""Optional Skill Tools — expose optional_skills functions as Agent tools.

This module bridges the optional_skills/ Python modules to the Zeloo tool system,
making specialized skills (software development, DevOps, data science, MLOps,
research, security) available as discoverable Agent tools.
"""

from __future__ import annotations

from typing import Any

from tools.base import tool

__all__ = [
    "code_review",
    "refactor_code",
    "generate_tests",
    "cicd_analysis",
    "docker_diagnostics",
    "k8s_health",
    "eda",
    "feature_analysis",
    "data_quality_report",
    "model_drift_check",
    "training_diagnostics",
    "model_registry_info",
    "summarize_paper",
    "extract_citations",
    "literature_review",
    "dependency_audit",
    "secret_detection",
    "threat_analysis",
]


def _import_skill(name: str) -> Any:
    try:
        return __import__(f"optional_skills.{name}", fromlist=["*"])
    except ImportError:
        return None


# ─── Software Development ──────────────────────────────────────────────


@tool(
    name="code_review",
    description=(
        "Run automated code review using ruff on provided source code. "
        "Supports Python, JavaScript, TypeScript, Rust, Go, and Java. "
        "Returns structured issues with file, line, column, message, and severity."
    ),
    toolset="optional_skill:software_development",
)
def code_review(code: str, language: str | None = None, ruff: bool = True) -> str:
    """Review source code with ruff linter."""
    mod = _import_skill("software_development")
    if mod is None:
        return "Error: optional_skills.software_development not installed"
    result = mod.code_review(code=code, language=language, ruff=ruff)
    return str(result)


@tool(
    name="refactor_code",
    description=(
        "Suggest refactorings for code. "
        "Supports: extract_function, simplify_conditionals, remove_duplication, improve_naming."
    ),
    toolset="optional_skill:software_development",
)
def refactor_code(code: str, target: str = "extract_function") -> str:
    """Suggest refactorings for code."""
    mod = _import_skill("software_development")
    if mod is None:
        return "Error: optional_skills.software_development not installed"
    result = mod.refactor(code=code, target=target)
    return str(result)


@tool(
    name="generate_tests",
    description=(
        "Generate unit tests (pytest or unittest) for provided source code. "
        "Detects functions automatically and generates skeleton test cases."
    ),
    toolset="optional_skill:software_development",
)
def generate_tests(code: str, framework: str = "pytest") -> str:
    """Generate unit tests for source code."""
    mod = _import_skill("software_development")
    if mod is None:
        return "Error: optional_skills.software_development not installed"
    result = mod.generate_tests(code=code, framework=framework)
    return str(result)


# ─── DevOps ─────────────────────────────────────────────────────────────


@tool(
    name="cicd_analysis",
    description=(
        "Analyze CI/CD pipeline YAML (GitHub Actions format) for issues and suggestions: "
        "caching, timeouts, trigger scope, action consolidation, SHA pinning."
    ),
    toolset="optional_skill:devops",
)
def cicd_analysis(config_path: str | None = None, config_content: str | None = None) -> str:
    """Analyze CI/CD pipeline configuration."""
    mod = _import_skill("devops")
    if mod is None:
        return "Error: optional_skills.devops not installed"
    result = mod.cicd_analysis(config_path=config_path, config_content=config_content)
    return str(result)


@tool(
    name="docker_diagnostics",
    description=(
        "Run Docker health and configuration diagnostics: "
        "checks docker installed, image exists, compose file (restart policy, healthcheck)."
    ),
    toolset="optional_skill:devops",
)
def docker_diagnostics(
    image: str | None = None, compose_path: str | None = None
) -> str:
    """Diagnose Docker setup."""
    mod = _import_skill("devops")
    if mod is None:
        return "Error: optional_skills.devops not installed"
    result = mod.docker_diagnostics(image=image, compose_path=compose_path)
    return str(result)


@tool(
    name="k8s_health",
    description=(
        "Check Kubernetes cluster health via kubectl: "
        "inspects nodes, pods, and services in the specified namespace. "
        "Returns component status counts (ok/failing)."
    ),
    toolset="optional_skill:devops",
)
def k8s_health(namespace: str = "default") -> str:
    """Check Kubernetes cluster health."""
    mod = _import_skill("devops")
    if mod is None:
        return "Error: optional_skills.devops not installed"
    result = mod.k8s_health(namespace=namespace)
    return str(result)


# ─── Data Science ───────────────────────────────────────────────────────


@tool(
    name="eda",
    description=(
        "Perform exploratory data analysis on a CSV or Parquet file. "
        "Returns summary stats (rows, cols, memory), per-column types, "
        "missing values, and numeric column statistics (mean, std, min, max). "
        "Requires pandas."
    ),
    toolset="optional_skill:data_science",
)
def eda(data_path: str, max_rows: int = 10000) -> str:
    """Run exploratory data analysis on a dataset."""
    mod = _import_skill("data_science")
    if mod is None:
        return "Error: optional_skills.data_science not installed"
    result = mod.eda(data_path=data_path, max_rows=max_rows)
    return str(result)


@tool(
    name="feature_analysis",
    description=(
        "Analyze features of a machine learning dataset. "
        "Computes dtype, missing %, cardinality, and correlation with target column. "
        "Requires pandas."
    ),
    toolset="optional_skill:data_science",
)
def feature_analysis(data_path: str, target_col: str | None = None) -> str:
    """Analyze ML dataset features."""
    mod = _import_skill("data_science")
    if mod is None:
        return "Error: optional_skills.data_science not installed"
    result = mod.feature_analysis(data_path=data_path, target_col=target_col)
    return str(result)


@tool(
    name="data_quality_report",
    description=(
        "Generate a comprehensive data quality report: "
        "completeness score, duplicate rows, per-column missing %, "
        "severity-rated issues."
    ),
    toolset="optional_skill:data_science",
)
def data_quality_report(data_path: str) -> str:
    """Generate data quality report."""
    mod = _import_skill("data_science")
    if mod is None:
        return "Error: optional_skills.data_science not installed"
    result = mod.data_quality_report(data_path=data_path)
    return str(result)


# ─── MLOps ────────────────────────────────────────────────────────────


@tool(
    name="model_drift_check",
    description=(
        "Detect data drift between a reference and current dataset. "
        "Compares mean values of numeric columns against a threshold (default 5%). "
        "Returns list of drifted features with drift percentages. "
        "Requires pandas."
    ),
    toolset="optional_skill:mlops",
)
def model_drift_check(
    reference_data: str,
    current_data: str,
    threshold: float = 0.05,
) -> str:
    """Detect data drift between two datasets."""
    mod = _import_skill("mlops")
    if mod is None:
        return "Error: optional_skills.mlops not installed"
    result = mod.model_drift_check(
        reference_data=reference_data,
        current_data=current_data,
        threshold=threshold,
    )
    return str(result)


@tool(
    name="training_diagnostics",
    description=(
        "Diagnose training log files for common ML issues: "
        "loss increasing, loss plateau, unstable loss, learning rate parsing. "
        "Extracts loss/accuracy/learning rate values from log text."
    ),
    toolset="optional_skill:mlops",
)
def training_diagnostics(
    log_path: str | None = None,
    log_content: str | None = None,
) -> str:
    """Diagnose ML training logs."""
    mod = _import_skill("mlops")
    if mod is None:
        return "Error: optional_skills.mlops not installed"
    result = mod.training_diagnostics(log_path=log_path, log_content=log_content)
    return str(result)


@tool(
    name="model_registry_info",
    description=(
        "Query a local model registry directory. "
        "Lists model folders with weight files (*.pt, *.pth, *.safetensors, *.onnx, *.h5), "
        "size, and metadata (metadata.json, model_card.md, config.json)."
    ),
    toolset="optional_skill:mlops",
)
def model_registry_info(
    registry_path: str,
    model_name: str | None = None,
) -> str:
    """Query model registry directory."""
    mod = _import_skill("mlops")
    if mod is None:
        return "Error: optional_skills.mlops not installed"
    result = mod.model_registry_info(
        registry_path=registry_path, model_name=model_name
    )
    return str(result)


# ─── Research ───────────────────────────────────────────────────────────


@tool(
    name="summarize_paper",
    description=(
        "Summarize academic papers or research documents. "
        "Styles: abstract (default), bullet_points, tl;dr. "
        "Extracts key terms (excludes stop words)."
    ),
    toolset="optional_skill:research",
)
def summarize_paper(
    text: str,
    style: str = "abstract",
    max_length: int = 300,
) -> str:
    """Summarize an academic paper."""
    mod = _import_skill("research")
    if mod is None:
        return "Error: optional_skills.research not installed"
    result = mod.summarize_paper(text=text, style=style, max_length=max_length)
    return str(result)


@tool(
    name="extract_citations",
    description=(
        "Extract citation references from academic text. "
        "Supports numeric [1], author-year (Smith et al. 2024), and author (Year) formats. "
        "Output as plain list or BibTeX."
    ),
    toolset="optional_skill:research",
)
def extract_citations(text: str, format: str = "list") -> str:
    """Extract citations from academic text."""
    mod = _import_skill("research")
    if mod is None:
        return "Error: optional_skills.research not installed"
    result = mod.extract_citations(text=text, format=format)
    return str(result)


@tool(
    name="literature_review",
    description=(
        "Scan a directory of papers and organize by keyword relevance. "
        "Scores papers by keyword match frequency, returns sorted list "
        "with abstracts and theme counts."
    ),
    toolset="optional_skill:research",
)
def literature_review(
    paper_dir: str,
    keywords: list[str] | None = None,
    max_papers: int = 20,
) -> str:
    """Organize papers by keyword relevance."""
    mod = _import_skill("research")
    if mod is None:
        return "Error: optional_skills.research not installed"
    result = mod.literature_review(
        paper_dir=paper_dir, keywords=keywords, max_papers=max_papers
    )
    return str(result)


# ─── Security ────────────────────────────────────────────────────────────


@tool(
    name="dependency_audit",
    description=(
        "Audit Python dependencies for known vulnerabilities. "
        "Scans requirements.txt or pyproject.toml. "
        "Uses pip list + pip audit (if installed) for CVE checking. "
        "Returns vulnerability list with severity and package info."
    ),
    toolset="optional_skill:security",
)
def dependency_audit(
    requirements_path: str | None = None,
    lock_content: str | None = None,
) -> str:
    """Audit Python dependencies for vulnerabilities."""
    mod = _import_skill("security")
    if mod is None:
        return "Error: optional_skills.security not installed"
    result = mod.dependency_audit(
        requirements_path=requirements_path, lock_content=lock_content
    )
    return str(result)


@tool(
    name="secret_detection",
    description=(
        "Scan source code for embedded secrets: "
        "API keys (OpenAI, Anthropic, GitHub, Slack, AWS, Google), "
        "OAuth tokens, private keys, passwords. "
        "Checks *.py, *.yaml, *.json, *.env files, skips venv/node_modules."
    ),
    toolset="optional_skill:security",
)
def secret_detection(
    target: str,
    patterns: list[str] | None = None,
) -> str:
    """Scan for embedded secrets in code."""
    mod = _import_skill("security")
    if mod is None:
        return "Error: optional_skills.security not installed"
    result = mod.secret_detection(target=target, patterns=patterns)
    return str(result)


@tool(
    name="threat_analysis",
    description=(
        "Perform security threat analysis on code or configuration. "
        "For code: detects eval(), exec(), shell=True, weak crypto, insecure random, obfuscation. "
        "For config: detects overly permissive permissions, debug mode, no SSL. "
        "Returns risk score (0-10) and threat list."
    ),
    toolset="optional_skill:security",
)
def threat_analysis(
    code_or_config: str,
    target_type: str = "code",
) -> str:
    """Analyze code/config for security threats."""
    mod = _import_skill("security")
    if mod is None:
        return "Error: optional_skills.security not installed"
    result = mod.threat_analysis(code_or_config=code_or_config, target_type=target_type)
    return str(result)
