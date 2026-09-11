# 56. Web Chat UI — 浏览器内流式对话（FastAPI + WebSocket）

## 56.1 概述

`zeloo_web/` 是 Zeloo Agent 的**浏览器内 Chat 前端**，基于 FastAPI + 原生 WebSocket + Jinja2 构建。它是审计 [§54](./54-frontend-audit.md) 中"Web Chat UI / WebSocket / SSE 0%"回填实现（与 Round 52-53 的 TUI 对应 — 终端有 TUI，浏览器有 Web Chat）。

**关键设计决策**：Web Chat 是 `ConversationLoop.on_token` 流式回调的**纯消费者**。Agent 循环仍由 `agent.conversation_loop.py` 驱动，前端只渲染 token / tool_call / tool_result / done 四种事件。本轮不重新实现 LLM 调用路径。

```
┌─────────────── Browser ───────────────────┐
│  /chat/{sid}  (Jinja2)                     │
│  ┌──────────┐  ┌─────────────────────┐   │
│  │ sidebar  │  │ chat.js              │   │
│  │ sessions │  │  ↕ WebSocket          │   │
│  └──────────┘  └─────────────────────┘   │
└─────────────────┬──────────────────────────┘
                  │ ws://…/ws/chat/{sid}
                  ▼
┌───────────── FastAPI app ─────────────────┐
│  ChatSocket.handle(scope, receive, send)   │
│   ↕ task pair (asyncio.wait)               │
│  receive_task ↔ turn_task                 │
│                  │                         │
│                  ▼                         │
│  ConversationLoop.run(messages, on_token)  │
└────────────────────────────────────────────┘
```

## 56.2 模块布局

| 文件 | 行数 | 职责 |
|------|------|------|
| `zeloo_web/__init__.py` | 60 | `is_web_available()` / `build_app()` |
| `zeloo_web/app.py` | 175 | FastAPI app factory + REST surface + WebSocket route |
| `zeloo_web/chat_socket.py` | 460 | `ChatSocket` ASGI 处理器 + 协议常量 + agent runner |
| `zeloo_web/sessions.py` | 165 | `ChatSession` / `ChatSessionStore`（线程安全） |
| `zeloo_web/cli.py` | 80 | `zeloo web` 入口 + uvicorn 配置 |
| `zeloo_web/templates/chat.html` | 80 | 单页 chat UI（sidebar + messages + composer） |
| `zeloo_web/static/chat.js` | 340 | WebSocket 客户端 + 流式渲染 + 工具可视化 |
| `zeloo_web/static/style.css` | 290 | 浅色主题 + 响应式 |
| `tests/unit/test_web_chat.py` | 525 | 22 个测试（HTTP + WS + session store） |

合计 ~2,175 行新增 + 22 个测试。

## 56.3 协议（Wire Protocol）

WebSocket 每帧一个 JSON 对象，`type` 字段是判别器。

### 56.3.1 客户端 → 服务端

| `type` | 字段 | 用途 |
|--------|------|------|
| `user` | `content: str` | 用户消息 — 触发一轮 agent run |
| `ping` | — | 心跳，浏览器每 20s 发送一次防止反向代理切断 |

### 56.3.2 服务端 → 客户端

| `type` | 字段 | 用途 |
|--------|------|------|
| `ready` | `session_id` | 握手成功（紧随 `accept`） |
| `thinking` | — | Agent 即将开始推理；UI 切换为"thinking…"指示 |
| `tool_call` | `name`, `args` | 工具调用可视化（黄底） |
| `tool_result` | `name`, `content` | 工具结果可视化（绿底） |
| `delta` | `content` | 单个 LLM token（拼到流式气泡） |
| `done` | `content`, `turn` | 整轮完成，提交权威 assistant 内容 |
| `error` | `message` | 帧解析错误 / agent run 异常 |
| `pong` | `ts` | 响应 ping |

### 56.3.3 工具事件隧道

`on_token(token: str)` 是 `ConversationLoop` 的回调签名，模型只产 `str`。但前端要 `tool_call` / `tool_result` 这种结构化事件。解决方法：在 `emit()` 内部把结构化事件序列化为 `__EVT__:{json}` 标记，socket 解码时再分流。

```python
async def emit(token: str) -> None:
    evt = _decode_event(token)         # 是否 __EVT__: 标记？
    if evt is not None:
        await _ws_send_json(send, evt) # 透传结构化事件
    else:
        await _ws_send_json(send, {"type": "delta", "content": token})
```

因为模型产出绝不会以 `__EVT__:` 起始（控制字符 + 字母都是普通 token），分流是**无歧义**的。

## 56.4 任务对（Task Pair）取消模式

`ChatSocket._serve` 用 `asyncio.wait` 同时跑 `receive_task` + `turn_task`：

