---
id: deployment-cli
title: CLI Reference
sidebar_label: CLI
---

# CLI Reference

The `Zeloo` command-line interface.

## Subcommands

```bash
Zeloo chat [PROMPT]       # Interactive or one-shot conversation
Zeloo config [ACTION]     # Manage ~/.Zeloo/ configuration
Zeloo install             # Initialize ~/.Zeloo/ directory
Zeloo doctor              # Run system diagnostics
Zeloo status              # Show runtime status
Zeloo backup [PATH]       # Snapshot current workspace
Zeloo model               # List/configure LLM providers
Zeloo skills              # Manage local skills
Zeloo session [ACTION]    # List/manage sessions
Zeloo mcp                 # List MCP servers
Zeloo usage               # Cost & token usage report
Zeloo tools               # List available tools
Zeloo update              # Self-update Zeloo
Zeloo oauth               # OAuth authorization helper
```

## Common flags

- `--provider <name>` — override LLM provider
- `--model <name>` — override model
- `--verbose` — verbose logging
- `--no-color` — disable colored output
- `--config <path>` — use custom config file

See `cli.py` for the full implementation.