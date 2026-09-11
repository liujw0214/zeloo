---
name: db-schema
description: 数据库 schema 设计与优化，覆盖范式选择、主键策略、索引规划、分区与分片
platforms: [cli, tui, api]
toolsets: [file, terminal, code_execution]
---

# Database Schema Design

设计与优化关系型 / 时序 / 文档型 schema：实体识别、范式选择、主键、索引、分区、分片、迁移。

## Triggers（触发条件）

- "design schema" / "create table" / "index strategy"
- "数据库设计" / "建表" / "索引怎么加"

## 工作流程

### 1. 实体与关系识别

- 列出所有实体（名词）和属性
- 标注关系：一对一 / 一对多 / 多对多
- 区分核心实体（必须强一致）vs 附属实体（可最终一致）
- 输出 ER 草图后再写 DDL

### 2. 范式选择

| 范式 | 适用 |
|---|---|
| 1NF | 原子字段，无重复组 |
| 2NF | 1NF + 非主属性完全依赖主键 |
| 3NF | 2NF + 消除传递依赖 |
| BCNF | 每个决定因子都是候选键 |

经验法则：

- 默认 **3NF**，写多读少的 OLTP
- 读多写少 / 高 QPS 的报表场景，允许**适度反范式**（缓存列、汇总表）
- 时序数据不要按 3NF 拆，按时间分区更划算

### 3. 主键策略

| 类型 | 场景 |
|---|---|
| 自增 BIGINT | 单库、低写入、无对外暴露 |
| UUID v4 | 分布式、对外暴露、防爬取 |
| UUID v7 | 分布式 + 时序友好（推荐替代 v4） |
| 雪花 ID | 分布式 + 趋势递增 |
| 复合主键 | 关联表 `(a_id, b_id)` |

原则：

- 主键尽量**稳定**：不要用业务字段（邮箱、手机号）
- 主键尽量**短**：聚簇索引按主键物理排序
- 对外暴露用 ID + 单独的 `public_id`（如 nanoid）

### 4. 索引设计

| 类型 | 场景 |
|---|---|
| 主键 / 聚簇索引 | 默认存在 |
| 唯一索引 | 业务唯一约束（`email`、`(tenant_id, slug)`） |
| 普通二级索引 | `WHERE` / `ORDER BY` 字段 |
| 复合索引 | 多列查询，遵循最左前缀 |
| 覆盖索引 | `SELECT` 列全部在索引中，避免回表 |
| 部分索引 | `WHERE status = 'active'` 子集 |
| 函数索引 | `WHERE lower(email) = ?` |
| GIN | 数组 / jsonb / 全文检索 |

陷阱：

- 单表索引数控制在 **5 个**以内，过多拖累写入
- 区分度高（`user_id`）的列放复合索引**前**面
- 避免对长字段（`TEXT`）直接建索引，必要时用前缀索引

### 5. 时间戳与审计

每个表的标准列：

```sql
created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
created_by  BIGINT,
updated_by  BIGINT
```

- `TIMESTAMPTZ` 而不是 `TIMESTAMP`：避免时区陷阱
- `updated_at` 用 trigger / ORM 自动维护

### 6. 软删除

```sql
deleted_at TIMESTAMPTZ  -- NULL = 存活
```

配套：

- 唯一索引改成部分索引：`UNIQUE(email) WHERE deleted_at IS NULL`
- 查询模板加 `WHERE deleted_at IS NULL`
- 定期物理清理（保留期 ≥ 90 天）

### 7. 多态关联

不推荐：单表 `parent_type + parent_id`

更稳：每个实体类型单独关联表

```
comments
├─ article_comment(article_id, ...)
├─ photo_comment(photo_id, ...)
└─ video_comment(video_id, ...)
```

如果必须做多态：

```sql
commentable_type VARCHAR(32) NOT NULL,
commentable_id   BIGINT      NOT NULL,
INDEX (commentable_type, commentable_id)
```

### 8. 层次结构

| 方案 | 优点 | 缺点 |
|---|---|---|
| 邻接表（`parent_id`） | 写入简单 | 递归查询慢 |
| 路径枚举（`path`） | 祖先查询快 | 移动子树复杂 |
| 嵌套集 | 整树读取极快 | 写入开销大 |
| 闭包表 | 查询灵活 | 额外存储 |

按查询模式选择，不要追求"通用"。

### 9. 分区与分片

**何时分区**：

- 单表 > 1 亿行
- 时序/冷热分层
- 按时间窗口清理

**分区策略**：

- 按时间（最常见）：`PARTITION BY RANGE (created_at)`
- 按哈希：`PARTITION BY HASH (user_id)`
- 按列表：`PARTITION BY LIST (region)`

**何时分库分表**：

- 单库写入 > 5k QPS 或单表 > 500GB
- 优先**垂直拆分**（按业务域），再考虑水平拆分

### 10. 迁移规范

- 所有 DDL 走 migration 工具（alembic / flyway / liquibase）
- 一次 migration 只做一件事
- 加列必须 `NULL` 允许或带默认值，避免长时间锁表
- 删除列 / 改类型前先灰度
- 大表加索引用 `CREATE INDEX CONCURRENTLY`（PostgreSQL）

## 模板：用户表

```sql
CREATE TABLE users (
    id           BIGSERIAL PRIMARY KEY,
    public_id    CHAR(21)     NOT NULL UNIQUE,  -- nanoid
    tenant_id    BIGINT       NOT NULL,
    email        CITEXT       NOT NULL,
    name         VARCHAR(120) NOT NULL,
    status       VARCHAR(16)  NOT NULL DEFAULT 'active',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    deleted_at   TIMESTAMPTZ,
    CONSTRAINT users_email_unique UNIQUE (tenant_id, email)
        WHERE deleted_at IS NULL
);

CREATE INDEX users_tenant_status_idx ON users (tenant_id, status)
    WHERE deleted_at IS NULL;
CREATE INDEX users_created_at_idx   ON users (created_at DESC);
```

要点：`public_id` 对外、`email` 按租户隔离唯一、部分索引带软删除条件、`created_at` 走时序索引。

## 反模式

| 反模式 | 修正 |
|---|---|
| 一张表存所有类型（`type + payload JSON`） | 多态关联或 EAV |
| 用 VARCHAR 存日期 | 用 `DATE` / `TIMESTAMPTZ` |
| FLOAT 存金额 | `DECIMAL(precision, scale)` 或整数（分） |
| 缺少外键约束 | 关系强一致必须加 FK |
| 主键随机（UUID v4）造成页分裂 | 改 UUID v7 / 雪花 |
| 滥用 `SELECT *` | 列出字段，节省 IO |

## 验证

- 用真实数据量（10w+ 行）跑 `EXPLAIN ANALYZE`
- 检查是否走索引、是否回表
- 慢查询日志无新条目
- 写入压测：TPS、p99 延迟、锁等待
- 备份恢复演练可执行
