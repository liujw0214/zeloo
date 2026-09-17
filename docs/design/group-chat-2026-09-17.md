# Group Chat / Multi-Agent 协作 — 设计报告

> Date: 2026-09-17 · Status: design exploration · Author: <delegated agent>
> 范围:把老板提的 10 个群聊多 Agent 能力点对照仓库的现有实现,**先盘点再设计**。
> 这不是从 0 设计 — Bot Mode 已经是生产级的群聊实现,需要回答的是「还差什么、按什么顺序补」。

---

## 0. 关键发现(写在前面的 TL;DR)

**Bot Mode 已经在 `main` 上线**(`website/docs/user-guide/bot-mode.md`、desktop app 默认开启),
架构是「**一个 Bot = 一个 Zeloo profile**」+ gateway 上的持久化 hosted-room + 跨机器 peer relay。
老板提的 10 项里 **8 项已落地、1 项部分落地、1 项真的是新工作**:

| # | 老板需求 | 落地状态 | 主要落点 |
|---|---|---|---|
| 1 | 多 Agent 独立身份 | ✅ 已落地 | profile 隔离(`~/.Zeloo/profiles/<name>/`)+ Bot 元数据 |
| 2 | 群聊房间 | ✅ 已落地 | `gateway/hosted_rooms.py`(1182 行 SQLite 持久化) |
| 3 | @召唤 | ✅ 已落地 | `hosted_room_discussion.py::resolve_mentions`(正则解析 + `@all`) |
| 4 | 任务分配(Agent 之间派活) | ⚠️ 部分落地 | `message_agent` 仅「DM」语义;**「派活带目标+验收」未做** |
| 5 | 进度状态共享 | ⚠️ 部分落地 | room log 显示发言;**无结构化进度字段**(thinking/tool_call/waiting_child) |
| 6 | 持久记忆 | ✅ 已落地 | memory provider(`agent/memory_manager.py`)+ cron Routines |
| 7 | 子 Agent 途中纠偏 | ❌ 未落地 | `SubagentLaunchRequest.cancel()` 是协作中断;**没有「主 Agent 改主意」通道** |
| 8 | 安全机制(并发/权限) | ⚠️ 部分落地 | 每个 Bot 是独立 profile(profile 隔离是天然边界);**没有跨 Bot 的文件锁** |
| 9 | 主动撤回(撤回消息/终止任务/撤销副作用) | ⚠️ 部分落地 | `room.stop_requested`、`groups.stop`、peer stop;**没有「已发出消息编辑/删除」、没有副作用 rollback 框架** |
| 10 | 信息共享(事实/上下文/知识) | ⚠️ 部分落地 | `@all` 广播 + room log;**没有「跨 Bot 共享 factsheet」、没有「群上下文压缩」组件** |

**真实的新设计工作只有 3 块**(见 §10 MVP):
- 群聊内结构化 **进度事件**(thinking/tool_call/waiting_child/done),让「Alice 在 git push」可见
- **主 Agent 中途改主意**通道(steer 当前子 Agent + 重新派活)
- **跨 Bot 共享 factsheet**(room-level context cache,降低每次 @-mention 重新解释的成本)

剩下的功能要么直接是 Bot Mode,要么按现状就能满足;**不要重新造轮子**。

---

## 1. 现有能力盘点(对照原始需求逐项)

### 1.1 Bot Mode 已落地的能力(详细对应)

老板的 1/2/3/6 完全覆盖在 Bot Mode 里。具体证据:

**① 多 Agent 独立身份** —
- `~/.Zeloo/profiles/<bot>/` 完全隔离的 config、memory、skills、credentials、cron
- 每个 Bot 有自己的 model pin、`SOUL.md`、toolset 启停
- 进程级隔离(默认 3 个 warm backends,`website/docs/user-guide/bot-mode.md:259-262`)
- → 独立身份 = profile,无新设计

**② 群聊房间** — `gateway/hosted_rooms.py` 完整实现:
- SQLite 持久化:`hosted_rooms`、`hosted_room_events`(append-only seq 排序)、`hosted_room_links`、`hosted_room_remote_runs`、`hosted_room_peer_reservations`(lines 87-148)
- 256 字节/事件上限、50K 事件/房、16MB gateway 总配额(events budget,lines 39-44)
- 跨网关同步:`hosted_room_replicas` + `groups.replicate`/`groups.replica_state`(`bot-mode.md:188-241`)
- 每房间 `authority_gateway_id` + `authority_epoch` 单一权威者,防止脑裂(防脑裂 checklist 见 `bot-mode.md:194-248`)
- → 群聊房间 = 已落地,且比需求里描述的「多 Agent 在同一房间看消息」严格得多

**③ @召唤** — `hosted_room_discussion.py::resolve_mentions`(lines 291-307):
```python
_MENTION_RE = re.compile(r"@([A-Za-z0-9][A-Za-z0-9._:-]*)", re.IGNORECASE)
# 解析 → by_handle 字典 → 默认 everyone 或 @all
# 同时支持 reserve handle "@all"/"@everyone"
```
- 确定性策略(pure function,no I/O) — 同样输入同样输出,重启可重建(line 4)
- 成员 handle 唯一 + 不可占用 `@all`/`@everyone` 保留字(line 252-260)
- 上限:6 成员/房、3 轮/回合、10 条/回合(line 25-28),防自旋
- Composer 自动补全、跨设备 disambiguation `@name-device`(`bot-mode.md:106、113`)
- → @召唤已落地,且有上限约束(老板需求里的「@召唤」恰好就是这套)

**⑥ 持久记忆** —
- `agent/memory_provider.py`(ABC)+ `agent/memory_manager.py`(provider 编排)
- pre-compress checkpoint hook(`PRE_COMPRESS_CHECKPOINT_API_VERSION`,`memory_manager.py:20`)
- Bot Mode 的 Routines = cron job,以 Bot profile 为单位(`bot-mode.md:83-85`)
  ```yaml
  # 例:每 6 小时扫新闻 → 该 Bot 的 cron job
  Zeloo cron create "every 6h" "Scan for news" --continuity
  ```
- Continuity 模式:后续 cron 触发自动接续 Bot Chat(`cron.md:839`)
- → 持久记忆已落地,Bot Routines 是已有的「定时任务持久记忆」

### 1.2 部分落地(4 项)— 各自缺什么

