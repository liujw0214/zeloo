# 26. CI/CD 流水线开发计划

> Zeloo 使用 GitHub Actions 实现全自动化 CI/CD。本文档记录需要开发的 CI/CD 流水线。

## 26.1 工作流总览

| 工作流 | 文件 | 优先级 |
|--------|------|--------|
| PR 检查 | `pr-checks.yml` | P1 |
| 主分支保护 | `ci.yml` | P1 |
| 测试套件 | `test.yml` | P1 |
| Lint 检查 | `lint.yml` | P1 |
| 类型检查 | `typecheck.yml` | P1 |
| 安全扫描 | `security.yml` | P1 |
| Docker 构建 | `docker.yml` | P2 | ✅ 已实现 |
| 发布 | `release.yml` | P2 |
| 依赖更新 | `dependabot.yml` | P2 |
| 性能回归 | `perf-regression.yml` | P3 |
| 文档构建 | `docs.yml` | P2 |
| 多平台测试 | `multi-platform.yml` | P2 |

---

## 26.2 pr-checks.yml PR 检查（P1）

```yaml
# .github/workflows/pr-checks.yml

name: PR Checks

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  fast-checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Lint (ruff)
        run: pip install ruff && ruff check .

      - name: Type check (pyright)
        run: pip install pyright && pyright agent/ gateway/ tools/

      - name: Fast tests
        run: pip install pytest && pytest tests/unit/ -x -q

  security-checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Scan secrets
        uses: trufflesecurity/trufflehog@main
        with:
          path: ./
          base: ${{ github.event.repository.default_branch }}

      - name: OSV Scanner
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          user: __token__
          password: ${{ secrets.TEST_PYPI_TOKEN }}

  complete:
    needs: [fast-checks, security-checks]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - name: Report
        run: echo "All checks completed"
```

---

## 26.3 ci.yml 主分支保护（P1）

```yaml
# .github/workflows/ci.yml

name: CI (Main Branch)

on:
  push:
    branches: [main]

jobs:
  full-test-suite:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Cache pip
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ matrix.python-version }}-${{ hashFiles('**/requirements.txt') }}

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Unit tests
        run: pytest tests/unit/ -v --tb=short

      - name: Integration tests
        run: pytest tests/integration/ -v --tb=short

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          fail_ci_if_error: true
```

---

## 26.4 security.yml 安全扫描（P1）

```yaml
# .github/workflows/security.yml

name: Security Scan

on:
  schedule:
    - cron: "0 2 * * *"  # 每天 UTC 02:00
  push:
    branches: [main]

jobs:
  dependency-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: OSV Scanner
        run: |
          pip install osv-scanner
          osv-scanner --recursive .

      - name: Check requirements.txt drift
        run: |
          pip install pip-audit
          pip-audit --strict

  code-security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: CodeQL Analysis
        uses: github/codeql-action/init@v3
        with:
          languages: python

      - name: Semgrep Scan
        uses: returntocorp/semgrep-action@v1
        with:
          config: p/security-audit

      - name: Upload SARIF
        uses: github/codeql-action/upload-sarif@v3
```

---

## 26.5 docker.yml Docker 构建（P2）

```yaml
# .github/workflows/docker.yml

name: Docker Build

on:
  push:
    branches: [main, release/**]
    tags: ["v*"]
  pull_request:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to GHCR
        if: github.event_name != 'pull_request'
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=sha,prefix=
            type=semver,pattern={{version}}
            type=raw,value=latest

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: ${{ github.event_name != 'pull_request' }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Run Trivy scanner
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ghcr.io/${{ github.repository }}:latest
          format: sarif
          output: trivy-results.sarif

      - name: Upload Trivy results
        uses: github/upload-sarif-action@v2
        with:
          sarif_file: trivy-results.sarif
```

---

## 26.6 release.yml 发布（P2）

```yaml
# .github/workflows/release.yml

name: Release

on:
  push:
    tags:
      - "v*"

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Build package
        run: |
          pip install build
          python -m build

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          password: ${{ secrets.PYPI_API_TOKEN }}

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v1
        with:
          files: dist/*
          generate_release_notes: true

      - name: Notify
        if: always()
        run: |
          echo "Release ${{ github.ref_name }} completed"
```

---

## 26.7 dependabot 配置

```yaml
# .github/dependabot.yml

version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10
    groups:
      dev-dependencies:
        dependency-type: "development"
      runtime-dependencies:
        dependency-type: "production"

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"

  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"
```

---

## 26.8 perf-regression.yml 性能回归（P3）

```yaml
# .github/workflows/perf-regression.yml

name: Performance Regression

on:
  schedule:
    - cron: "0 6 * * *"  # 每天 UTC 06:00
  workflow_dispatch:

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install
        run: pip install -e ".[perf]"

      - name: Run benchmarks
        run: python -m pytest tests/perf/ -v --benchmark-json=benchmark.json

      - name: Compare with baseline
        run: |
          pip install bencher
          bencher run --project Zeloo --token ${{ secrets.BENCHER_TOKEN }}

      - name: Upload results
        uses: actions/upload-artifact@v4
        with:
          name: benchmark-results
          path: benchmark.json
```

---

## 26.9 docs.yml 文档构建（P2）

```yaml
# .github/workflows/docs.yml

name: Docs Build

on:
  push:
    branches: [main]
    paths: ["docs/**", "website/**"]
  pull_request:

jobs:
  build-docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: "npm"
          cache-dependency-path: website/package-lock.json

      - name: Install
        run: cd website && npm install

      - name: Build Docusaurus
        run: cd website && npm run build

      - name: Deploy to GitHub Pages
        if: github.ref == 'refs/heads/main'
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: website/build
```
