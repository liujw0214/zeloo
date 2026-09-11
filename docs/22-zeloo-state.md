# 22. zeloo_state 状态管理系统

## 22.1 模块总览

Zeloo 的状态管理分为两层：

1. **顶层文件**（`zeloo_state*.py`）— 顶层 API 入口，提供 SessionDB 等核心类
2. **`zeloo_state/` 子包** — 状态管理子系统，包含 Schema、修复、维护、异常等模块

```
zeloo_state.py                    # 顶层入口（SessionDB）
zeloo_state_messages.py           # 消息持久化
zeloo_state_search.py             # FTS5 全文搜索
zeloo_state_schema.py             # Schema 版本管理
zeloo_state_repair.py             # 数据库自诊断与修复
zeloo_state/                      # 状态管理子系统
    ├── schema.py                  # Schema 定义（TABLES / INDEXES / migrate）
    ├── repair.py                  # 数据库自诊断与修复
    ├── maintenance.py             # 定时维护任务
    ├── errors.py                  # 状态异常类型
    ├── usage.py                   # Token 用量追踪
    ├── guard.py                   # 状态写锁（防并发写入）
    ├── readpool.py                # 只读连接池（读写分离）
    ├── registry.py                # 状态注册表
    ├── fts.py                     # FTS5 全文搜索封装
    ├── gateway.py                 # 网关状态管理
    └── wal.py                     # WAL 模式细粒度控制
```

| 模块 | 优先级 | 状态 | 说明 |
|------|--------|------|------|
| `zeloo_state.py` | P1 | ✅ 已有 | SessionDB 核心类（顶层入口） |
| `zeloo_state_messages.py` | P1 | ✅ 已有 | 消息持久化 |
| `zeloo_state_search.py` | P1 | ✅ 已有 | FTS5 搜索 |
| `zeloo_state_schema.py` | P1 | ✅ 已有 | Schema 版本管理 |
| `zeloo_state_repair.py` | P1 | ✅ 已有 | 数据库自诊断修复 |
| `zeloo_state/` 子包 | P1 | ✅ 已有 | 完整状态管理子系统（13 个模块） |
| `zeloo_state/messages.py` | P1 | ✅ 已有 | Message 数据类 + MessageStore CRUD |
| `zeloo_state/search.py` | P1 | ✅ 已有 | 搜索门面（search_all / get_recent_sessions / iter_search_results） |
| `zeloo_state/usage.py` | P2 | ✅ 已有 | Token 用量统计 |
| `zeloo_state/guard.py` | P2 | ✅ 已有 | 写锁机制 |
| `zeloo_state/readpool.py` | P2 | ✅ 已有 | 只读连接池 |
| `zeloo_state/registry.py` | P2 | ✅ 已有 | 状态注册表 |
| `zeloo_state/fts.py` | P2 | ✅ 已有 | FTS5 封装 |
| `zeloo_state/gateway.py` | P2 | ✅ 已有 | 网关状态 |
| `zeloo_state/wal.py` | P2 | ✅ 已有 | WAL 模式控制 |
| `zeloo_state/errors.py` | P2 | ✅ 已有 | 状态异常类型 |
| `zeloo_state/maintenance.py` | P2 | ✅ 已有 | 定时维护任务 |

---

## 22.2 `zeloo_state/` 子包（核心）

### 22.2.1 导出 API

```python
from zeloo_state import (
    SCHEMA_VERSION,      # 当前 Schema 版本
    TABLES,              # 表定义字典
    INDEXES,             # 索引定义字典
    ensure_schema,       # 确保 Schema 最新
    get_schema_version,  # 获取当前版本
    migrate,             # 执行迁移
    validate_schema,     # 验证 Schema
    StateRepair,         # 数据库修复器
    RepairIssue,         # 修复问题描述
    RepairResult,        # 修复结果
    Severity,            # 严重程度枚举
    MaintenanceScheduler,  # 维护调度器
    MaintenanceStats,    # 维护统计
    ZelooStateError,    # 基异常
    MigrationError,      # 迁移异常
    RepairError,         # 修复异常
    SessionNotFoundError,
    MessageNotFoundError,
    StateCorruptError,
    StateLockError,
    MaintenanceError,
    ValidationError,
    SessionDB,
    set_state_home_override,
)
```

### 22.2.2 `schema.py` — Schema 版本管理

集中定义所有状态数据库的 Schema，支持版本迁移：

```python
from zeloo_state.schema import (
    SCHEMA_VERSION,
    TABLES,
    INDEXES,
    ensure_schema,
    get_schema_version,
    migrate,
    validate_schema,
)

SCHEMA_VERSION = 1

TABLES = {
    "sessions": """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT,
            platform TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            title TEXT,
            metadata TEXT
        )
    """,
    "messages": """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_calls TEXT,
            tool_call_id TEXT,
            name TEXT,
            created_at REAL NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """,
    "trajectories": """
        CREATE TABLE trajectories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            turn_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """,
    "messages_fts": """
        CREATE VIRTUAL TABLE messages_fts
        USING fts5(content, tokenize='unicode61')
    """,
}

INDEXES = {
    "messages_session_id": "CREATE INDEX idx_messages_session_id ON messages(session_id)",
    "messages_created_at": "CREATE INDEX idx_messages_created_at ON messages(created_at)",
    "trajectories_session_turn": "CREATE UNIQUE INDEX idx_trajectories_session_turn ON trajectories(session_id, turn_id)",
}
```

