# Contributing to Zeloo Agent

Thank you for your interest in contributing to Zeloo. This document provides guidelines and instructions for contributing.

## Development Environment

### Prerequisites

- Python 3.11+
- Node.js 22+ (for TUI and MCP tools)
- [uv](https://github.com/astral-sh/uv) — fast Python package manager
- Git

### Initial Setup

```bash
# Clone the repository
git clone <Zeloo-repo-url>
cd Zeloo

# Install dependencies with uv
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install -e .

# Verify installation
Zeloo doctor
```

### Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test module
python -m pytest tests/unit/test_memory.py -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=term-missing

# Lint and type check
uv run ruff check .
uv run ruff format --check .
```

## Project Structure

```
Zeloo/
├── agent/            # Core agent engine
├── gateway/          # Message gateway & platform adapters
├── tools/            # Tool implementations
├── plugins/          # Plugin system
├── skills/           # Built-in skills
├── zeloo_cli/       # CLI subcommands
├── cron/             # Cron scheduling system
├── datagen/          # Trajectory compression
├── docs/             # Documentation
└── tests/            # Test suite
```

## Code Conventions

- **Style**: PEP 8 + Ruff (enforced via `ruff check`)
- **Types**: Full type annotations required on all public functions
- **Docs**: Docstrings on all public functions using Google style
- **Versions**: All dependencies must be pinned with exact versions (==X.Y.Z)
- **Testing**: New features require tests. Bug fixes should include a regression test.

## Branching Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable release only |
| `develop` | Integration branch for features |
| `feat/<name>` | New feature development |
| `fix/<name>` | Bug fixes |
| `docs/<name>` | Documentation improvements |

```bash
# Create a feature branch
git checkout -b feat/my-new-feature develop

# After changes, push and create PR
git push origin feat/my-new-feature
```

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add DeepSeek model provider
fix: resolve credential pool race condition
docs: update MCP integration guide
test: add coverage for cron scheduler
refactor: simplify platform registry loading
```

## Pull Request Process

1. **Fork** the repository and create a branch from `develop`
2. **Run tests** locally: `python -m pytest tests/ -v`
3. **Run linting**: `uv run ruff check . && uv run ruff format .`
4. **Write tests** for new functionality
5. **Update documentation** if needed
6. **Open a PR** with a clear description of changes
7. **Address review feedback** if requested

### PR Template

```markdown
## Description
Brief description of what this PR does.

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Refactoring
- [ ] Test improvement

## Testing
Describe how this was tested.

## Checklist
- [ ] Code follows project conventions
- [ ] Type annotations complete
- [ ] Docstrings added/updated
- [ ] Tests added/updated
- [ ] Documentation updated
```

## Reporting Issues

### Bug Reports

Include:
- Python version and OS
- Zeloo version (`Zeloo --version`)
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs (with secrets redacted)

### Feature Requests

- Describe the use case clearly
- Explain why it would benefit the project
- Provide examples of how it would work

## Security

If you discover a security vulnerability, please **do not** open a public issue. Send a private report instead.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
