---
id: roadmap
title: Roadmap
sidebar_label: Roadmap
---

# Development Roadmap

## Phase 1-3 ✅ Core Runtime

- Core conversation loop with tool calling
- 40+ built-in tools (file, web, shell, code-exec, …)
- Three-layer System Prompt (stable/context/volatile)
- 9 memory providers (file, sqlite, redis, postgres, …)
- Skills system (auto-discovery + curator lifecycle)
- Self-evolution (turn finalizer + background review)

## Phase 4 ✅ Multi-platform Gateway

- Gateway core + 18 platform adapters (Telegram, Discord, Slack, …)
- MCP stdio + HTTP clients
- OpenAI-compatible API server

## Phase 5 ✅ Optimization & Ecosystem

- Credential pool with circuit breakers
- Error classifier (8 categories)
- Kanban multi-agent board
- Hooks lifecycle system
- eStop emergency stop
- i18n (English / Chinese)
- Curator (skill lifecycle: active → stale → archived)
- Insights (runtime metrics + optimization suggestions)
- Plugins (manager + hooks)
- Native extensions (FTS5 CJK tokenizer)

## Active Development

- Browser providers (Browserbase, Firecrawl)
- Image gen providers (FAL, DeepInfra)
- Video gen providers
- Observability (Langfuse)
- Connection pool + RW locks

See [docs/10-roadmap.md](https://github.com/Zeloo/Zeloo/blob/main/docs/10-roadmap.md) for the full plan.