**④ 任务分配**:
- ✅ Bot-to-bot DM: `message_agent(target="researcher", message="…")`,validates target against live roster, fire-and-forget(`bot-mode.md:114`)
- ✅ 长任务: `Zeloo peer run <peer> --idempotency-key <key>` — 异步、可重试、poll status、`peer stop` 中断(`cli-commands.md:472-497`)
- ❌ **缺**:**结构化「派活」语义** — 现在 message_agent 是「给同事发消息」,不是「分配一个有 deadline + deliverable 的任务」。如果老板说「让 Bob 在 30 分钟内把 X 做完」,现在没有「派活 → 进度回报 → 验收」数据流。
- ❌ **缺**:**派活可见性** — 主 Agent 派给 Bob 后,主 Agent 的 prompt 里只看到「DM 已发」,不跟踪 Bob 完成了没有。要看 Bob 在干嘛得切到 Bob 的 Bot Chat。

**⑤ 进度状态共享**:
- ✅ Room log 显示「谁说了什么」+ 时间戳(`bot-mode.md:99`)
- ✅ Active-now 过滤:owner of focused live turn, 90 秒内有发言的,有心跳的(`bot-mode.md:21`)
- ❌ **缺**:**结构化 progress events** — 现在只有「message.member」一种状态。「Alice 在 git push」无法表达。需要扩展 `hosted_room_events` 的 kind 或加新的 gateway-author 事件:
  - `agent.thinking` — LLM 思考中(可带 model 标签)
  - `agent.tool_call` — 正在执行哪个工具(可带 tool_name、args 摘要)
  - `agent.waiting_child` — 等待子 Agent(subagent_lifecycle handle)
  - `agent.done` / `agent.failed` / `agent.cancelled` — 终态
- 这正是老板要的「Alice 在执行 git push」可见性的来源。

**⑧ 安全机制**:
- ✅ Profile 隔离 = 天然权限边界(每个 Bot 只能访问自己的 `~/.Zeloo/profiles/<bot>/`)
- ✅ Cross-gateway 权限通过 `API_SERVER_KEY`(`bot-mode.md:175`、peer auth)
- ✅ `delegate_task` 的 role 边界: `leaf` 默认屏蔽 `delegate_task`/`clarify`/`memory`/`send_message`/`cronjob`,只有 `orchestrator` 才能再派活,且受 `delegation.max_spawn_depth` 限制(`tools/AGENTS.md`)
- ❌ **缺**:**跨 Bot 共享 workspace 的并发控制** — 现在没有 file lock,如果两个 Bot 同时 `git push` 到同一分支会冲突。Kanban 有 workspace 隔离(`ZELOO_KANBAN_BOARD` env 钉死,`cron/AGENTS.md`),但 Bot Mode 的 room 没继承这个机制。
- ❌ **缺**:**敏感操作的二次确认** — 当前 `dangerous_command` 走 `approval_callback`(`agent-loop.md:144`),但仅在「当前 Bot」上下文中。如果一个 Bot 在 group 里说「让我跑 `rm -rf`」,其他 Bot 看不见这条审批请求 — 应该**只让 Owner 看到**(已在 `bot-mode.md:101` 描述的「needs you badge」),实现可能已部分存在,需核对 `room.activity`/`pending_approvals` 字段。

**⑨ 主动撤回**:
- ✅ **终止正在跑的任务**:`groups.stop`(room 整体停)、`peer stop <peer> <run_id>`(单 run 中断)、`SubagentLaunchRequest.cancel()`(协作中断)
- ✅ **房间解散**:`groups.disband` + tombstone(90 天保留)
- ⚠️ **撤回房间里的某条消息**:hosted_rooms 是 append-only(`gateway/hosted_rooms.py:101-113`),**没有 delete/update**。需要新增 `redact_event(room_id, event_id)` 写一条 `event.redacted` 而非物理删除 — 与 append-only 不矛盾,且保留审计线索。
- ❌ **缺**:**副作用 rollback 框架** — 「Agent 已发的 commit / 已 push 的 branch / 已运行的 terminal command」没有统一的撤销入口。Kanban 有 `kanban_complete` + `request_changes`,但那是 task 级别,不是 command 级别。
  - 部分可借现有机制:terminal 命令是 sandbox 进程(`tools/environments/`),Docker backend 可重建容器;但 git 操作需要单独工作流。

**⑩ 信息共享**:
- ✅ `@all` 广播 + room log(`hosted_room_discussion.py:301-307`)
- ✅ Bot Chat 启动时自动注入「team roster(姓名+角色+device)」(`bot-mode.md:114`)
- ❌ **缺**:**跨 Bot 的 factsheet**(共享事实/上下文/知识) — 现在每个 Bot 各自读文件,没有「群级别的 shared context cache」。比如讨论结束后,「今天决定的方案 X」应该有一个地方所有 Bot 都能查到,而不是各自让 Bob 再读一遍 room log。
- ❌ **缺**:**群上下文压缩** — 群聊超过 X 条消息后,room log 应该自动压缩成 summary 注入新成员的 prompt,而非原样塞历史。

### 1.3 完全没做(1 项)

**⑦ 子 Agent 途中纠偏(主 Agent 改主意)**:
- 现在: `SubagentLaunchRequest.cancel()` 是「协作中断」,子 Agent 在下一安全边界停下。**但子 Agent 停下之后,主 Agent 没有任何通道重新派活、调整方向、改 requirement**。
- 缺的是: **steer-with-redirection**,不只是 cancel。
  - 子 Agent 正在执行 `Bash(git fetch)`,主 Agent 想改成 `Bash(git fetch --all)`,现在做不到
  - 子 Agent 已经 fetch 完准备 `git rebase`,主 Agent 想改成 `git merge`,只能 cancel 重派
- 这其实是 `subagent.steer({session_id, subagent_id, text})` RPC 已存在(`tui_gateway/AGENTS.md` 中段),用于「向子 Agent 注入额外 instruction」;但**用在 group chat 上下文里没有现成的 pattern** — 谁有权 steer?何时 steer?对其他房间成员怎么可见?

### 1.4 现有能力总表

