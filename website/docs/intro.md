---
id: intro
title: Welcome to Zeloo
sidebar_label: Introduction
slug: /
---

# Zeloo

A self-hosted, self-evolving AI agent runtime framework.

## What is Zeloo?

Zeloo is a production-grade AI agent framework with:

- **Three-layer System Prompt** — Stable / Context / Volatile layers for prefix caching
- **Multi-provider LLM routing** — OpenAI, DeepSeek, Gemini, Anthropic, Bedrock, and more
- **Self-evolving skills** — Turn finalizer + background review to extract reusable skills
- **18+ messaging platforms** — Telegram, Discord, Slack, WeChat, Lark, WhatsApp, …
- **Built-in MCP support** — Both client and server implementations
- **Full state persistence** — SQLite + FTS5 + WAL + connection pool

## Quick start

```bash
pip install Zeloo
Zeloo install
Zeloo doctor
Zeloo chat "Hello, agent!"
```

## Documentation

- [Installation](getting-started/installation)
- [Quickstart](getting-started/quickstart)
- [Architecture](architecture/overview)
- [Roadmap](roadmap)