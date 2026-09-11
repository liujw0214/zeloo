# 12. Cron 定时任务系统

## 12.1 概述

Zeloo 内置轻量级 cron 调度器（`cron/scheduler.py`），支持标准 5 字段 cron 表达式。调度器运行在后台守护线程中，不阻塞 Agent 主循环。

## 12.2 架构

```
zeloo_agent
    └── cron_scheduler: CronScheduler   # 后台守护线程
            └── tick_loop(): 每 tick_interval 秒检查一次
                    └── cron_matches()  # 判断是否触发
                            └── job.callback()  # 执行注册的回调
```

## 12.3 CronScheduler API

```python
from cron.scheduler import CronScheduler, cron_matches, parse_cron

scheduler = CronScheduler(tick_interval=30)  # 默认每 30s 检查一次
scheduler.add_job("backup", "0 2 * * *", callback=lambda: print("backup"))
scheduler.start()   # 启动守护线程
scheduler.stop()    # 优雅停止
```

| 方法 | 说明 |
|------|------|
| `CronScheduler(tick_interval=30)` | 构造，tick_interval 为检查间隔秒数 |
| `add_job(name, expression, callback)` | 注册任务，expression 为 5 字段 cron 字符串 |
| `remove_job(name)` | 按名称删除任务 |
| `list_jobs()` | 返回所有任务摘要（含 name/expression/last_run） |
| `start()` | 启动后台线程（幂等） |
| `stop()` | 停止线程并 join |

## 12.4 调度格式支持

Zeloo 的 cron 调度器支持**四种调度格式**，优先使用最自然的表达方式：

| 格式 | 示例 | 说明 |
|------|------|------|
| Duration | `"30m"` `"2h"` `"1d"` | 相对间隔，固定周期 |
| 自然语言 | `"every 2h"` `"every day at 9am"` | 人类可读表达 |
| 标准 Cron | `"0 9 * * 1-5"` | 5 字段标准格式 |
| ISO 时间戳 | `"2026-09-15T09:00:00Z"` | 一次性精确时间 |

**Duration 格式**：
```
30m    → 每 30 分钟
2h     → 每 2 小时
1d     → 每 1 天
15s    → 每 15 秒
```

**自然语言格式**：
```
every 30m      → 每 30 分钟
every 2h       → 每 2 小时
every day at 9am → 每天 9:00
every weekday    → 每个工作日
```

**加固机制**：
- flock 文件锁：跨进程防重（多实例部署场景，Windows 自动跳过）
- 同分钟去重：`_just_ran()` 防止同一 tick 内重复触发
- 运行历史持久化：JSON 文件记录每次执行时间/结果（默认保留 7 天）
- **多格式支持**：`parse_duration()` 自动识别 Duration shorthand（`30m`/`2h`/`1d`）、自然语言别名（`@hourly`/`@daily`/`@weekly`）和标准 5 字段 cron，自动转换后统一执行

**no-agent 纯脚本模式**：Cron 任务可配置为纯脚本执行（`no_agent: true`），不启动 Agent，零 token 费用运行定时脚本。

## 12.5 cron 表达式（标准 5 字段）

标准 5 字段格式：`分 时 日 月 星期`

| 字段 | 范围 | 示例 |
|------|------|------|
| 分 | 0-59 | `0`, `*/15`, `0,30` |
| 时 | 0-23 | `9`, `0-5`, `*/2` |
| 日 | 1-31 | `1`, `15`, `*` |
| 月 | 1-12 | `1`, `6-8` |
| 星期 | 0-6 | `0`=周日, `1-5`=工作日 |

常见表达式：

| 表达式 | 含义 |
|--------|------|
| `0 9 * * 1-5` | 工作日 9:00 |
| `*/15 * * * *` | 每 15 分钟 |
| `0 0 1 * *` | 每月 1 日 0:00 |
| `30 18 * * *` | 每天 18:30 |
| `0 */2 * * *` | 每 2 小时整点 |

## 12.6 核心解析函数

```python
from cron.scheduler import parse_cron, cron_matches, CronJob

# 解析表达式为 5 个集合
fields = parse_cron("0 9 * * 1-5")
# → [{0}, {9}, {1..31}, {1..12}, {1,2,3,4,5}]

# 检查当前时间是否匹配
from datetime import datetime
cron_matches("0 9 * * 1-5", dt=datetime(2026, 9, 7, 9, 0))  # 周一 9:00 → True

# 构造 Job 对象
job = CronJob(name="backup", expression="0 2 * * *", callback=my_callback)
```

## 12.7 防重复触发

`_just_ran()` 通过对比 `last_run` 时间戳，确保同一任务在同一分钟内不会重复执行：

```python
# 同一分钟内多次 tick，只触发一次
if self._matches(job, now) and not self._just_ran(job, now):
    job.callback()
    job.last_run = now.timestamp()
```

## 12.8 接入工具

Agent 通过 `cron_add`/`cron_list`/`cron_remove` 工具与调度器交互：

```
Agent: cron_add(name="daily_backup", expression="0 2 * * *", command="tar czf /backup/data.tar.gz /data")
Agent: cron_list()
daily_backup: 0 2 * * * (last_run=None)
Agent: cron_remove(name="daily_backup")
```

## 12.9 与系统 cron 的区别

| 维度 | Zeloo CronScheduler | 系统 cron |
|------|----------------------|-----------|
| 精度 | 秒级（tick_interval） | 分钟级 |
| 执行环境 | Python 进程内 | 系统级独立进程 |
| 持久化 | 进程内存（历史记录 JSON 持久化） | /etc/crontab 文件持久 |
| 适用场景 | Agent 内动态任务 | 系统管理员任务 |

建议：短生命周期、Agent 控制的任务用 CronScheduler；需要持久化或系统级权限的任务用系统 cron。
