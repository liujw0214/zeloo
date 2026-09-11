# Supabase MCP Server 接入文档

> 本文档介绍如何将 `optional_mcps/supabase.py` 集成到 Zeloo Agent，使 agent 可调用 Supabase 数据库、Auth、Storage 等能力。

---

## 一、Server 概述

| 项目 | 值 |
|------|------|
| Server 名称 | `supabase` |
| 启动模块 | `optional_mcps.supabase` |
| 工具总数 | 10 个 |
| 通信协议 | stdio JSON-RPC 2.0 |
| 认证方式 | `apikey` + `Authorization: Bearer` 双头（Supabase 标准） |
| 外部依赖 | `httpx`（懒加载） |

### 已实现工具

| 工具 | 功能 |
|------|------|
| `supabase_list_tables` | 列出 schema 中的表/视图 |
| `supabase_select` | SELECT 行（支持过滤、列选择、分页） |
| `supabase_insert` | INSERT 一行 |
| `supabase_auth_signup` | 注册新用户（email + password） |
| `supabase_auth_signin` | 登录现有用户（返回 JWT） |
| `supabase_update` | UPDATE 行（支持过滤条件） |
| `supabase_delete` | DELETE 行（支持过滤条件） |
| `supabase_storage_upload` | 上传文件到 Storage bucket |
| `supabase_storage_download` | 下载 Storage 对象为 base64 |
| `supabase_rpc` | 调用 PostgreSQL 函数（`/rest/v1/rpc/<name>`） |

---

## 二、前置条件

### 1. 获取 Supabase 凭据

登录 [Supabase Dashboard](https://supabase.com/dashboard)，打开目标项目：

- **Project URL**：位于 `Settings` → `API` → `Project URL`
  - 形如：`https://<project-ref>.supabase.co`
- **API Key (anon public)**：位于 `Settings` → `API` → `Project API keys` → `anon` `public`
  - 这是一个以 `eyJhbGciOi...` 开头的 JWT
- **API Key (service_role)**（可选，绕过 RLS）：同位置 `service_role` `secret`
  - ⚠️ 此 key 拥有完整数据库权限，请妥善保管

### 2. 配置数据库（可选）

- 在 `Table Editor` 中创建所需表
- 在 `Authentication` → `Policies` 中配置 RLS（推荐）
- 在 `SQL Editor` 中初始化 schema：

```sql
-- 示例：创建 notes 表
create table public.notes (
  id bigserial primary key,
  user_id uuid references auth.users(id) on delete cascade,
  content text not null,
  created_at timestamp with time zone default now()
);

-- 启用 RLS（推荐）
alter table public.notes enable row level security;

-- 示例 policy：允许认证用户读写自己的 notes
create policy "Users manage their own notes"
on public.notes
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);
```

---

## 四、配置 Zeloo Agent

在项目根目录 `config.yaml` 中添加：

```yaml
mcp:
  servers:
    - name: supabase
      transport: stdio
      command: python
      args: ["-m", "optional_mcps.supabase"]
      env:
        SUPABASE_URL: "${SUPABASE_URL}"
        SUPABASE_KEY: "${SUPABASE_KEY}"
```

将凭据写入 `.env`（或在系统中导出为环境变量）：

```bash
# .env
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_KEY=eyJhbGciOi...
```

> **安全提示**：
> - 仓库中**不要**提交 `.env`
> - 使用 `service_role` key 时建议只在服务端使用
> - 生产环境使用 `anon` key + RLS 实现最小权限

---

## 五、启动 MCP Server

### 方式 1：让 Agent 自动加载（推荐）

```bash
Zeloo chat --model gpt-4o
# Agent 会读取 config.yaml → 自动 spawn supabase MCP server → 注册 10 个工具
```

### 方式 2：手动启动（调试用）

```bash
SUPABASE_URL=https://... SUPABASE_KEY=eyJ... \
  uv run python -m optional_mcps.supabase
```

Server 进入 stdio JSON-RPC 2.0 监听模式，等待主进程的 initialize / tools/list / tools/call 请求。

---

## 六、Agent 中的使用示例

启动 `Zeloo chat` 后，agent 会自动发现并注册以下 10 个工具：

```
[supabase_list_tables]   列出 schema 中的表/视图
[supabase_select]        SELECT 行
[supabase_insert]       INSERT 行
[supabase_update]       UPDATE 行
[supabase_delete]       DELETE 行
[supabase_auth_signup]   注册新用户
[supabase_auth_signin]   用户登录
[supabase_storage_upload] 上传文件
[supabase_storage_download] 下载文件
[supabase_rpc]          调用 PostgreSQL 函数
```

### 示例 1：让 agent 查询笔记表

```
> 帮我查询 notes 表中 user_id 是 alice 的最新 5 条笔记
```

agent 内部调用：

```json
{
  "method": "tools/call",
  "params": {
    "name": "supabase_select",
    "arguments": {
      "table": "notes",
      "filters": {"user_id": "alice-uuid-here"},
      "columns": "id,content,created_at",
      "limit": 5
    }
  }
}
```

### 示例 2：让 agent 注册测试用户

```
> 注册一个新用户，邮箱 test@example.com，密码 Test1234!
```

agent 调用：

```json
{
  "method": "tools/call",
  "params": {
    "name": "supabase_auth_signup",
    "arguments": {
      "email": "test@example.com",
      "password": "Test1234!"
    }
  }
}
```

### 示例 3：让 agent 插入笔记

```
> 在 notes 表里插入一条记录，content 是 "Hello Supabase MCP"
```

agent 调用：

```json
{
  "method": "tools/call",
  "params": {
    "name": "supabase_insert",
    "arguments": {
      "table": "notes",
      "values": {"content": "Hello Supabase MCP", "user_id": "..."}
    }
  }
}
```

---

## 七、API 参考

### `supabase_list_tables`

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `schema` | str | `"public"` | schema 名 |
| `limit` | int | `20` | 返回行数上限 |

### `supabase_select`

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `table` | str | — | 目标表名（必填） |
| `filters` | dict | `None` | 列名=值的等值过滤 |
| `columns` | str | `"*"` | 要选择的列 |
| `limit` | int | `20` | 最大返回行数 |

### `supabase_insert`

| 参数 | 类型 | 说明 |
|------|------|------|
| `table` | str | 目标表名（必填） |
| `values` | dict | 列名→值的映射（必填） |

### `supabase_auth_signup`

| 参数 | 类型 | 说明 |
|------|------|------|
| `email` | str | 邮箱（必填） |
| `password` | str | 密码（必填） |

---

## 八、故障排查

| 问题 | 排查方向 |
|------|----------|
| `cannot import name 'supabase'` | 确认 `optional_mcps` 已加入 `pyproject.toml` 的 `include` 列表；执行 `uv pip install -e .` |
| `httpx is not installed` | `uv add httpx` 或确认 `.venv` 中存在 |
| `401 Unauthorized` | 检查 `SUPABASE_KEY` 是否以 `eyJ` 开头；anon key JWT 是否过期 |
| `Row Level Security violation` | 在 Supabase Dashboard 中为对应表添加 SELECT/INSERT policy |
| `relation does not exist` | 确认 `schema` 参数正确；表是否在 `public` 下 |
| Server 启动后立即退出 | 检查 `config.yaml` 中 `args` 路径正确指向 `optional_mcps.supabase` 模块 |

---

## 九、扩展建议

如需添加更多工具，可参考 `optional_mcps/base.py` 中的 `make_tool` 装饰器模式自行扩展。