---
id: memory
title: Memory
sidebar_label: Memory
---

# Memory Subsystem

Zeloo persists conversation memory across sessions via swappable backends.

## Memory backends

| Backend | Storage | Best for |
|---------|---------|----------|
| `file` | Markdown files (`MEMORY.md`, `USER.md`) | Local dev, single user |
| `sqlite` | SQLite with FTS5 | Production single-instance |
| `redis` | Redis with TTL | High-throughput multi-instance |
| `postgres` | PostgreSQL with JSONB | Multi-instance, durable |
| `supermemory` | ExternalSupermumery API | Managed cross-device memory |
| `honcho` | Honcho API | Personal-assistant contexts |
| `mem0` | Mem0 API | Long-term user preferences |
| `openviking` | OpenViking | RAG-style episodic memory |
| `byterover` | ByterOver | Knowledge graph memory |

## Consolidation

`agent/memory_consolidator.py` runs periodically to:

- **Merge** semantically duplicate entries
- **Expire** stale entries (TTL configurable)
- **Promote** frequently-accessed entries to long-term storage
- **Prune** low-importance entries to bound storage

## See also

- [Source: agent/memory_providers.py](https://github.com/Zeloo/Zeloo/blob/main/agent/memory_providers.py)
- [Source: agent/memory_consolidator.py](https://github.com/Zeloo/Zeloo/blob/main/agent/memory_consolidator.py)