---
id: modules-state
title: State
sidebar_label: State
---

# State Persistence

All agent state lives in `zeloo_state/`.

## Components

- **Sessions** (`Session` dataclass) — per-conversation metadata
- **Messages** (`Message` dataclass) — per-turn records
- **FTS5 search** — full-text search across messages (CJK tokenizer via native ext)
- **Connection pool** — SQLite WAL with read/write locks
- **Audit log** — append-only event log

## Storage

Default: SQLite with WAL journal mode. Alternative: in-memory (for tests).

## Schema

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    platform TEXT,
    created_at REAL,
    metadata JSON
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id),
    role TEXT,
    content TEXT,
    created_at REAL
);

CREATE VIRTUAL TABLE messages_fts USING fts5(content, content='messages');
```