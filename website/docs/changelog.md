---
id: changelog
title: Changelog
sidebar_label: Changelog
---

# Changelog

## 0.1.0 (2026-09)

Initial public release.

### Features

- 44 LLM providers (OpenAI, Anthropic, Gemini, DeepSeek, Bedrock, Mistral, …)
- 9 memory backends (file, sqlite, redis, postgres, supermemory, honcho, mem0, openviking, byterover)
- 65+ MCP servers built-in
- 18 messaging platforms (Telegram, Discord, Slack, WeChat, Lark, …)
- 4 image generation providers
- 4 video generation providers
- 3 browser providers (Browserbase, Firecrawl, Playwright)
- Skills system with auto-curation
- Self-evolution (turn finalizer + background review)
- Native FTS5 CJK tokenizer (Rust + jieba-rs)
- Cost tracking + circuit breakers

### Infrastructure

- GitHub Actions: 11 workflows (CI, CD, security, perf, multi-platform, …)
- Docker: multi-stage build + non-root user + health check
- Docusaurus docs site
- 1214+ unit tests + 18 integration tests + perf benchmarks

## Earlier rounds

See [docs/10-roadmap.md](https://github.com/Zeloo/Zeloo/blob/main/docs/10-roadmap.md) for the full 39-round history.