| 维度 | 仓库位置 | 行数/规模 | 状态 |
|---|---|---|---|
| Profile 隔离 | `zeloo_constants.py` + `docs/design/multiplexing-gateway.md` | 设计文档 208 行 | ✅ 已落地 |
| Bot 装配 UI | `apps/desktop/src/.../bot*.tsx` + `website/docs/user-guide/bot-mode.md` | 用户文档 281 行 | ✅ 已落地 |
| Room 持久化 | `gateway/hosted_rooms.py` | 1182 行 SQLite schema | ✅ 已落地 |
| Room Discussion 策略 | `gateway/hosted_room_discussion.py` | 792 行,纯函数 | ✅ 已落地 |
| Room Driver(turn 调度) | `gateway/hosted_room_driver.py` | - | ✅ 已落地 |
| Cross-gateway 同步 | `gateway/hosted_room_replicas.py` + `gateway/hosted_room_peer.py` | - | ✅ 已落地 |
| Room RPC | `tui_gateway/methods_groups.py` | 17 个 method | ✅ 已落地 |
| Room Service 后台 | `tui_gateway/hosted_room_service.py` + `hosted_room_driver.py` | 629/983 行 | ✅ 已落地 |
| Bot-to-bot DM | `message_agent` tool(在 `bot_mode_protocol` 中) | - | ✅ 已落地 |
| Cross-machine Bot DM | `Zeloo peer` CLI | - | ✅ 已落地 |
| Bot Routines | cron jobs namespaced `[bot:<name>]` | - | ✅ 已落地 |
| Memory provider ABC | `agent/memory_provider.py` | - | ✅ 已落地 |
| Memory manager | `agent/memory_manager.py` | 836 行 | ✅ 已落地 |
| Delegate task | `tools/delegate_tool.py` | 737+ 行(含子文件) | ✅ 已落地 |
| Kanban 调度 | `zeloo_cli/kanban.py` + dispatcher | - | ✅ 已落地 |
| **结构化 progress events** | **缺** | - | ❌ |
| **Steer-with-redirection** | 仅 `subagent.steer` RPC,**无 group 模式** | - | ⚠️ |
| **跨 Bot 共享 factsheet** | **缺** | - | ❌ |
| **跨 Bot workspace 锁** | **缺**(Kanban 有 board 隔离) | - | ❌ |
| **已发消息 redact** | **缺**(append-only) | - | ❌ |
| **副作用 rollback 框架** | **缺** | - | ❌ |

---

## 2. 架构方案(关键决策)

### 2.1 决策:**不要新建 `MultiAgentGroup` facade**

❌ 提议: 「为群聊写一个新的 `MultiAgentGroup` 类,把多个 AIAgent 包起来」
✅ 反提议: **继续把每个 Bot 当成一个普通 profile**。Bot Mode 的成功恰恰证明了这条路是对的 — 「一个 Bot = 一个 profile」让所有现有工具/权限/cron/memory 自动复用,**新写 facade 会把整套体系切两半**。

理由(用具体文件):
- `zeloo_constants.py::get_zeloo_home()` + `set_zeloo_home_override()` 已经支持 profile-scoped 一切资源 — `docs/design/multiplexing-gateway.md:111-118`
- 每个 profile 已经独立 session、cron、memory、skills(`bot-mode.md:13`)
- 现有的 `delegate_task` 已经是「从主 Agent 派一个子 Agent」模型(`tools/delegate_tool.py:294` 的 `_run_single_child`),**它就是 Bot Mode 跨 Bot 派活的功能等价物** — 只是 message_agent 没有用 delegate_task 的 role/timeout/result API。

### 2.2 决策: **共享 room DB,各自 profile DB**

- Room state:**全部 gateway-owned SQLite**(`gateway/hosted_rooms.py:1-9`),所有 Bot 共用一份 `state.db` 里的 hosted_room_events 表
- 每个 Bot 自己的 state.db(profile-scoped):sessions、memory、cron、skills — 完全独立
- 跨网关:每个 gateway 各一份 room replica(`hosted_room_replicas`)+ authority_epoch 单权威(`hosted_rooms.py:91-93`)
- **设计含义**:Room 是「跨 profile 的共享平面」,Bot profile 是「独立执行环境」。两者职责清晰,不要混。

### 2.3 ContextVar 隔离 — **沿用现有,不重做**

- ZELOO_HOME override 是 ContextVar(`zeloo_constants.py`,`multiplexing-gateway.md:111`),已经被 multiplexing 设计验证
- 群聊 turn 调度走的是 `hosted_room_driver` — 调用每个 Bot 时**该 Bot 的 profile override 必须装上**,否则会读到默认 profile 的 state
- 现成实现: `_profile_runtime_scope()` 在 `gateway/run.py`(被 `multiplexing-gateway.md:48-58` 描述)已经做这件事,hosted_room_driver 需要确认**在 spawn 每个 member turn 时也包了一层**(待验证,见 §11)

### 2.4 Prompt caching 边界 — **绝对不能破**

AGENTS.md 第一条硬规矩(`/root/zeloo/AGENTS.md:18-21`):

> Per-conversation prompt caching is sacred.

群聊带来的风险点(必须避开):
- **不能因为「新消息来了」就重 build 系统提示**。如果 group chat driver 把新成员消息当作 system prompt 注入 → 缓存必破。
- **正确做法**: room 新消息以 **user role** 追加到 Bot 的 Bot Chat session(`history:「user: 房间里的 Bob 刚才说了 ...」`),不动 system prompt。这正是 Bot Mode 的现有做法 — canonical Bot Chat 的 messaging protocol 是静态 system 段(`bot-mode.md:118-123`),不是每条消息都重 build。
- 同理,@召唤触发 Bot 的 turn 时,room context 以 tool result message 形式注入(`agent/AGENTS.md:23-30` 描述「skill slash commands inject as a user message, never the system prompt」)。**待验证的细节**:hosted_room_driver 是否已经按这条规矩办?如果还没有,这是必须补的实现 bug,不是设计取舍。

### 2.5 决策: **复用 `delegate_task` 做「派活」语义**

老板要的「Agent 之间能互相派活」其实有两种:
1. **DM 风格派活** — Bot A 说「Bob,帮我看下这个 bug」,Bot B 自己决定怎么处理(已经是 message_agent 的语义,不动)
2. **任务式派活** — Bot A 说「Bob,在 30 分钟内完成 X,完成后告诉我」,需要 status/deadline/result

设计选择: **在 `message_agent` 之上加一个 `assign_task` 工具**,而不是另起一套。理由:
- `delegate_task` 已经有 role/timeout/result/slot_key 全套语义(`tools/AGENTS.md:100-105`)
- `message_agent` 是 fire-and-forget(`bot-mode.md:114`),没法做任务式
- **复用 delegate_task 的 lifecycle API**(`subagent_lifecycle.py`),把 `target` 从本地 profile 扩成「跨 Bot」即可,技术上不新,只是 wiring 改动

### 2.6 决策: **进度事件作为新 `kind` 加到 hosted_room_events**

不另起一套事件总线 — append-only 的 hosted_room_events 表已经是事实上的 room event log(`hosted_rooms.py:101-113`)。

