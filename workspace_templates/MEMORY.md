# MEMORY.md — 长期记忆

> 加载优先级:项目 `.zeloo/memories/MEMORY.md` > `~/.zeloo/memories/MEMORY.md` > 本文件
> **这是 Agent 的长期记忆库**,每次会话开始时会被加载到 context 的顶部。
> 所有标记 `#Memory` 的条目都是持久化的,会话结束后仍然保留。
> 本文件不参与 RAG embedding——它直接进入 system prompt。

---

## 用途

MEMORY.md 是 Agent 的**外部记忆文件**,解决了 LLM 上下文窗口有限、无法记住所有历史细节的问题。
它比向量数据库轻量、比内部 history 可靠,适合存放:

- 用户偏好(语言、时区、回复风格、项目技术栈)
- 未完成的后续任务(TODO / 后续跟进)
- 关键决策记录(为什么选了 X 而不是 Y)
- 上下文快照(当前在处理哪个项目、什么阶段)
- 错误教训(踩过的坑、日后避免)

---

## 内容组织

文件采用**时间线 + 标签**双轨组织:

### 1. 固定区块(必须存在)

```
# [用户偏好]
---
# [当前项目]
---
# [待跟进]
---
# [历史教训]
---
```

每次新增记忆,按时间顺序追加到对应区块,**不要**修改旧条目。

### 2. 记忆条目格式

```markdown
## [时间戳] [标签] 主题

正文内容。一段话说不完就分段,保持可读性。
关键信息用 **加粗** 标注。

> 关联:TOOLS.md / AGENTS.md / HEARTBEAT.md
```

标签可选: `#Preference` `#Project` `#Decision` `#Error` `#Context`

### 3. 示例条目

```markdown
## [2026-09-10] #Project Zeloo WSL 集成

用户采用 WSL + Windows 双栈架构。WSL 内运行 Python/Node,Windows 跑 GUI Shell。
两边的 workspace 通过 `~/.Zeloo/` 共享状态文件(SQLite + JSON)。
目前 agent.py 在 Windows 侧,WSL 侧只跑工具脚本。
待完成:WSL 侧 Agent 主进程迁移。

## [2026-09-12] #Error PostgreSQL 连接超时

`state.db` 从 SQLite 切到 PostgreSQL 时,connection pool size 默认 10 太小。
高峰期 `psql: too many connections` 导致 `/status` 端挂。
修复:pg_bouncer max_client_conn=200, pool_size=30。
```

---

## 写入规则

| 规则 | 说明 |
|------|------|
| 自动写入 | Agent 在**会话结束时**自动追加本次关键上下文 |
| 手动写入 | 用户说「记住 XXX」→ 立刻写,不等到结束 |
| 清理触发 | HEARTBEAT `memory_consolidate` 任务会定期精简(去重+去旧) |
| 不写什么 | 纯会话闲聊、错误尝试过程、临时中间变量 |
| 最大长度 | 单文件建议不超过 2000 行;超出时触发 consolidate |

---

## 与其他文件的关系

| 文件 | 关系 |
|------|------|
| `IDENTITY.md` | 会话开始时,IDENTITY + USER + MEMORY 一起拼入 system prompt |
| `USER.md` | MEMORY 中的 `#Preference` 条目优先级高于 USER.md(实时 > 静态) |
| `HEARTBEAT.md` | `memory_consolidate` 定时任务负责精简本文件 |
| `AGENTS.md` | subagent 写的记忆需 `owner: agent` 标记,主 agent 清理时询问用户 |

---

## 自检命令

- 查看记忆总数: `Zeloo memory --stats`
- 搜索记忆: `Zeloo memory --grep " Zeloo "`
- 导出为 JSON: `Zeloo memory --export memories.json`
- 手动触发 consolidate: `Zeloo memory --consolidate`

---

> 提示:本文件**不**被 `zeloo init` 覆盖(除非用户主动 `zeloo memory --reset`)。
> 它是用户最重要的数据资产,请定期通过 `~/.Zeloo/backups/` 备份。
