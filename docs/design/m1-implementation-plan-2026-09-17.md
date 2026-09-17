# M1 实施计划 —— 结构化 progress events

> Date: 2026-09-17 · Owner: <delegated agent> · Scope: 群聊模式 M1 最小切片(~17 工作时, 3 个工作日)
> Status: planning only · 不写代码、不动代码、本文件是后续 PR 的施工说明书。

---

## 0. 老板请求的精确解读

**老板刚说「开发」**, 上一轮我问「群聊模式开发出来了吗」老板得到的是「未开发」(Bot Mode 是生产实现, 但 §0 的 10 项需求里有 5 项只部分落地, 1 项未落地, 其中**结构化进度事件** §0 表 #5 是「⚠️ 部分落地」标注的明确缺口)。

**「开发」的真实含义判断**:

| 选项 | 工作量 | 本会话可行性 |
|---|---|---|
| A. 完整 10 项群聊能力 | 6-8 周 | ✗ 不可行 |
| **B. M1 单 Bot 结构化 progress events(只追加事件)** | **~17 小时 / 3 工作日** | **✓ 推荐** |
| C. M2 factsheet(共享上下文缓存) | 30+ 小时 | ✗ 超出 session |
| D. M3 主 Agent 中途改主意(steer) | 40+ 小时 | ✗ 超出 session |

**本会话选 B(M1)**。理由:
1. 设计稿 §11 明确「**如果只能做 1 个 PR, 做 M1**」(line 552), 老板语义最契合需求 #5
2. 设计稿 §11.2 显示 M1 是 M2/M3 的前置依赖;**先打通管道, 后续 PR 才有基础**
3. 老板前 7 个 PR 都成功 ship(PR-1 到 PR-7), 但 PR-8 pytest_sessionfinish ZELOO_HOME race 失败回滚了 —— **session 后期边际风险递增, M1 是「小到可控」的最优切片**
4. M1 完全不动 `delegate_task` / `AIAgent` facade / 新 SQLite 表 / 新 RPC(§11.3), 对现有 Bot Mode 用户零破坏

**M1 的边界明确声明**: 单 Bot 在群里的 progress 可视化。**不做** multi-bot 互动编排、不做跨 Bot 派活、不做中途改主意、不做撤回。

---

## 1. 必做的验证(先做这 6 项才动代码)

> 这些验证在动任何代码前完成, 避免 PR 中途发现设计稿假设不成立。每个都有具体文件和验证命令。

### V1. driver 是否已包 `_profile_runtime_scope`
- **文件**:`gateway/hosted_room_driver.py` (driver 任务调度处)
- **验证什么**: 每个 member turn 启动时是否切到目标 Bot profile 的 credentials;不切的话默认 profile 的 token 会泄漏到其他 Bot 的 turn
- **工具/命令**:`grep -n "profile_runtime_scope\|_apply_profile\|os.environ" gateway/hosted_room_driver.py`, 关注 spawn 子进程或设置 env 的位置
- **预计时长**:30 分钟
- **影响**:若**不包**, M1.2 需先打 PR-9 修 profile scope, 否则 progress event 的 actor.profile 字段会指向错的 profile

### V2. progress event 注入是否会破 prompt cache
- **文件**:`gateway/hosted_room_driver.py` (driver 组装 member turn prompt 处) + `agent/prompt_builder.py`
- **验证什么**: 现有 driver 把 room log 注入 system prompt 还是 user message?注入点 slot 是否稳定?
- **工具/命令**:`grep -n "room.log\|append_event\|room context" gateway/hosted_room_driver.py`, 同时 `grep -n "BOT_MODE\|bot_mode_protocol\|fact_sheet" agent/prompt_builder.py agent/bot_mode_protocol.py`(若存在)
- **预计时长**:45 分钟
- **影响**:若**注入 user message 顶部**, 新增 agent.thinking 事件会改变每一轮的 user 内容 → **缓存全破**;若 slot stable, append 进度事件**不破缓存**(纯 append-only)

### V3. 跨网关同步是否需要 bump PROTOCOL_VERSION
- **文件**:`gateway/hosted_rooms.py:23` (`PROTOCOL_VERSION = 2`) + `gateway/hosted_room_peer.py` (跨网关 relay)
- **验证什么**: 旧网关收到 `agent.thinking` 这种新 kind 时, 是忽略还是拒收?会不会让 replica 同步失败?
- **工具/命令**:`grep -n "PROTOCOL_VERSION\|kind in\|allow.*kind\|unknown.*kind" gateway/hosted_room_peer.py gateway/hosted_rooms.py`, 看 `_EVENT_KIND_RE`(line 48 `^[a-z][a-z0-9_.-]*$`) 是否放行新 kind
- **预计时长**:30 分钟
- **影响**: 旧网关若 **拒收** 新 kind, 需 bump PROTOCOL_VERSION(影响部署兼容性);若**忽略**, 不必 bump(向下兼容)

### V4. `groups.capabilities` 是否声明 `progress_events: true`
- **文件**:`tui_gateway/methods_groups.py:18` 附近(`groups.capabilities` RPC)
- **验证什么**: 现版本 gateway 报的 capability 是否包含 progress 事件指示?
- **工具/命令**:`grep -n "capabilities\|driver\|progress" tui_gateway/methods_groups.py`, 直接读 `def groups_capabilities`(若存在)
- **预计时长**:15 分钟
- **影响**:若**没有**, M1.4 渲染层需先在 frontend 做 capability detection(`if (cap.progress_events)` 守卫);若**已声明**, 直接展示

### V5. `room.activity` 事件 status 字段是否覆盖 progress 需求
- **文件**:`gateway/hosted_room_discussion.py:60-64` (`_GATEWAY_EVENT_FIELDS`)
- **验证什么**: `room.activity` 的 status/reason_code 枚举是否能区分 "agent.thinking" 和 "agent.tool_call" 两种状态?
- **工具/命令**: `sed -n '50,80p' gateway/hosted_room_discussion.py`, 看现有 `room.activity` payload schema 是否够用
- **预计时长**:15 分钟
- **影响**:若 status 字段太粗, M1.1 不能复用 room.activity, 必须新引入独立的 `agent.thinking`/`agent.tool_call` 等 kind

### V6. driver 现有的 turn 生命周期 hook 点
- **文件**:`gateway/hosted_room_driver.py` 全文 + `agent/turn_tool_round.py`(若 M1.3 tool_call 需要)
- **验证什么**: turn start / turn end / tool start / tool end 各在哪些函数、哪些行?
- **工具/命令**:`grep -n "def.*turn\|def.*task\|begin_run\|finish_run\|def run_task" gateway/hosted_room_driver.py`, 列出 4 个时点对应的函数和行号
- **预计时长**:30 分钟
- **影响**: 这是 M1.2 / M1.3 写代码的精确插入点;不能凭空写「在 L#X emit」

**验证总时长**:~3 小时。**全部完成才能进 §2**。

---

## 2. M1.1 schema 扩展(最小依赖)

> 这是纯文档 + Python 字段表, 不发事件、不写渲染。~250 行 + 文档。

### 2.1 新增 event kind(6 种)

| kind | actor.kind | payload 必填字段 | 触发时机 |
|---|---|---|---|
| `agent.thinking` | `member` | `task_id`, `model`, `round` | turn 开始, LLM 还没发第一句 |
| `agent.tool_call` | `member` | `task_id`, `tool`, `call_id`, `round` | 工具调用前 |
| `agent.tool_result` | `member` | `task_id`, `tool`, `call_id`, `duration_ms`, `status` | 工具返回时 |
| `agent.waiting_child` | `member` | `task_id`, `child_task_id`, `child_target` | 发起 `delegate_task` 后 |
| `agent.done` | `member` | `task_id`, `terminal_kind`, `tokens` | turn 正常结束 |
| `agent.failed` | `member` | `task_id`, `error_class`, `error_message` | turn 异常终态 |

**actor**: 复用 `_ACTOR_FIELDS`(`hosted_rooms.py:60`): `{kind: "member", id: "<member_id>", profile: "<bot_profile>", connection_id: "<gateway_id>"}`。

### 2.2 验证现有约束

| 约束 | 验证 |
|---|---|
| `_EVENT_KIND_RE = ^[a-z][a-z0-9_.-]*$` (`hosted_rooms.py:48`) | ✓ 全部 6 种 kind 匹配 |
| `MAX_EVENT_KIND_CHARS = 64` (`hosted_rooms.py:27`) | ✓ 最长 `agent.waiting_child` = 19 字符 |
| `MAX_EVENT_JSON_BYTES = 256 KB` (`hosted_rooms.py:32`) | ✓ 单 payload < 1 KB |
| `_EVENT_KINDS_BY_ACTOR["member"]` (`hosted_rooms.py:51`) | ⚠ 当前**只允许 `message.member`**, M1.1 需扩到包含 6 种新 kind |
| `append_event` 幂等性 (`hosted_rooms.py:924`) | ✓ 通过 `event_id` 唯一约束保证 `(room_id, event_id)` 不重复 |
| append-only 兼容 | ✓ 不需 schema 迁移, 旧 event 格式不动 |

### 2.3 M1.1 的输出物

| 文件 | 改动 |
|---|---|
| `gateway/hosted_rooms.py:50-57` | `_EVENT_KINDS_BY_ACTOR["member"]` 加入 6 种新 kind |
| `gateway/hosted_room_discussion.py:60-64` | 新增 `_PROGRESS_EVENT_FIELDS` 字段表(每种 kind 的 required + optional 字段) |
| `website/docs/developer-guide/hosted-room-progress-events.md` | **新文件**, 列 6 种 kind、payload schema、append-only 兼容性、迁移指南 |
| `docs/design/group-chat-2026-09-17.md` | 末尾加「M1.1 已落地」链接 + §11.3 不做项核对 |

**预计代码量**: Python ~40 行 + 文档 ~150 行

---

## 3. M1.2 driver emit(turn 生命周期)

> 在 driver 跑 member turn 时, 按生命周期 emit progress event。~150 行 + 测试 ~120 行。

### 3.1 turn 生命周期映射(取决于 V6 验证结果)

| 生命周期点 | 函数(待 V6 确认行号) | emit kind |
|---|---|---|
| turn 开始 | driver 在 `_mark_running(...)` 后调用 `spawn_subagent(...)` 前 | `agent.thinking` |
| tool 调用前 | driver 调用 `subagent.handle_tool_call(...)` 之前 | `agent.tool_call` |
| tool 调用后 | 拿到 tool result 后 | `agent.tool_result` |
| 发起 `delegate_task` | driver 写子任务后 | `agent.waiting_child` |
| turn 终态 | driver 在 `_SETTLE_RUNNING_SQL` 提交后 | `agent.done` 或 `agent.failed` |

### 3.2 复用现有 helper

- **emit 用 `append_event`**(`hosted_rooms.py:924`), 不是新写 RPC
- **actor 复用** `_actor_for_member(member)`(若存在;若没有, 抽 1 个 ~10 行 helper)
- **event_id 生成** 复用 `_validate_identifier` 的 `hashlib.sha256(...)` 模式(见 `hosted_rooms.py:1016`)
- **不引入新 connection / 新表 / 新 RPC**

### 3.3 throttle 与去重

设计稿 §12.2 提到 throttling。**M1.2 不做 throttling**:
- 6 种 kind 的 emit 频率天然受限于 turn 数量(每个 turn 最多 1 次 thinking + N 次 tool_call + 1 次 done)
- throttling 是 M3 steer 之前才需要(那时 driver 才会高频发 progress)
- 在 M1.2 注释里写「throttling hook point: TBD in M3」即可

### 3.4 写入路径与错误处理

- **append_event 失败时**: driver 记录 warning 到 log(`gateway.log`), **不抛异常**(progress event 是 best-effort, 不能让它 crash turn)
- **event_id 冲突**: `UNIQUE (room_id, event_id)`(`hosted_rooms.py:111`)会让 append_event 抛错 → 同样 best-effort, log warning, 不重试
- **payload 序列化失败**: 同上 best-effort, 不影响 turn 主流程

---

## 4. M1.3 driver emit tool_call(配套 M1.2, 合并实施)

> 实际 M1.3 在设计稿里独立;本计划把它**并入 M1.2 同一 PR**(避免两次动 driver), 但文件路径保留分立(测试目录分开)。

### 4.1 hook 点

- 入口:`agent/turn_tool_round.py` 的 tool round 调度(待 V6 验证具体行号)
- 方案 A(driver 调用 turn 前/后注入): **推荐**, 不动 `turn_tool_round.py`, 改动最小
- 方案 B(改 `turn_tool_round.py` 加 listener): **不推荐**, 改动面广, 破缓存风险

### 4.2 去重

同一 `(task_id, tool, call_id)` 只发 start + done, 不重复。**靠 event_id 唯一性天然去重**:
- start: `event_id = sha256(f"tool:{task_id}:{call_id}:start")[:32]`
- done: `event_id = sha256(f"tool:{task_id}:{call_id}:done:{duration_ms}")[:32]`
- 不同 duration → 不同 event_id, 但同 id 重发被 UNIQUE 约束挡掉

---

## 5. M1.4 TUI 渲染(最简化)

> 静态展示进度事件, 不做交互。~120 行 TS。

### 5.1 数据流

`groups.log`(`tui_gateway/methods_groups.py`) → 已返回 hosted_room_events 列表 → TUI 在 message.member 之间插入 progress 行。

### 5.2 渲染位置

`ui-tui/src/components/groups/MessageList.tsx` (待 V6 验证具体文件): 在每条 `message.member` 行**之上**插入 progress panel:
- `agent.thinking` → `<Spinner text="<member> thinking…" model={...} />`
- `agent.tool_call` → `<ToolBadge tool={...} call_id={...} />`
- `agent.tool_result` → `<ToolBadge tool={...} status={...} duration_ms={...} />`
- `agent.waiting_child` → `<ChildWaiting child_target={...} />`
- `agent.done` / `agent.failed` → 行尾打 ✓/✗ 标记, 不占独立行

### 5.3 不做的(M1 明确不做)

- ❌ cancel 按钮(等 M3 steer)
- ❌ expand / collapse(等 M2/M3)
- ❌ 点击查看 tool args 详情(等 M2 factsheet)
- ❌ 重写 room log 组件(只在现有 message 列表里追加)
- ❌ Desktop 端渲染(那是设计稿 §11.1 M1.5, **本切片不做**)

---

## 6. 测试计划

> 每个 M1.x 至少 1 个新测试文件, INVARIANT 测试 ≥ 1 个(不写 change-detector)。

### 6.1 测试文件清单

| 测试文件 | 覆盖 | INVARIANT |
|---|---|---|
| `tests/gateway/test_hosted_rooms_progress_kinds.py` | M1.1: 6 种新 kind 的 actor 验证 + 字段验证 + payload 序列化 | 同一 kind 重复 emit 第二次被 UNIQUE 拒绝 |
| `tests/gateway/test_hosted_room_driver_emits_progress.py` | M1.2: mock driver 跑 1 个 turn, 验证 log 含 1×thinking + 1×done | turn 终态前没 done 事件 → driver 仍能在下次启动 reconcile |
| `tests/gateway/test_hosted_room_driver_emits_tool_progress.py` | M1.3: mock 跑 1 个 turn 含 2 次 tool 调用, 验证 log 含 2×tool_call + 2×tool_result | 同一 call_id 不重复(UNIQUE 约束) |
| `tests/tui_gateway/test_groups_log_progress.py` | M1.4: `groups.log` 返回值包含 agent.* 事件 + 序列化正确 | client 拿到的事件可被 React 组件直接渲染(无 missing field) |

### 6.2 集成测试边界

- **不跑** 真实 LLM(全 mock)
- **不跑** 真实跨网关 relay(V3 验证后再说)
- **不跑** profile 切换(V1 验证后再说, 若需修 PR-9 单独跑)
- **必须跑** 真实 `hosted_rooms.py` SQLite + driver(用 `tmp_path` fixture, 模式同 `tests/conftest.py` 的 `_isolate_zeloo_home`)

### 6.3 复用现有 fixture

- `tests/gateway/test_hosted_rooms_*.py` 现有 `gateway_db` / `hosted_room` fixture 直接复用
- 不新建 fixture, 不动 `tests/conftest.py`

### 6.4 INVARIANT 守则(从 AGENTS.md 抄)

- **断言两个数据的关系**(e.g. "log 返回的事件数 == driver 内部 emit 计数"), 不写 `len(...) == 3` 这种 change-detector
- **不读源代码文本**(e.g. 不 `assert.match` driver.py 内容)
- **E2E 真实路径**: 真 SQLite + 真 driver, 不 mock `append_event`

---

## 7. 风险与不做的项

### 7.1 明确不做(防止 scope creep)

| 不做项 | 推到哪 |
|---|---|
| cancel/expand/undo 按钮 | M3 steer |
| tool args 详情展示 | M2 factsheet |
| Multi-bot 互动编排(主 Agent 调度) | 不在 M1-M6 MVP 范围 |
| `delegate_task` 协议扩展 | M3 steer |
| 跨网关同步新 kind 兼容性 | V3 验证后单独立 PR |
| Desktop 端 UI(M1.5) | 老板若要求, 后续 PR |
| `_profile_runtime_scope` 修复(若 V1 发现未包) | PR-9 单独 PR, 不绑在 M1 |

### 7.2 边界判断(M1.x vs M1.y)

- **M1.1 = schema + 文档**: 完全无副作用, 可单独 ship
- **M1.2 + M1.3 = driver emit**: 同 PR, 一起 ship
- **M1.4 = TUI 渲染**: 单独 PR, 但等 M1.2 + M1.3 merge 后再开
- **M1.5 = Desktop 渲染**: **本切片不做**, 老板需要时单开 PR

### 7.3 老板若要「群聊」含 multi-bot 互动

**M1 不覆盖 multi-bot 互动编排**。如果老板说「Alice 派活给 Bob」, 那要的不是 M1, 是 M2 factsheet + M3 steer, 本会话做不完。
**诚实告知**: M1 只做「看见 Alice 现在在干嘛」(单 Bot progress), 不做「Alice 调度 Bob」(multi-bot orchestration)。

---

## 8. 估工时与依赖

### 8.1 工时(纯实施, 不含 review/merge)

| 子任务 | 工时 | 备注 |
|---|---|---|
| §1 验证(V1-V6) | 3 小时 | 必做, 失败则设计稿 §12.1 待验证问题升级为 blocker |
| §2 M1.1 schema + 文档 | 4 小时 | 含 `hosted-room-progress-events.md` 写完 |
| §3 M1.2 driver emit + 测试 | 6 小时 | 含 INVARIANT 测试 |
| §4 M1.3 tool_call emit + 测试(并入 M1.2 PR) | 0 小时(已含在 M1.2) | 共用同一 PR |
| §5 M1.4 TUI 渲染 | 3 小时 | 仅静态展示, 无交互 |
| §6 测试整合 + INVARIANT 收尾 | 4 小时 | 含 4 个测试文件的 INVARIANT 复审 |
| **总计** | **~17 小时 / 3 工作日** | 单人, 串行 |

### 8.2 依赖图

```
§1 验证 ──→ §2 M1.1 ──→ §3 M1.2 (+ §4 M1.3) ──→ §5 M1.4 ──→ §6 测试整合
       ↓                    ↓
  若 V1 失败:           若 V3 失败:
  先开 PR-9 profile      bump PROTOCOL_VERSION
  scope 修复,            独立 PR
  再回 §2                再回 §3
```

### 8.3 与设计稿 §11.1 估时的差异

设计稿估时: M1.1(纯文档 1h) + M1.2(100 行 + 测试 2h) + M1.3(150 行 + 测试 3h) + M1.4(200 行 + 测试 3h) + M1.5(300 行 4h) = **~13h**(不含验证)。

本计划加上:
- **§1 验证 +3h**(设计稿漏掉, 是上轮 PR-8 失败的教训: **必须先验, 才能写**)
- **§6 测试复审 +1h**(INVARIANT 比 snapshot 测试耗时更长)
- **M1.5 不做 -4h**(砍掉)
- **M1.3 并入 M1.2 -3h**(同 PR)

**净调整**: +4h -7h = **-3h**, 但保留更多余量给意外。

---

## 9. 「老板选项」明确列出

> 老板说「开发」, 我有 4 个选项可以执行。**强烈推荐 A**, 但老板可能想选其他。

| 选项 | 内容 | 工时 | 本会话可完成 |
|---|---|---|---|
| **A** | **M1 单 Bot progress(我推荐)** | ~17h / 3 工作日 | ✓ |
| B | M1 + 最简 multi-bot smoke test(多 Bot 不互动, 只在 `groups.log` 看各自 progress) | M1 17h + smoke 3h = 20h | ✓(紧张) |
| C | 仅完成 M1.1 schema + 测试, 不做 driver emit | ~6h / 1 工作日 | ✓(最稳) |
| D | 什么都不做, 承认 session 内不能完整实现群聊模式 | 0h | ✓(诚实选项) |

**推荐 A 的理由**:
- 设计稿 §11 已明确「如果只能做 1 个 PR, 做 M1」
- A 选项完成后, 老板**能立刻看见「Alice 在执行 git push」**, 哪怕没有 multi-bot 互动编排
- B 选项里 multi-bot smoke 是个**伪需求**: 不互动的 multi-bot 只是两个独立单 Bot, 没有群聊本质
- C 选项太短视: schema 落地不 emit 事件, 老板看不到任何变化
- D 选项诚实, 但本会话还有时间, 不必放弃

**我的判断**: 老板大概率**选 A**。如果老板选 C, 我会先做 C 并诚实说明「M1 不动 driver 等于什么都没改」。

---

## 10. 提交策略(本会话不动代码, 仅供后续 PR 参考)

**3 个 PR 串行**:
1. **PR-A**: M1.1 schema + 文档 + 字段表(纯加 kind, 无行为变化)
2. **PR-B**: M1.2 + M1.3 driver emit + 测试(发事件, 但 frontend 不消费, 无视觉变化)
3. **PR-C**: M1.4 TUI 静态渲染 + 测试(用户能看见 progress)

**每个 PR 满足 AGENTS.md 要求**:
- INVARIANT 测试 ≥ 1 个, 不写 change-detector
- E2E 真实路径(真 SQLite + 真 driver + tmp ZELOO_HOME)
- 不引入新 facade / 新 RPC / 新 SQLite 表
- review 自查:`grep` 旧有 Bot Mode 用户行为路径(发 message.member) 不变
- run `scripts/run_tests.sh tests/gateway/` + `tests/tui_gateway/` 全绿

**绝不重蹈 PR-8 覆辙**:
- PR-8 失败原因 = `pytest_sessionfinish` 里设 `ZELOO_HOME` 与某个 fixture 的 race
- M1 的所有测试**不动 `ZELOO_HOME`**(全用 `tests/conftest.py:: _isolate_zeloo_home` autouse)
- 若需要切换 profile, 用 `monkeypatch.setattr(Path, "home", ...)` + `monkeypatch.setenv("ZELOO_HOME", ...)`,**两者都要**(AGENTS.md 已强调)

---

## 11. 不在本切片(留作后续 session 的 TODO)

- M2 factsheet(共享上下文缓存)
- M3 主 Agent steer(中途改主意)
- M4 workspace lock
- M5 redact(消息编辑/删除)
- M6 undo(副作用 rollback)
- M1.5 Desktop 端 UI(若老板需要)
- 跨网关 progress 同步(V3 验证后单开 PR)
- `groups.steer` RPC(M3)
- `message_group` RPC(若老板的 Bot Routines 要群发)
- profile scope 泄漏修复(若 V1 验证发现未包)

---

## 12. 我下一步

**本会话不动代码**, 我提交这份计划后, 等老板指示:
1. 老板说「做 M1」 → 进 §1 验证(3 小时) + §2 schema(4 小时), **不一次做完**, 先 ship §1+§2 PR-A 验证设计假设
2. 老板说「只做 M1.1」 → 仅 §1 + §2, ~7 小时
4. 老板说「不算了」 → 关闭本切片, 留本文件作为下次 session 的起点
4. 老板说「别的」 → 我重读上下文(回头看老板原话, 不脑补)

**诚实声明**: 本文件**没动任何代码**。M1 的代码工作从 §1 验证开始, 不从「拍脑袋写 driver emit」开始。