新 `kind`(全部归在 `gateway` actor 下,与现有 `_EVENT_KINDS_BY_ACTOR["gateway"]` 一致,见 `hosted_rooms.py:52-54`):
```
agent.thinking          # payload: { agent_id, model?, started_at }
agent.tool_call         # payload: { agent_id, tool_name, args_summary, started_at }
agent.waiting_child     # payload: { agent_id, child_handle, child_goal_summary }
agent.assigned_task     # payload: { agent_id, task_id, deadline?, goal_summary }
agent.task_progress     # payload: { agent_id, task_id, percent?, message }
agent.task_done         # payload: { agent_id, task_id, result_summary, duration_ms }
agent.task_failed       # payload: { agent_id, task_id, reason_code, error_excerpt }
agent.steered           # payload: { from_agent_id, to_agent_id, subagent_id, text }
```

**事件计数 500K/房、16MB gateway total**(hosted_rooms.py:39-44),这些细粒度事件要 throttle — 默认 1 条 tool_call + 1 条 tool_call_done,中间不发(类似现有 delivery transport `metadata["_interim_send"]` 模式)。

---

## 3. 群聊消息流(沿用 Bot Mode + 增量)

### 3.1 输入来源

| 来源 | 现状 | 设计要点 |
|---|---|---|
| 用户消息(Owner) | ✅ `message.user` 入组,触发 Discussion(`hosted_room_discussion.py:187-192`) | 不动 |
| 群消息(其他 Bot) | ✅ `message.member` 入组,bot 之间的接力 | 不动 |
| @召唤 | ✅ `resolve_mentions` 决定谁来答(`hosted_room_discussion.py:291-307`) | 不动 |
| 定时任务(Routines) | ⚠️ cron 触发 Bot,Bot 自己决定要不要 message group | **设计缺口**:cron 触发后 Bot 可能想「提醒群里的人」,现有 message_agent 是 DM 不是 group;需要 `message_group(room_id, message)` |
| 子 Agent 完成 | ⚠️ 现有 `subagent.list/tail` 用于父子,group 维度不可见 | **设计缺口**:`agent.task_done` 事件入 room log,所有成员可见 |
| 进度事件 | ❌ 缺 | 见 §6 |

### 3.2 处理: 哪个 Agent 接收

- **`resolve_mentions` 已实现确定性决策**(`hosted_room_discussion.py:291-307`)。输入 frozen roster + user text,输出 `tuple[DiscussionMember, ...]`
- 状态机:`idle → (user.message | member.message) → task → (member 串行 turn) → settled | bounded`
- 3 轮上限、10 条上限、6 成员上限(`hosted_room_discussion.py:25-28`)— 不要放宽

### 3.3 输出: 每个 Agent 独立回复

✅ 现有做法正确 — 每个 member **自己的 AIAgent 跑自己的 turn**,在 room log 里发 `message.member`,**不是合并成一个 super-agent reply**。

老板的需求里隐含了一个坑:「Alice 在执行 git push」如果只显示在 Alice 的 Bot Chat,其他成员看不见 → 这就是 §6 进度事件的设计动机。

### 3.4 持久化:append-only SQLite

- `hosted_rooms.py:101-113` 已是 append-only(seq 严格递增、event_id 唯一、actor_json 不可改)
- **不要改成 mutable** — redaction 用新的 `event.redacted` kind(指向被 redact 的 event_id),保留审计
- 跨网关同步走 `hosted_room_replicas` + `groups.replicate`(已存在,`bot-mode.md:188-241`)
- 16MB/房 上限意味着**群聊不能太密**,或要加 GC(淘汰最早事件 + 留 summary)

---

## 4. @召唤实现

### 4.1 已落地的部分

- 解析:`@handle` 正则(`hosted_room_discussion.py:37`)
- 路由: `resolve_mentions` 决定 members(`hosted_room_discussion.py:291-307`)
- 触发 turn: `hosted_room_driver.py` 拿到 plan 后 spawn 每个 member 的 AIAgent
- 上下文注入: 每个 Bot 的 turn 启动时,room history 作为「user message」或 tool result 注入(`agent/AGENTS.md:23-30` 的规约)

### 4.2 设计要点(待验证)

- **被召唤的 Bot 是否看到完整 room log?** — 当前应该是看到一段最近的 history 作为 user message。要确认 cache boundary(`agent/AGENTS.md:23-26` 「the system prompt is byte-stable for the life of a conversation; the ONLY context mutation is compression」)。
- **@user(召唤 Owner)** — Bot 想让主人介入,目前是 `pending question` 显示在 needs-you badge(`bot-mode.md:101`),实现位置需核对。
- **3 轮上限内 @-mention 是否还能继续累?** — 当前是 frozen 上限(`MAX_DISCUSSION_ROUNDS=3`),如果第一轮 Bob @-mention 了 Carol,Carol 在第二轮回复,逻辑上 OK,但实现要确认。

### 4.3 不需要新增的设计

- 不需要新的 mention 协议(已有正则 + handle 字典)
- 不需要新的 turn 调度(RTC 已有 `hosted_room_driver`)
- **不要**新加「hot mention 立刻打断当前 turn」 — 这是逆 AGENTS.md「系统提示字节稳定」的(打补丁会破缓存),且与现有 `Bot-to-bot delivery is per-invocation`(`bot-mode.md:126`)「将来工作」一致 — 当前不实现是对的。

---

## 5. 任务分配

### 5.1 现状 vs 老板需求

| 老板需求 | 现状 |
|---|---|
| Agent 之间互相派活 | ✅ DM(`message_agent`) + ⚠️ 长任务(`peer run`) |
| 子任务状态回传给主 Agent | ⚠️ `subagent.list/tail` 用于父子,**`assign_task` 还没存在** |
| 主 Agent 改主意(中途纠偏) | ❌ `cancel` 协作中断,无「重新指派方向」 |
| 子 Agent 任务列表的可见性 | ⚠️ Kanban 是 task 列表,但 Bot Mode 没有 |

### 5.2 决策: **用 `delegate_task` 的 lifecycle 跨 Bot 用**

**具体设计**:
- 新工具 `assign_task(target_agent, goal, deadline?, deliverable_schema?, parent_room_id?)`
- 实现:`tools/assign_task.py`,内部走 `SubagentLaunchRequest`(`subagent_lifecycle.py:15-39`)+ `delegate_task` 的 role/timeout 体系
- 把 `target_agent` 从「本地 subagent profile」扩到「remote bot via message_agent + poll」或「same-gateway bot via delegate_task 直接走」
- **状态回传**:`agent.task_done/failed` 写入 host room(`§2.6` 新 event kinds),主 Agent 在下一轮 room 上下文里看到
- **deadline 实现**:timeout 借 `delegation.child_timeout_seconds`(`tools/AGENTS.md` 中段)