```python
done, pending = await asyncio.wait(
    {receive_task, turn_task},
    return_when=asyncio.FIRST_COMPLETED,
)
```

* **正常路径**：`receive_task` 在用户发下一条消息前一直挂着；`turn_task` 先完成 → 提交 assistant → 回到 wait
* **取消路径**：用户点 Cancel 发新 `user` 帧 → `receive_task` 先完成 → `turn_task.cancel()` → 旧轮终止、新轮开始

这是用户对"聊天机器人卡死"的核心诉求：**新消息必须立即打断旧消息**。

## 56.5 智能体接入

`ChatSocket.agent_runner: Callable` 接受 `(session, user_message, emit)` → 返回完整 assistant 文本。生产路径：

```python
def _default_agent_factory(session, user_message, emit):
    from agent.conversation_loop import ConversationLoop
    history = [m.to_dict() for m in session.messages]
    return _run_conversation_loop(session, history, user_message, emit)
```

其中 `_run_conversation_loop` 把同步的 `ConversationLoop.run(messages, on_token=_on_token)` 放到 `loop.run_in_executor` 上跑。`on_token` 是从 executor 线程触发的，通过 `asyncio.run_coroutine_threadsafe(emit(token), loop)` 把 emit 调度回主事件循环 — 这样它跟 WebSocket 的 send 自然交错。

> **关键不变量**：Web Chat 走的是和 CLI `python cli.py chat` **完全相同**的 agent runtime。模型 / 工具 / 记忆 / 计费 一字不差。

## 56.6 前端

### 56.6.1 单文件 vanilla JS（无构建步骤）

`chat.js` 是一个 IIFE，不依赖任何 npm 模块 — 直接 `<script src="/static/chat.js" defer>` 加载。这避免了 npm bundler / React / Vue 带来的部署复杂度，对 Round 54 的最小可工作集是合适的。后续若要拆组件可以迁移到 Preact / Lit。

### 56.6.2 三块布局

```
┌─ topbar (header / session_id / conn-status / actions) ─┐
│ sidebar (220px)        │  messages (auto-scroll)        │
│  Sessions list         │                                 │
│  - abc12345 ●  busy    │  ┌─ user ─────────────────┐    │
│  - def67890            │  │ hi                      │    │
│  + New                 │  └─────────────────────────┘    │
│                        │  ┌─ assistant (streaming) ─┐    │
│                        │  │ hello w▌                │    │
│                        │  └─────────────────────────┘    │
│                        │  ┌─ tool_call ─────────────┐    │
│                        │  │ web_search              │    │
│                        │  │ {q: "..."}              │    │
│                        │  └─────────────────────────┘    │
│                        │  ┌─ tool_result ────────────┐    │
│                        │  │ 5 hits                   │    │
│                        │  └─────────────────────────┘    │
│                        ├─ composer (textarea + send) ──  │
└────────────────────────────────────────────────────────┘
```

### 56.6.3 流式渲染

`appendDelta(token)` 把 token 拼到 `activeStreamBuffer` 并写回 `body.textContent`，**不在 DOM 中插入节点** — 避免每 token 一次 reflow。`endStream()` 移除 `.streaming` class，光标动画停止。

### 56.6.4 心跳 / 断线指示

`conn-status` 元素用 3 种状态：
* `ready`（绿）— WS 已建立
* `thinking`（黄）— Agent 运行中
* `closed`（红）— 断线 / 无 session

每 20s 客户端发 `ping`，服务端回 `pong`。反向代理（nginx / caddy）默认 60s 切断空闲 WS，心跳防止误杀。

## 56.7 CLI 集成

```bash
zeloo web                              # http://127.0.0.1:8080
zeloo web --host 0.0.0.0 --port 8080   # 公网绑定
zeloo web --reload                     # 开发模式（uvicorn --reload）
zeloo web --log-level DEBUG
```

缺依赖时优雅降级：

```
The Web Chat UI requires fastapi, uvicorn, jinja2 and websockets.
Install with:  uv pip install fastapi uvicorn jinja2 websockets
```

