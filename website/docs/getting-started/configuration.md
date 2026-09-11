---
id: configuration
title: Configuration
sidebar_label: Configuration
---

# Configuration

Zeloo reads configuration from environment variables and `~/.Zeloo/.env`.

## Core settings

| Variable | Default | Description |
|----------|---------|-------------|
| `zeloo_HOME` | `~/.Zeloo` | Workspace root |
| `zeloo_MODEL` | `gpt-4o` | Default LLM model |
| `zeloo_PROVIDER` | `openai` | Default provider name |
| `zeloo_MODE` | `cli` | Run mode (cli/gateway/web/tui/cron) |

## Provider credentials

Each provider has its own env var:

```bash
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
DEEPSEEK_API_KEY=sk-...
GEMINI_API_KEY=AIza...
GITHUB_TOKEN=ghp_...
```

## Workspace configuration

`~/.Zeloo/profile/config.yaml`:

```yaml
provider: openai
model: gpt-4o
memory_provider: sqlite
skill_dir: ~/.Zeloo/skills
max_iterations: 100
```

## Logging

```bash
zeloo_LOG_LEVEL=INFO  # DEBUG / INFO / WARNING / ERROR
```