### 5.3 中途纠偏:steer-with-redirection

- 现有 `subagent.steer(session_id, subagent_id, text)` RPC(`tui_gateway/AGENTS.md` 中段)— **没用到 group 上下文**
- 设计:加 group 维度的 `groups.steer(room_id, member_id, subagent_id, text)` → 写入 `agent.steered` 事件 + 调用底层 `subagent.steer`
- **关键约束**:只能 steer **自己派的** subagent,不能 steer 别人派的(权限边界)
- **group 维度可见**:其他成员看到 `agent.steered` 事件,知道「Alice 在改主意」
- **何时用 steer vs cancel**:text 明确指出「改成 X」→ steer;text 是「停」→ cancel(底层已有,不动)

### 5.4 任务列表可见性: 借 Kanban 还是新做?

- Kanban 设计:`workspace` 隔离 + `ZELOO_KANBAN_BOARD` env(`cron/AGENTS.md`)
- 群聊里要不要 task 列表? → **轻量做**:每个 group room 自带一个 Kanban board,Bot 派的活自动写入(board id = `room:<room_id>`),所有成员可见。
- 已有: kanban 的 `kanban_create` / `kanban_assign` / `kanban_comment` 等工具(`cron/AGENTS.md` 列表)。
- 这就是「多 Agent 协作雏形」扩展到 group 的自然路径。

---

## 6. 持久记忆

### 6.1 现状盘点

- `agent/memory_provider.py`(ABC)+ `agent/memory_manager.py`(836 行)
- 钩子:`PRE_COMPRESS_CHECKPOINT_API_VERSION`(压缩前落盘,`memory_manager.py:20`)
- **跨 Agent 共享 vs 各自私有**:
  - 默认是「Bot profile 内私有」(每个 profile 自己的 memory store)
  - Honcho 集成(`website/docs/user-guide/features/honcho.md`)做跨用户/跨 Bot 共享
  - **没有「room 维度的共享记忆」** — 老板要的「Agent 共享事实」缺这一层

### 6.2 跨 Bot 共享 factsheet — **真正的新设计**

- **设计**:为每个 hosted_room 引入一个 **factsheet**(`gateway/hosted_room_factsheet.py`),key-value 存储
- **写入路径**:
  - 任何 Bot 可以在自己 turn 里写 `factsheet.set(key, value, source="<bot_id>")`
  - 每个 room 配一个 leader Bot(或 round-robin)周期把 room log 摘要 → 写 factsheet(类似 curator 的自动总结)
- **读取路径**:
  - 每个 Bot 启动 turn 时,prompt assembly 阶段注入当前 room factsheet(轻量摘要,避免 prompt cache 破)
  - **注入方式**:**append 到 system prompt 的固定 slot** — 「Room factsheet: { ... }」 这个 slot 的 hash 在 room lifetime 内是稳定的,内容变化时整块重写但 slot 位置不变 → 触发整段 system prompt 重 hash 但这是 room-level 而不是 turn-level,且 Bot 的 Bot Chat 已经在 system prompt 顶层有 messaging protocol 段(`bot-mode.md:118-123`),沿用同样模式
- **设计要点**:
  - factsheet 是 host room 的附属物,跟着 room 走,跟着 room 拆
  - 大小上限:32KB(够写几千 token 摘要)
  - 写权限:任何 Bot + Owner 可写,读权限:任何成员可读
  - **schema 不强求**,Bot 自己定义 key/value 结构

### 6.3 定时任务的记忆回填

- 现状: Bot Routines 触发 cron job,Bot 在 Bot Chat 里执行(`bot-mode.md:85`)
- **现状 OK,不动** — Routines 的执行结果自然落到 Bot 的 Bot Chat session,下次 Bot Chat 启动时 prompt assembly 会注入
- 待验证: cron session 的 `skip_memory=True`(`agent/AGENTS.md` 末尾、cron/AGENTS.md)意味着 Routines 触发时**不会自动写 memory store**。设计上有意为之:避免 cron 把 routine output 写进长期记忆污染。需要 Bot **显式调用** `memory` tool 才能写。

---

## 7. 进度状态共享

### 7.1 Agent 状态机(沿用现有 + 扩展)

```
idle → thinking → tool_call → (waiting_child?) → done | failed | cancelled
       ↑___________________________________|
       (tool result returns to thinking)
```

现有 turn 状态:`agent/conversation_loop.py:31-44`(`run_conversation`)的循环 — **每个 iteration 内部**的状态:
- `_pending_messages`(adapter 层)
- `_interrupt_requested`(break loop)
- iteration_budget.remaining(loop 终止条件)

**设计**: 把这些状态**广播到 room log**,变成可见事件。

### 7.2 状态广播机制

- **粒度**:每 200ms 节流一次,避免 spam
- **写事件**: `hosted_room_events.append_event(kind="agent.thinking"|"agent.tool_call"|...)` (`hosted_rooms.py` 已有 `append_event`)
- **读事件**: room log 已有 `groups.log` RPC(`methods_groups.py:18-22`),新增 `agent.*` kind 不需要新 RPC
- **owner 视角显示**:`<bot_name> 正在执行 git push(tool_call) · 12s`
- **owner 看到没看到的** Bot:显示「Alice last activity 2min ago」+ 最近一条 `agent.thinking` 内容

### 7.3 群聊里如何显示「Alice 在执行 git push」

- 行内显示:room 消息流的同一行
- UI 选项:
  - **minimal**: 「Alice · git push · 12s」一行,hover 展开
  - **detailed**: 一条 ephemeral 卡片,带 tool args 摘要 + 进度条 + 取消按钮
  - **TUI 选 minimal, Desktop 选 detailed**

### 7.4 跨设备统一视图

- 跨设备 Bot 的状态广播走 cross-connection relay(`bot-mode.md:142-148` 已描述的 Desktop relay)
- **关键点**:不要阻塞本地 turn 等待远端 ack;fire-and-forget,远端延迟显示就延迟显示
- Owner 看到 5 个 Bot 进度:本地直接读 ,走 SQLite,跨设备的由 Desktop relay 收齐

---

## 8. 安全机制

### 8.1 并发控制

- **跨 Bot 共享 workspace 的并发**: 新加 `tools/workspace_lock.py` — 类似 Kanban 的 board 隔离
  - lock 字段: `room_id`, `path`, `holder_agent_id`, `acquired_at`, `ttl`
  - 加锁 API:`acquire_workspace_lock(path, mode="exclusive"|"shared", ttl=300)`
  - 与 `approval_callback`(`agent-loop.md:144`)联动:危险命令先拿 lock 再审