### 22.2.3 `repair.py` — 数据库自诊断与修复

检测并修复常见数据库损坏：索引穿透、WAL 文件残留、事务未提交等：

```python
from zeloo_state.repair import (
    StateRepair,
    RepairIssue,
    RepairResult,
    Severity,
)

repair = StateRepair(db_path=Path("~/.Zeloo/state.db"))
issues = repair.diagnose()
results = repair.repair(dry_run=False)
repair.vacuum()
```

| 检查项 | 严重程度 | 修复方式 |
|--------|----------|----------|
| WAL 文件残留 | warning | 删除 .wal 和 .shm 文件 |
| 索引损坏 | critical | REINDEX |
| 外键断裂 | critical | 清理孤儿记录 |
| 事务未提交 | warning | ROLLBACK |
| 表损坏 | critical | 从备份恢复或重建 |
| Schema 版本不匹配 | critical | 执行迁移 |

### 22.2.4 `maintenance.py` — 定时维护任务

```python
from zeloo_state.maintenance import MaintenanceScheduler, MaintenanceStats

scheduler = MaintenanceScheduler(db_path)
stats = scheduler.run_maintenance()
# stats.vacuumed / stats.analyzed / stats.orphaned_cleaned / ...
```

### 22.2.5 `errors.py` — 异常类型

```python
from zeloo_state.errors import (
    ZelooStateError,       # 基异常
    MigrationError,         # 迁移失败
    RepairError,            # 修复失败
    SchemaError,            # Schema 错误
    SessionNotFoundError,   # 会话不存在
    MessageNotFoundError,   # 消息不存在
    StateCorruptError,      # 状态损坏
    StateLockError,         # 状态锁定
    MaintenanceError,       # 维护失败
    ValidationError,        # 验证失败
)
```

### 22.2.6 `guard.py` — 状态写锁

防止并发写入导致数据库损坏：

```python
from zeloo_state.guard import StateGuard

guard = StateGuard(db_path)
guard.acquire_write_lock(session_id, timeout=5.0)
# ... 执行写入操作 ...
guard.release_write_lock(session_id)
```

### 22.2.7 `readpool.py` — 只读连接池

独立的只读连接池，避免读操作阻塞写操作：

```python
from zeloo_state.readpool import ReadConnectionPool

pool = ReadConnectionPool(db_path, pool_size=4)
conn = pool.get_connection(timeout=5.0)
# ... 执行只读查询 ...
pool.return_connection(conn)
```

### 22.2.8 其他子模块

| 模块 | 说明 |
|------|------|
| `usage.py` | Token 用量追踪 |
| `fts.py` | FTS5 全文搜索封装 |
| `gateway.py` | 网关状态管理 |
| `wal.py` | WAL 模式细粒度控制 |
| `sessions.py` | 会话生命周期（归档/恢复/合并/统计） |
| `registry.py` | 状态注册表 |

---

## 22.3 顶层状态文件

### 22.3.1 `zeloo_state.py` — SessionDB 核心

提供会话管理、消息持久化、轨迹存储等核心功能：

```python
from zeloo_state import SessionDB

db = SessionDB()
session = db.create_session(session_id="sess-001", platform="telegram")
db.save_message(session_id="sess-001", role="user", content="Hello")
messages = db.get_messages(session_id="sess-001")
db.save_turn(session_id="sess-001", turn_id=1, data={...})
```

### 22.3.2 `zeloo_state_messages.py` — 消息搜索状态管理

消息持久化与 FTS5 搜索：

```python
from zeloo_state_messages import (
    save_message,
    get_messages,
    search_messages,  # FTS5
)
```

### 22.3.3 `zeloo_state_search.py` — 全局搜索状态管理

全局搜索状态：

```python
from zeloo_state_search import (
    search_all,
    get_recent_sessions,
)
```

### 22.3.4 `zeloo_state_schema.py` — Schema 管理

Schema 版本管理（与 `zeloo_state/schema.py` 协同）：

```python
from zeloo_state_schema import (
    SCHEMA_VERSION,
    ensure_schema,
    get_schema_version,
    migrate,
)
```

### 22.3.5 `zeloo_state_repair.py` — 数据库修复

数据库自诊断与修复（与 `zeloo_state/repair.py` 协同）：

```python
from zeloo_state_repair import (
    RepairIssue,
    RepairReport,
    StateRepair,
)
```

---

## 22.4 测试覆盖

| 测试文件 | 覆盖模块 | 用例数 |
|----------|----------|--------|
| `test_state_schema_repair.py` | schema / repair | 12 |
| `test_messages_search.py` | messages / search | 12 |
| `test_agent_pipeline.py`（integration） | 完整 pipeline | 12 |
