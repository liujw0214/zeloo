# 17. 会话状态管理

## 17.1 概述

`zeloo_state.py` 中的 `SessionDB` 是 Zeloo 的核心状态存储层，基于 SQLite（WAL 模式 + FTS5 全文搜索）实现会话持久化。

## 17.2 架构

```
SessionDB
├── sessions 表     — 会话元数据
├── messages 表    — 消息历史
├── trajectories 表 — 轨迹数据
└── messages_fts  — FTS5 全文搜索虚拟表
```

## 17.3 数据库 Schema

### 17.3.1 sessions 表

```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT,
    platform TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    title TEXT
);
```

### 17.3.2 messages 表

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,          -- user / assistant / system / tool
    content TEXT,
    tool_calls TEXT,            -- JSON 序列化
    tool_call_id TEXT,
    name TEXT,                 -- 工具名
    created_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);
```

### 17.3.3 trajectories 表

```sql
CREATE TABLE trajectories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_id INTEGER NOT NULL,
    data TEXT NOT NULL,         -- JSON 序列化
    created_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);
```

### 17.3.4 messages_fts（FTS5 全文搜索）

```sql
CREATE VIRTUAL TABLE messages_fts USING fts5(
    content, content_rowid, tokenize='unicode61'
);
```

使用 `unicode61` 分词器，支持 Unicode 文本搜索。

## 17.4 WAL 模式

```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA foreign_keys=ON")
```

- **WAL**（Write-Ahead Logging）：写入不阻塞读取，支持并发读写
- **foreign_keys**：外键约束开启，保证引用完整性
- **check_same_thread=False**：多线程安全连接

## 17.5 SessionDB API

```python
from zeloo_state import SessionDB

db = SessionDB()  # 默认 ~/.Zeloo/state.db

# 会话管理
db.create_session(session_id, user_id="user_1", platform="telegram")
session = db.get_session(session_id)
sessions = db.list_sessions(limit=20)

# 消息管理
db.save_message(session_id, role="user", content="Hello")
messages = db.get_messages(session_id, limit=100)

# 全文搜索
results = db.search_messages(session_id, query="python code", limit=20)

# 轨迹持久化
db.save_trajectory(session_id, turn_id=1, data=trajectory_dict)

db.close()
```

## 17.6 全文搜索集成

FTS 与 messages 表通过 `rowid` 关联。`save_message()` 时同步更新 FTS 表：

```python
# save_message() 中
cursor.execute("INSERT INTO messages (...) VALUES (...)")
cursor.lastrowid  # 新插入行的 rowid

# 同步更新 FTS
conn.execute(
    "INSERT INTO messages_fts (rowid, content) VALUES (?, ?)",
    (cursor.lastrowid, content)
)
```

## 17.7 与其他模块的关系

```
SessionDB
    │
    ├── AIAgent.run_conversation() → save_message() / get_messages()
    │
    ├── session_search tool → search_messages()
    │
    ├── TurnFinalizer._record_trajectory() → save_trajectory()
    │
    └── compress_trajectories.py → 读取 trajectories 表
```

## 17.8 存储路径

| 环境 | 路径 |
|------|------|
| 默认 | `~/.Zeloo/state.db` |
| Profile 隔离 | `~/.Zeloo/profiles/<name>/state.db` |
| 自定义 | `SessionDB(db_path=Path(...))` |

## 17.9 配置

```yaml
# config.yaml
gateway:
  session_idle_timeout: 3600   # 会话空闲超时（秒）
  eviction_interval: 300        # 空闲回收检查间隔
```

超过 `session_idle_timeout` 的会话会被标记为不活跃，`eviction_interval` 控制检查频率。
