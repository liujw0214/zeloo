---
id: agent-loop
title: Agent Loop
sidebar_label: Agent Loop
---

# Agent Conversation Loop

The agent loop orchestrates LLM calls, tool execution, and message accumulation.

## Flow

```
┌─────────────────────────────────────────┐
│          User Input / Tool Result       │
└──────────────┬──────────────────────────┘
               ▼
┌─────────────────────────────────────────┐
│   Add to messages · Compress if needed  │
└──────────────┬──────────────────────────┘
               ▼
┌─────────────────────────────────────────┐
│   Call LLM with retries (LLM_MAX_RETRIES)│
└──────────────┬──────────────────────────┘
               ▼
        ┌──────────────┐
        │ Tool calls?  │──No──► Return content
        └──────┬───────┘
               ▼ Yes
┌─────────────────────────────────────────┐
│   Execute tools in parallel (max 8)     │
└──────────────┬──────────────────────────┘
               ▼
┌─────────────────────────────────────────┐
│   Append tool messages · Loop back      │
└─────────────────────────────────────────┘
```

## Configuration

- `max_iterations` — Default 90 (90 LLM calls before partial response)
- `llm_max_retries` — Default 3 transient retries
- `max_workers` — Default 8 parallel tool executions
- `interrupt_requested` — Cooperative cancellation

## See also

- [System Prompt](system-prompt)
- [Memory](memory)
- [Source: agent/conversation_loop.py](https://github.com/Zeloo/Zeloo/blob/main/agent/conversation_loop.py)