- **隔离粒度**:
  - Bot profile 间隔离: 天然 OK(`~/.Zeloo/profiles/<bot>/` 不共享)
  - **同 room 多 Bot 协作**:lock 必要
  - **跨 room**:lock 也要,否则一个 Bot 被两个 room 同时叫,容易打架

### 8.2 权限边界

- **每个 Agent 的授权 scope**: 现成的就是 Bot profile 的 toolset 启停(`bot-mode.md:50`)
- **设计要点**:
  - group room 成员的默认 toolset = 该 Bot profile 的 toolset ∩ room 限定的最小集
  - 例:「审计 Bot」在群里被允许读文件但不允许 `Bash`
  - **实现**:`delegation.allowed_toolsets`(`tools/AGENTS.md`)从单个 subagent 扩到 room

### 8.3 用户手动介入(紧急 stop)

- ✅ 已存在: `groups.stop`(整体房间)、`peer stop`(单个 run)、`/stop`(Bot Chat 内)
- **UI**:Desktop 的「needs you」+ 每个 member 行尾的「Stop」按钮
- **明确边界**:`groups.stop` 不等于解散房间,房间历史保留,只是停止 turn 调度(`hosted_rooms.py:_EVENT_KIND_RE` 已包含 `room.stop_requested`)

### 8.4 敏感操作二次确认

- ✅ 已有: `approval_callback`(单 Bot 上下文)
- **设计**: 在 room 维度,「Alice 在 rm -rf」这件事,**只让 Owner 看到审批 UI**,其他 Bot 继续跑。这要求 `room.activity` 事件含 `kind=approval_required`(`hosted_rooms.py:60-64` 已有 `room.activity` 字段定义)。
- **不需要**:Bot 互相审批(让 AI 审批 AI 是 anti-pattern)
- **需要**:**审批 UI 必须 cross-transport 同步** — TUI 看到审批请求、Desktop 看到、CLI `/approvals` 看到(同一份 ground truth)

---

## 9. 主动撤回

### 9.1 Agent 输出撤回(已发消息编辑/删除)

- **append-only 设计保留**(重大,保留在 `hosted_rooms.py:101-113`),不物理删除
- 新增 `event.redacted` kind(`hosted_room_discussion.py` 的 `_TERMINAL_EVENT_KINDS` 模式扩展):
  ```python
  {
    "kind": "event.redacted",
    "actor": {"kind": "user", "id": "<owner_id>"},  # 或 system
    "payload": {
      "target_event_id": "<被撤回的消息 id>",
      "reason": "user-request | bot-misconduct | safety-policy",
    }
  }
  ```
- 渲染时:被 redact 的消息显示「[此消息已被撤回]」+ 鼠标 hover 显示 reason(仅 Owner 可见完整 reason)
- **权限**:
  - Owner 可 redact 任何人的消息
  - Bot 可 redact 自己的消息
  - Bot **不可** redact 别人的消息

### 9.2 子任务取消

- ✅ `SubagentLaunchRequest.cancel()`(协作中断,`subagent_lifecycle.py:38-44`)
- ✅ `groups.stop` room 整体停
- ✅ `peer stop <peer> <run_id>` 远端中断
- **设计要点**:cancel 是协作中断,不是「主 Agent 杀子进程」,子 Agent 在下一安全边界停下。如果子 Agent 在 terminal sandbox(像 Docker),cancel 后 sandbox 销毁 = 副作用部分自动撤销。

### 9.3 副作用 rollback

- **最难的**。 当前没有任何统一框架。
- **设计建议**(分阶段):
  1. **git 操作的 rollback**: `tools/git_rollback.py` — 记录每个 Bot 执行的 git 命令,提供 `rollback_last_n(agent_id, n)` 接口,reverse 操作:
     - `git commit` → `git reset --soft HEAD~1`
     - `git push` → 拒绝 rollback(已发出去),只回滚本地 commit
     - `git checkout -b` → `git branch -D`
     - `git merge` → `git reset --hard HEAD~1`(危险,需 approval)
  2. **terminal sandbox rollback**: Docker/singularity backend 已经在 sandbox 里跑,销毁容器 = 销毁副作用(`tools/environments/`)。local backend 没有 rollback,**设计上要警告用户**
  3. **文件 write rollback**: workspace_lock 设计里有 git 集成的话,`git checkout -- file` 就是 rollback。否则只能靠 Bot 自己的 undo 逻辑
- **统一接口**:`tools/undo.py` — 给定 agent_id + 时间窗口,枚举所有可撤销操作,UI 让 Owner 选

### 9.4 撤回的权限边界

| 操作 | Owner | Bot 自己 | 其他 Bot |
|---|---|---|---|
| 撤回自己发的消息 | ✅ | ✅ | ❌ |
| 撤回别人的消息 | ✅ | ❌ | ❌ |
| 取消子任务 | ✅(任何子任务) | ✅(自己派的) | ❌ |
| Rollback 副作用 | ✅ | ✅(自己的) | ❌ |
| 解散房间 | ✅ | ❌ | ❌ |

---

## 10. 风险评估

### 10.1 与 AGENTS.md 硬规矩的冲突点

| AGENTS.md 规约 | 风险 | 缓解 |
|---|---|---|
| Per-conversation prompt caching sacred | 群聊进度事件如果注入 system prompt → 缓存破 | 进度事件全部走 user message + tool result(`agent/AGENTS.md:23-30`) |
| Strict role alternation | 群消息拼接为 user message 时容易双 user | 复用现有 `cron` 镜像模式 — 「labelled user turns appended at a turn boundary」(cron/AGENTS.md) |
| System prompt byte-stable for life of conversation | Bot 进 group 后想读 factsheet,要不要每轮重读? | factsheet 内容变化 → 整段 system prompt 重写,但 slot 位置不变 → Bot Chat 启动时一次性注入,turn 内不动 |
| Core is narrow waist | 不要把群聊逻辑塞进 `run_agent.py` | Bot Mode 已经在 `gateway/`、`tui_gateway/`、`website/`,继续沿用 |
| Capability is property of session, not process env | group room 跨 profile,要 ZELOO_HOME override 在每个 member turn 都装上 | 验证 `hosted_room_driver` 在 spawn member turn 时是否包了 `_profile_runtime_scope()`(`multiplexing-gateway.md:48-58`) |
| Plugins don't touch core | group chat 后续会扩展,做 plugin 而不是改 core | Bot Mode 本身在 desktop plugin,继续这个模式 |
| Cache-aware default for state-mutating slash | skills install 等默认 deferred invalidation | 不直接相关,但 factsheet 这种「注入式」数据要确保 slot stable |

