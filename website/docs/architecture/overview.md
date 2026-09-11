---
id: architecture-overview
title: Architecture Overview
sidebar_label: Overview
---

# Architecture Overview

Zeloo is built around three core subsystems that work together to deliver a self-evolving agent runtime.

## High-level diagram

```
┌─────────────────────────────────────────────────────────┐
│                    User / Platform                       │
│   Telegram · Discord · Slack · CLI · OpenAI API          │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                  Gateway Layer                           │
│   Platform adapters · Session routing · API server       │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                  Agent Runtime                           │
│   Conversation loop · Tool registry · Skills · Memory    │
└─────────────────────┬───────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   ┌────────┐   ┌──────────┐   ┌──────────┐
   │  LLM   │   │   MCP    │   │ Plugins  │
   │Router  │   │ Servers  │   │          │
   └────────┘   └──────────┘   └──────────┘
```

## Key Components

| Layer | Component | Responsibility |
|-------|-----------|----------------|
| Gateway | `gateway/run.py` | Multi-platform message routing |
| Agent | `run_agent.py` | Conversation loop |
| Agent | `agent/system_prompt.py` | Three-layer prompt assembly |
| Agent | `agent/memory_providers.py` | Memory persistence |
| State | `zeloo_state/*.py` | Sessions, messages, FTS5 search |
| Tools | `tools/*.py` | 40+ tools, auto-discovered |
| Plugins | `plugins/*.py` | Hooks, manager, plugins |