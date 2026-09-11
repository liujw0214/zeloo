# 55. TUI 渲染 — textual 终端 UI

## 55.1 概述

`zeloo_tui/` 是 Zeloo Agent 的 **终端 UI 前端**，基于 [Textual](https://github.com/Textualize/textual) 构建。它是审计 [§54](./54-frontend-audit.md) 中 Web/TUI 渲染层 0% 的回填实现。

**关键设计决策**：TUI 本身**不**运行任何 LLM 调用——它是 `tui_gateway` 事件流的**纯消费者**。Agent 循环仍由 `agent.conversation_loop.py` 驱动，TUI 只渲染 AgentEvent / 账单 / 配置变更 / 计算节点状态四个数据源。

## 55.2 架构

```
                       tui_gateway
   ┌─────────────────────────────────────────────┐
   │  CallbackRegistry     BillingView            │
   │  (start/think/tool/   (cost summary)        │
   │   finish/error)                              │
   │                     ChangeWatcher            │
   │  HostInfo registry   (config / skill changes)│
   └────────┬────────────────────────┬────────────┘
            │ events                  │ snapshots
            ▼                        ▼
   ┌─────────────────────────────────────────────┐
   │            zeloo_tui.bridge                  │
   │  (TUIBridge: buffers events, replays on attach │
   │   routes through call_from_thread)            │
   └──────────────────┬───────────────────────────┘
                      ▼
   ┌─────────────────────────────────────────────┐
   │           ZelooTUIApp (textual.App)          │
   │  ┌─────────────────┬─────────────────────┐   │
   │  │ EventLog (left)  │ BillingPanel       │   │
   │  │  (RichLog)       │  (Static)          │   │
   │  │                  ├─────────────────────┤   │
   │  │                  │ HostPanel (DataTable)│   │
   │  │                  ├─────────────────────┤   │
   │  │                  │ ChangePanel (DataTable)│ │
   │  └─────────────────┴─────────────────────┘   │
   └─────────────────────────────────────────────┘
```

## 55.3 模块布局

| 文件 | 行数 | 职责 |
|------|------|------|
| `zeloo_tui/__init__.py` | 35 | `is_textual_available()` / `launch()` |
| `zeloo_tui/bridge.py` | 235 | `TUIBridge` + 4 个 `format_*` 纯函数 |
| `zeloo_tui/app.py` | 175 | `ZelooTUIApp` (ComposeResult / on_mount / 绑定) |
| `zeloo_tui/cli.py` | 100 | `zeloo-tui` 入口 + demo emitter |
| `zeloo_tui/widgets/event_log.py` | 35 | `EventLog` (RichLog 包装) |
| `zeloo_tui/widgets/status_panels.py` | 130 | `BillingPanel` / `HostPanel` / `ChangePanel` |

合计 ~710 行（含注释 / docstring）。

## 55.4 `TUIBridge` — 头层解耦

`TUIBridge` 是**唯一**与 `tui_gateway` 交互的代码。它做四件事：

1. **订阅**：在 `subscribe()` 中注册到 `CallbackRegistry` 的全部 7 个事件类型
3. **缓存**：维护 `events: deque[AgentEvent]`（500 ring）+ `billing` / `hosts` / `changes` 状态
4. **派发**：通过 `app.call_from_thread(method, *args)` 把事件传给 UI 线程
5. **重放**：晚 attach 时（如 app 启动前 AgentEvent 已发出），自动 replay buffer

关键设计：

* `app.call_from_thread` **不存在**时（测试 / headless 环境）自动降级为同步 `method(*args)`
* 失败 / 已退出的 app 永不抛出异常（log 后继续）

## 55.5 textual App 设计

### 55.5.1 4-pane 布局

```
┌─────────────────── Header (clock) ──────────────────┐
│ ┌──────────────────────────┬────────────────────┐ │
│ │                          │  BillingPanel      │ │
│ │      EventLog            ├────────────────────┤ │
│ │   (AgentEvent stream)    │  HostPanel         │ │
│ │                          ├────────────────────┤ │
│ │                          │  ChangePanel       │ │
│ └──────────────────────────┴────────────────────┘ │
├─────────────────── Footer (key bindings) ───────────┤
```

### 55.5.2 键盘绑定

| 按键 | 行为 |
|------|------|
| `Ctrl+C` | 退出 TUI |
| `Ctrl+L` | 清空 EventLog |
| `Ctrl+R` | 手动 refresh billing |
| `F1` | 帮助提示 |

### 55.5.3 `bridge_on_*` 命名约定

textual 的消息分发机制会自动调用 `on_<MessageType>`` 方法。我们故意把桥接方法命名为 `bridge_on_event / bridge_on_billing / ...` 以避免与 `events.Event` 基类的默认分发器冲突——之前的 `on_event(AgentEvent)` 会让 textual 把 AgentEvent 当作自己的消息协议去解析导致 `NoneType can't be used in 'await' expression`。

## 55.6 CLI 集成

```bash
# 标准入口（依赖 textual）
zeloo tui

# 演示模式（无需 LLM key，注入合成事件流）
zeloo tui --demo

# 调试日志
zeloo tui --log-level DEBUG
```

缺失 `textual` 时优雅降级：

```
The TUI requires the 'textual' package.
Install with:  uv pip install textual
```

## 55.7 可选依赖

| 包 | 用途 | `pyproject.toml` extra |
|----|------|----------------------|
| `textual >= 0.60` | TUI 框架 | `dev` / `tui` |
| `rich >= 13.0` | terminal rendering | `tui` |

缺包时 `zeloo_cli/perf/baseline.py` / `tui` 自动 no-op，其他子命令完全不受影响。

## 55.8 测试覆盖

* [tests/unit/test_tui_bridge.py](file:///C:/Users/38324/OneDrive/Desktop/primus/tests/unit/test_tui_bridge.py) — 16 个单元测试（formatters + bridge 状态机）
* [tests/unit/test_tui_widgets.py](file:///C:/Users/38324/OneDrive/Desktop/primus/tests/unit/test_tui_widgets.py) — 7 个 textual pilot 测试

合计 **23 个 TUI 测试**，全过。

| 测试维度 | 数量 |
|---------|------|
| Event formatter（5 种 event type） | 6 |
| Billing / Change / Host formatter | 3 |
| Bridge subscribe / unsubscribe | 1 |
| Bridge buffer + replay | 2 |
| Bridge billing refresh | 1 |
| Bridge record_change / register_host | 2 |
| availability 检测 | 1 |
| Widget 渲染（textual pilot） | 7 |

## 55.9 失败模式矩阵

| 场景 | 行为 |
|------|------|
| `textual` 未安装 | `zeloo tui` 打印安装提示并返回 1 |
| AgentEvent 没有 app 接收 | bridge buffer（最多 500 条），late attach 时 replay |
| app 已退出但 callback 仍在 | `call_from_thread` 失败 → log + 继续，agent 不崩 |
| textual `on_event` 与我们命名冲突 | 改成 `bridge_on_*` 避开基类 |
| Static `_content` 是 private | 测试改用 `panel.render()` |
| DataTable cell 解析 markup | `append_change` 在 `[/]` 切分 |

## 55.10 已知限制 / 后续

* **不接 LLM 调用**：TUI 是被动观察者；用户通过 CLI / 多平台 bot 发起对话，TUI 仅观察
* **Demo emitter 仅 1 个 session**：可扩展为多 session 切换
* **无 scroll-back 搜索**：EventLog 是 RichLog，超过 5000 行自动截断
* **未实现 WebSocket**：TUI 是本地进程，不能远程观察（需要时改用 Web Dashboard）

## 55.11 启动示意

```
$ zeloo tui --demo
┌─ Zeloo TUI ─ self-hosted agent runtime ──── 14:32:17 ─┐
│                                                      │
│ 14:32:12 [▶ start]    session=abc12345 demo=True      │
│ 14:32:13 [… thinking] session=abc12345 iteration=1    │
│ 14:32:13 [⚙ tool_call] session=abc12345 web_search... │
│ 14:32:14 [↳ result]  session=abc12345 web_search → ... │
│ 14:32:14 [✓ finish]   session=abc12345 tokens=100     │
│                                                      │
│                                                      │
│                                                      │
│ $0.1234 USD · 7 calls · in=1000 out=2000             │
│                                                      │
│ ┌─ hosts ──────────────────────────────────────────┐ │
│ │ name        os            cpus                   │ │
│ │ local       Linux 6.0     8                      │ │
│ └─────────────────────────────────────────────────┘ │
│ ┌─ changes ────────────────────────────────────────┐ │
│ │   modified /etc/config.yaml                       │ │
│ └─────────────────────────────────────────────────┘ │
├─ Ctrl+C quit · Ctrl+L clear · Ctrl+R refresh ─────────┤
└──────────────────────────────────────────────────────┘
```