### 10.2 实施风险(单 PR 爆炸)

| 风险 | 影响 |
|---|---|
| hosted_rooms 表 schema 改动 = 数据迁移 | 加 `agent.*` event kinds 不需要 schema 改(现有 schema 已允许任意 kind);加 factsheet 表 = 新表,迁移成本低 |
| Cross-gateway 同步 = peer protocol 改 | 加新 event kinds 要走 `hosted_room_peer` PROTOCOL_VERSION bump + capability digest 重算(`hosted_room_discussion.py:213-216`) |
| progress event spam = 16MB gateway 上限打爆 | throttle 200ms,只发 start/done,中间不报 |
| workspace lock = 新领域 | 先做单 Bot 自我锁定,跨 Bot 锁 v2 |
| 副作用 rollback = 新框架 | 先 git,再 terminal sandbox,再 file write |

### 10.3 实施阶段拆分(避免单 PR 爆炸)

按依赖关系排:

1. **M0 — Audit & 文档化**(本周,不写代码)
   - 把 Bot Mode 已经有但文档里没说清楚的能力补齐到 `bot-mode.md`
   - 加一张「能力 ↔ 文件」映射表,让后续贡献者知道在哪改
   - **本设计报告就是 M0 的一部分**

2. **M1 — 结构化 progress events**(1-2 周)
   - 加 6 个 `agent.*` event kinds(`§2.6`)
   - hosted_room_driver 在每个 member turn 生命周期内 emit 事件
   - TUI 渲染最小版,Desktop 详细版
   - **数据迁移**:无(append-only 表自然扩展)
   - **跨网关**:本 PR 不动,事件本地可见

3. **M2 — 群上下文压缩 + factsheet**(2-3 周)
   - `gateway/hosted_room_factsheet.py` 新文件,新 SQLite 表
   - leader Bot(或 cron 周期)写 factsheet
   - Bot Chat 启动时注入 factsheet 摘要到 system prompt(沿 bot-mode protocol 模式)
   - **关键风险**: prompt cache 边界保护 — slot stable

4. **M3 — steer-with-redirection + assign_task**(3-4 周)
   - `tools/assign_task.py` 新文件,基于 `subagent_lifecycle` + `delegate_task`
   - `groups.steer` RPC + 底层 `subagent.steer` 调用
   - `agent.steered` / `agent.assigned_task` event kinds
   - **权限**: 只能 steer 自己派的

5. **M4 — workspace lock + 安全加固**(4-5 周)
   - `tools/workspace_lock.py`
   - 与 `approval_callback` 联动
   - room 维度的 toolset scoping(从 delegation.allowed_toolsets 扩)

6. **M5 — 主动撤回**(5-6 周)
   - `event.redacted` kind
   - 渲染「[此消息已被撤回]」
   - 跨 transport 同步(Desktop/TUI/CLI 一致视图)

7. **M6 — 副作用 rollback 框架**(6+ 周,可能跨季度)
   - `tools/undo.py` 统一接口
   - `tools/git_rollback.py` 先做
   - terminal sandbox rollback(已有基础,需接口化)
   - file write rollback(via git 集成)

---

## 11. 最小 MVP(M0 → M2)

**如果只能做 1 个 PR,做 M1(结构化 progress events)。**
理由:
- **复用最多**:append-only 表已存在,event kinds 是字符串,driver 已有 spawn 逻辑
- **老板感知最强**:「Alice 在执行 git push」可见 → 直接对得上需求 #5
- **不破坏现有**:不引入新表,不引入新 RPC,只是 emit 已有 RPC schema 的新 kind
- **缓存安全**:全是 user message / tool result 追加,不破缓存
- **测试容易**:driver 行为驱动,加 mock 即可

### 11.1 MVP 切分(具体可独立 ship 的子任务)

**M1.1 — Progress event types 定义(纯文档)**
- 在 `gateway/hosted_room_discussion.py` 的 `_GATEWAY_EVENT_FIELDS`(line 60-64)旁边加 `agent.*` 的字段定义
- 在 `website/docs/developer-guide/` 加 `hosted-room-progress-events.md`,列出 6 种 kind + payload schema
- **不写代码,只写文档与字段表**

**M1.2 — Driver emit agent.thinking/agent.done**
- `gateway/hosted_room_driver.py` 在 member turn start/end 调用 `append_event(kind="agent.thinking"/"agent.done", ...)`
- 测试: 启动一个 hosted_room,跑 1 轮,确认 `groups.log` 返回的事件包含 `agent.thinking`/`agent.done`
- **~100 行代码 + 测试**

**M1.3 — Driver emit agent.tool_call**
- `turn_tool_round`(`agent/turn_tool_round.py`)的 hook 点,driver 注册一个 listener
- throttle: 同一 tool_call 只发 start+done,不重复
- 测试: 多工具调用场景,确认 log 里每个工具一条 start + 一条 done
- **~150 行代码 + 测试**

**M1.4 — TUI 渲染**
- `tui_gateway/methods_groups.py::groups.log` 返回数据已包含 agent.* events,渲染层加判断
- `ui-tui/src/components/...` 加一个 `<BotProgress />` 组件
- **~200 行 TS + 测试**

**M1.5 — Desktop 渲染(详细版)**
- 同样的 log 渲染,Desktop 加展开/折叠、tool args 摘要、cancel 按钮
- **Desktop 端 ~300 行 TS**

### 11.2 后续(M2-M6)的依赖关系

```
M2 factsheet  ── 依赖 M1(已有 progress 事件做 leader 选择信号)
M3 steer       ── 不依赖 M2,但依赖 M1.2(turn 生命周期清晰)
M4 workspace   ── 不依赖 M2/M3,可并行
M5 redact      ── 不依赖 M2/M3/M4,可并行
M6 undo        ── 依赖 M4(workspace lock 知道操作历史才能撤销)
```

并行策略:
- M1 串行(本季度)
- M2 / M3 / M4 / M5 可并行启动(2 个组 2 季度消化)
- M6 单独放最后

### 11.3 不做**放进 MVP 的话

- ❌ 任何新 SQLite 表(留到 M2 factsheet)
- ❌ 任何新 RPC(`subagent.steer` / `groups.steer` 留到 M3)
- ❌ 任何对 `delegate_task` 的改动(留到 M3)
- ❌ 任何对 `AIAgent` facade 的改动(留到 M5 或更后)
- ❌ schema 迁移(append-only 表自然扩)