## 56.8 REST 端点（与 WebSocket 配合）

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/` | 渲染 chat.html（无 session → 显示欢迎页 + ＋New 提示） |
| `GET` | `/chat/{sid}` | 渲染 chat.html（带 session_id → 自动连 WS） |
| `GET` | `/healthz` | 健康检查 |
| `GET` | `/api/sessions` | 列表（供 sidebar 拉取） |
| `POST` | `/api/sessions` | 创建新 session（返回 id，前端跳转） |
| `GET` | `/api/sessions/{sid}` | 详情 + 消息历史 |
| `DELETE` | `/api/sessions/{sid}` | 删除 |
| `WS` | `/ws/chat/{sid}` | 流式对话 |

`zeloo_cli.web_routers.*` 18 个端点保持原样不动（Dashboard 在 Round 55 会用），Web Chat 用自己的一组 in-memory 端点。

## 56.9 测试覆盖

22 个测试，全过：

| 测试维度 | 数量 |
|---------|------|
| App 工厂 + HTTP 路由 | 4 |
| session_id 路径解析 | 7 |
| WebSocket 拒绝未知 session | 1 |
| 流式往返 + tool 事件 + ping | 3 |
| 帧错误处理（invalid JSON / unknown type / empty） | 3 |
| Stale turn 取消 | 1 |
| Session store CRUD + 并发 | 3 |

**驱动方式**：用 `_QueueTransport`（`asyncio.Queue` 包装的 send/receive mock）直接驱动 ASGI socket，**不依赖真实网络端口** — CI 在 Windows runner 上也能跑。

## 56.10 依赖

```toml
# pyproject.toml
[project.optional-dependencies]
web = ["fastapi>=0.115", "uvicorn>=0.30", "jinja2>=3.1", "websockets>=12"]
```

安装：

```bash
uv pip install fastapi uvicorn jinja2 websockets
```

依赖是**可选**的 — 没装时 `is_web_available()` 返回 False，CLI 打印安装提示而不崩。

## 56.11 失败模式矩阵

| 场景 | 行为 |
|------|------|
| 缺 fastapi/uvicorn/jinja2/websockets | `zeloo web` 打印安装提示并返回 1 |
| 未知 session_id | WS 握手时 `close(1008, "unknown session")` |
| 空 content / 非 JSON / 未知 type | 发送 `error` 帧，不关闭 socket |
| 客户端断线 | `turn_task` 取消 + handler 退出 |
| 客户端发新消息时旧 turn 还在跑 | `turn_task.cancel()` + `await turn_task` 让出 |
| Agent 抛异常 | 发送 `error` 帧，session 不变 busy，handler 继续等下一帧 |
| HTTP 模板找不到 | 返回 500（开发期发现 — 没装 templates 会显式报） |
| 浏览器多标签页打开同一 session | 每个标签独立 WS，但都写同一 session — Round 55 Dashboard 引入鉴权后隔离 |

## 56.12 已知限制 / 后续（Round 55+）

* **没有鉴权** — 任何拿到 URL 的人都能用。Round 55 接入 `dashboard_auth.BasicAuthProvider`。
* **session 在内存** — 重启丢失。Round 55 持久化到 SQLite。
* **不支持 abort 帧** — 取消时是发"新空白 user"让新 turn 取消旧 turn。Round 55 引入专用的 `{"type": "abort"}`。
* **没有 stream 速率限制** — 后台有 `RateLimiter` 但 WS handler 没用上。Round 55 接入。
* **无 markdown 渲染** — tool_call JSON 用了 `<pre>`，assistant 用 `textContent`（即纯文本）。Round 55 用 `marked.js` 渲染。
* **多 modal（图片 / 文件）** — 暂时只支持文本输入输出。Round 56+。

## 56.13 启动示意

```
$ zeloo web
2026-09-10 14:32:17 INFO uvicorn: Started server process [12345]
2026-09-10 14:32:17 INFO uvicorn: Waiting for application startup.
2026-09-10 14:32:17 INFO uvicorn: Application startup complete.
2026-09-10 14:32:17 INFO uvicorn: Uvicorn running on http://127.0.0.1:8080

# 浏览器打开 http://127.0.0.1:8080 → 点击 ＋ New → 输入 "hi" → 流式回复
```

## 56.14 关键经验

* **`from __future__ import annotations` 与 FastAPI 0.141 不兼容** — `request: Request` 会被识别成 query 参数而不是注入参数。修复：从 `__future__` 导入移除，依赖 Python 3.10+ 的原生类型注解。
* **Starlette `TemplateResponse` 签名变了** — 新版要求 `request` 作为第一位置参数（不是 context dict 里的 key），否则 cache key 是 dict 不可哈希。
* **WebSocket `await receive()` 会阻塞整个 handler** — 单 receive → 处理 → await receive 的写法无法取消正在跑的 turn。改用 `asyncio.wait({receive_task, turn_task})` 才能让新消息打断旧 turn。
* **`on_token` 是同步回调** — agent 在 executor 线程跑，回调里用 `asyncio.run_coroutine_threadsafe(emit, loop)` 调度回主 loop，不要直接 `await`（会跨 loop 报错）。
* **`_QueueTransport` 测 ASGI** — 用 `asyncio.Queue` 模拟 send/receive，免开端口、免 uvicorn、不污染 socket。CI 友好。
