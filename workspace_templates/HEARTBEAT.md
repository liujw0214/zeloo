# HEARTBEAT.md — 后台定时任务清单

> 加载优先级:项目 `.zeloo/workspace/HEARTBEAT.md` > `~/.zeloo/workspace/HEARTBEAT.md` > 本文件
> **这是 Agent 的定时任务清单**。cron / Gateway 心跳会周期性读取,并把每条转换成 cron job。
> 本文件不被 seed 到 memories/——它走独立的 schedule 管道(经 `cron/scheduler.py`)。

---

## 语法

| 字段 | 说明 |
|------|------|
| `name` | 唯一任务名(重复会覆盖) |
| `cron` | 标准 5 字段 cron 表达式(`* * * * *`),不支持「每月第三个星期五」这类表达 |
| `tz` | IANA 时区(缺省则用 `Asia/Shanghai`),不会在 prompt 里面告诉用户 |
| `prompt` | 触发后跳出的任务描述(会被打包成 `cron scheduler_prompt.py` 的 system message) |
| `enabled` | `true` / `false`,缺省 `true` |
| `delivery` | `steer` / `follow_up` / `auto`,缺省 `auto`(steer 立刻注入、follow_up 等下个轮开始、auto 根据忙/闲状态选) |
| `owner` | `user` / `agent`,缺省 `user`(`agent` 表示 Agent 自己加的,删除时要询问一下) |

## 任务清单

<!-- 格式:以下 YAML 代码块,每个 `- name:` 是一个独立任务。删掉某个块 = 删任务。 -->

```yaml
- name: healthcheck
  cron: "*/30 * * * *"
  tz: Asia/Shanghai
  prompt: 运行 `Zeloo doctor` 并上报任何告警。如果全部健康,返回「全部健康」。
  delivery: steer
  owner: agent

- name: state_backup
  cron: "0 2 * * *"
  tz: Asia/Shanghai
  prompt: 复制 `~/.Zeloo/state.db` 到 `~/.Zeloo/backups/state-$(date +%Y%m%d).db`。仅当今日备份不存在时创建。
  delivery: follow_up
  owner: agent

- name: memory_consolidate
  cron: "0 3 * * 0"
  tz: Asia/Shanghai
  prompt: 检查 `~/.Zeloo/memories/MEMORY.md` 超过 1800 字的卡片,只保留上一周被读过的、去掉过期的。
  delivery: steer
  owner: agent
```

## 读取行为

1. cron tick 刷新时(默认每 60s)读取本文件,解析为 `cron.jobs.Job` 对象
2. 同名任务会去重并覆盖现有(避免 cron table 越来越膨胀)
3. `enabled: false` 的任务不被调度但仍在清单里(可以用来临时暂停)
4. `owner: user` 的任务被删除前需询问;`owner: agent` 的可由 Agent 自己动
5. 任务触发后,会调 `scheduler_prompt.build_prompt(name, prompt)` 打包为 system message 推送给 LLM

## 与其他文件的关系

| 文件 | 关系 |
|------|------|
| `MEMORY.md` | 定时任务的结果(如 backup 成功)会被记下来 |
| `USER.md` | `tz` 字段缺省时从 USER.md 读取用户时区 |
| `TOOLS.md` | `prompt` 里调用的工具(如 `Zeloo doctor`)需要 TOOLS.md 里已启用 |
| `IDENTITY.md` | 推送给 LLM 时会加上 Agent 身份头(「你是某某」) |
| `AGENTS.md` | 多 Agent 场景下,每个 Agent 会只扫自己名字开头的任务块 |

---

> 提示:本文件默认**不**被 `zeloo init` seed(保护用户主动选择)。
> 手动复制:从 `workspace_templates/HEARTBEAT.md` 复制到 `.zeloo/workspace/HEARTBEAT.md` 即可。
> 验证语法: `Zeloo doctor --check heartbeat-manifest`。
