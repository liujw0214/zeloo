---
id: deployment-cicd
title: CI/CD
sidebar_label: CI/CD
---

# CI/CD Pipeline

GitHub Actions workflows in `.github/workflows/`.

## Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `pr-checks.yml` | PR open/sync | Ruff lint + format + unit tests |
| `test.yml` | push main | Full test suite + Codecov |
| `ci.yml` | push | Lint + type-check + tests |
| `multi-platform.yml` | push main | Linux/macOS/Windows × Python 3.11/3.12 |
| `lint.yml` | push | Standalone ruff check |
| `typecheck.yml` | push | ANN type checks |
| `perf-regression.yml` | push main (weekly) | Benchmark baselines |
| `docker.yml` | push main/develop | Build + Trivy scan + SBOM |
| `release.yml` | tag v* | PyPI publish + GitHub release |
| `security.yml` | push | Bandit + Safety |
| `docs.yml` | push main | Deploy Docusaurus to Pages |

## Local pre-commit equivalent

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/unit -q
```

## See also

- [Source: .github/workflows/](https://github.com/Zeloo/Zeloo/tree/main/.github/workflows)