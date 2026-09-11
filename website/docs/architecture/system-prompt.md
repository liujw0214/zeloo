---
id: system-prompt
title: System Prompt
sidebar_label: System Prompt
---

# Three-Layer System Prompt

Zeloo uses a three-layer system prompt architecture optimized for LLM prefix caching.

## Layers

| Layer | Stability | Cached | Example |
|-------|-----------|--------|---------|
| **Stable** | Never changes during a session | ✅ Heavily cached | Tool definitions, agent identity |
| **Context** | Changes occasionally (memory, env) | ⚠️ Sometimes invalidated | MEMORY.md summary, working directory |
| **Volatile** | Changes every turn | ❌ Never cached | Current task, recent tool results |

## Why three layers?

By keeping the **Stable** layer constant, LLM providers can cache the prefix and avoid recomputing it on every turn — typically reducing latency by 30-50% and cost by 20-40% on long conversations.

## Source

`agent/system_prompt.py` — assembles layers in order, returns full prompt string.

## Cache invalidation

- Layer 1 invalidated only on agent reset
- Layer 2 invalidated when memory file changes (hash comparison)
- Layer 3 always recomputed