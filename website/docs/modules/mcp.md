---
id: modules-mcp
title: MCP
sidebar_label: MCP
---

# Model Context Protocol

Zeloo is both an MCP **client** (consume external servers) and **server** (expose its own tools).

## Built-in servers (65)

`optional_mcps/` ships 65+ production-ready servers: github, gitlab, slack, jira, linear, notion, stripe, sentry, supabase, figma, datadog, gmail, …

## Configuration

`~/.Zeloo/profile/config.yaml`:

```yaml
mcp_servers:
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: ${GITHUB_TOKEN}
```

## Protocol support

- **stdio** (default) — subprocess per server
- **HTTP** — long-lived HTTP transport
- **WebSocket** — streaming transport

See `optional_mcps/` and `agent/mcp_client.py`.