---

## 12. 待验证 / 开放问题

### 12.1 必须验证(继续探索后才能定)

| 问题 | 在哪验证 | 为什么重要 |
|---|---|---|
| `hosted_room_driver` 是否在每个 member turn 包了 `_profile_runtime_scope`? | `gateway/hosted_room_driver.py` | 不包的话,默认 profile 的 credentials 会泄漏到其他 Bot 的 turn |
| `progress event` 注入方式是否破 prompt cache? | 看 `hosted_room_driver` 怎么组装 prompt | 直接决定 MVP 能不能做 |
| cross-gateway 同步时,新增 `agent.*` kinds 要不要 bump PROTOCOL_VERSION? | `gateway/hosted_room_peer.py` | 影响能否跨网关 deploy |
| factsheet 注入 system prompt 时 slot 是否 stable? | `agent/prompt_builder.py` 配合 `agent.bot_mode_protocol` | slot 不稳定 → 缓存破 |
| `room.activity` 事件里的 `status/reason_code` 字段是否覆盖 approval 通知? | `hosted_room_discussion.py:60-64` + 渲染层 | 直接决定审批 UI 是否真的工作 |
| `groups.capabilities`(`methods_groups.py:18`)是不是已经声明了 `progress_events: true`? | `tui_gateway/methods_groups.py` | 没有的话要加 capability digest |

### 12.2 开放问题(待讨论决定)

1. **progress 事件要不要 throttling? 200ms 还是 500ms?** — 太短 spam,太长卡顿。建议 200ms,带「同一 tool_call 不重复」去重。
2. **Bot Routines 触发的群消息应该走哪个 RPC?** — 当前没有,需要 `message_group(room_id, message)` 还是扩展 message_agent 加 `target="group:<room_id>"`?
3. **factsheet schema 要不要强约束?** — 完全 free-form 让 Bot 自己写,vs 固定 schema(decision / fact / context)?倾向 free-form + 文档规范。
4. **跨网关 progress 事件的延迟?** — 跨设备 relay 是 best-effort,要明示 UI「showing ~5s delayed」。
5. **workspace lock 跟 git 集成怎么挂钩?** — 拿 lock 时检查 git branch?避免两个 Bot 在不同 branch 上「改同一个文件」。
6. **副作用 rollback 是 opt-in 还是 default?** — opt-in 更安全但用户体验差;default 更流畅但风险大。建议 **owner profile 全局开关**,默认 opt-in。
7. **Bot Routines 的 message_group 是否要审批?** — Routines 静默执行是当前默认;群消息让其他 Bot 看到是否要经过 approval?建议不审批(Routines 是 Owner 配的)。

### 12.3 设计上的「取舍」 — 记录给后人

- **不写新 facade 的代价**: 每次新增 group chat 能力都要顺着 Bot Mode 现有的模块加。好处是简单,代价是命名会乱(Mode/Room/Group/Discussion 混着用)。
- **append-only + redact 的代价**: redact 必须读 event_id,不能按 seq 索引(用户可能删中间一条)。当前 SQLite schema `PRIMARY KEY (room_id, seq)` 加 `UNIQUE (room_id, event_id)`(`hosted_rooms.py:111`)已经够用。
- **不强制 schema 的代价**: factsheet free-form 让 Bot 写什么都有,长期会变垃圾场。需要 cron 周期清理过期 key(`cron/AGENTS.md` 已有 GC 模式)。

---

## 13. 参考文件索引

### 13.1 必读(已读)

| 文件 | 行数 | 关键章节 |
|---|---|---|
| `AGENTS.md` | 路由表 + 硬规矩 | 1-2, 17-26 |
| `agent/AGENTS.md` | AIAgent + 缓存硬规矩 | 22-50 |
| `gateway/AGENTS.md` | Gateway + adapters | 1-30 |
| `cron/AGENTS.md` | Cron + Kanban | 全文 |
| `zeloo_cli/AGENTS.md` | CLI + profiles | 全文 |
| `tools/AGENTS.md` | 工具 + delegate_task | 100-110 |
| `website/docs/developer-guide/agent-loop.md` | AIAgent turn 循环 | 60-79 |
| `website/docs/developer-guide/prompt-assembly.md` | prompt 构建 + 缓存 | — |
| `website/docs/developer-guide/context-compression-and-caching.md` | 压缩是缓存唯一合法破坏点 | — |
| `website/docs/developer-guide/cron-internals.md` | Cron 内部 | 全文 |
| `gateway/hosted_rooms.py` | Room 持久化 | 1-150 |
| `gateway/hosted_room_discussion.py` | 群聊策略(@召唤、轮次) | 全文 |
| `gateway/hosted_room_driver.py` | Turn 调度 | — |
| `tui_gateway/methods_groups.py` | Room RPC 接口 | 18-23 |
| `website/docs/user-guide/bot-mode.md` | Bot Mode 用户文档 | 全文(281 行) |
| `website/docs/design/multiplexing-gateway.md` | 多 profile 隔离 | 全文 |

### 13.2 设计引用(报告里指向的位置)

- `gateway/hosted_rooms.py:39-44` — events budget 上限
- `gateway/hosted_rooms.py:87-148` — SQLite schema
- `gateway/hosted_rooms.py:101-113` — append-only 约束
- `gateway/hosted_rooms.py:49-57` — actor/kind 分类
- `gateway/hosted_room_discussion.py:25-28` — 6 成员/3 轮/10 条上限
- `gateway/hosted_room_discussion.py:37` — @-mention 正则
- `gateway/hosted_room_discussion.py:60-64` — gateway-author event 字段定义
- `gateway/hosted_room_discussion.py:291-307` — resolve_mentions 函数
- `tui_gateway/methods_groups.py:18-22` — Room RPC 方法名列表
- `tools/AGENTS.md` (delegate_task 段) — 派活的 role/timeout/orchestrator
- `agent/AGENTS.md:23-30` — system prompt cache 规约
- `agent/memory_manager.py:20` — pre-compress checkpoint API version

---

## 14. 结论

**一句话总结**: 老板提的 10 项群聊需求里,**8 项 Bot Mode 已落地,2 项真的需要新设计工作**。不要从头写 — 把现有架构摸透(M0),先 ship 结构化 progress events(M1,本季度),然后 factsheet + steer(M2/M3)。

**最值得做的第一件事**: 把这份报告的 §1(现有能力盘点)+ §11(MVP 切分)单独抽出来,跟老板过一遍,确认 M1.1(纯文档 + event kinds 定义)是大家共识的「下一件事」。再开始写 M1.2。