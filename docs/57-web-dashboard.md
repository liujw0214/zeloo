# 57. Web Dashboard — 操作员控制台

## 57.1 概述

`zeloo_dashboard/` 是 Zeloo Agent 的**操作员** Web UI（与 [§56](./56-web-chat-ui.md) 的用户 chat UI 对偶）。审计 [§54](./54-frontend-audit.md) 中"Dashboard 渲染 0%"的 P2 backlog 在本轮全部回填。

**关键设计决策**：

* Dashboard **复用** 18 个 `zeloo_cli.web_routers/*` REST 端点（不重写），通过 `WebRouterBridge` ASGI 适配层挂在 FastAPI 后面
* 鉴权用真实的 `zeloo_cli.dashboard_auth.BasicAuthProvider`（pbkdf2-sha256 + 文件存储），不再用 `AuthRouter` 的 stub
* 3 个 dashboard-native 端点（`/api/dashboard/{health,usage,system}`）是 FastAPI 路由 — bridge 不抢这些路径
* 5 个 tab 单页 SPA（`/dashboard`）+ 登录页（`/login`），vanilla JS，无构建

```
┌─────────────── Browser ───────────────────┐
│  /login  (Jinja2 + login.js)              │
│   ↓ submit                                 │
│  POST /api/auth/login                     │
│   ↓ token in localStorage                 │
│  /dashboard (Jinja2 + dashboard.js)       │
│   ↓ 5 tabs: Overview / Sessions / Users / │
│           Settings / System               │
│   ↓ fetch with Bearer token               │
└─────────────────┬──────────────────────────┘
                  │ HTTP + Bearer
                  ▼
┌─────────── FastAPI app ───────────────────┐
│  DashboardAuthMiddleware (outermost)      │
│      │ extract token → BasicAuthProvider  │
│      ▼                                     │
│  _BridgeMiddleware                         │
│      │ /api/users /api/sessions           │
│      │ /api/settings  → WebRouterBridge   │
│      │                                     │
│      │ /api/dashboard/*  → fall through   │
│      ▼                                     │
│  FastAPI routes                            │
│      - /login /dashboard / static          │
│      - /api/auth/{login,logout,me}        │
│      - /api/dashboard/{health,usage,...}  │
└────────────────────────────────────────────┘
```

## 57.2 模块布局

| 文件 | 行数 | 职责 |
|------|------|------|
| `zeloo_dashboard/__init__.py` | 40 | `is_dashboard_available()` + `create_dashboard_app()` |
| `zeloo_dashboard/app.py` | 290 | FastAPI app factory + pages + auth/usage/health endpoints |
| `zeloo_dashboard/bridge.py` | 410 | `WebRouterBridge` ASGI 中间件 + `_StubApp` 触发 `register()` |
| `zeloo_dashboard/auth.py` | 130 | `DashboardAuthMiddleware` (Bearer + ?token= WS 兼容) |
| `zeloo_dashboard/cli.py` | 60 | `zeloo web-dashboard` 入口 |
| `zeloo_dashboard/templates/login.html` | 50 | 登录页 |
| `zeloo_dashboard/templates/dashboard.html` | 130 | 5-tab SPA shell |
| `zeloo_dashboard/static/login.js` | 60 | 登录表单 + 跳转 |
| `zeloo_dashboard/static/dashboard.js` | 380 | 5 tab 渲染 + fetch + token 401 自动跳转 |
| `zeloo_dashboard/static/dashboard.css` | 410 | 浅色主题 + sidebar + cards + tables + toast |
| `tests/unit/test_dashboard.py` | 365 | 26 个测试 |
| `docs/57-web-dashboard.md` | 280 | 14 节设计文档 |

合计 ~2,605 行新增 + 26 个测试。

## 57.3 WebRouterBridge 设计

### 57.3.1 复用 18 个 web_routers 端点

`zeloo_cli/web_routers/{auth,users,sessions,settings}.py` 用一个轻量的 `RouteContext` dataclass + `Router.register()` 装饰器注册 handler（`auth_router`、`users_router` 等都是模块级单例）。我们不重写这些 handler，而是让它们在 FastAPI 后面继续可用。

`WebRouterBridge` 是 ASGI 中间件：

1. **索引构建**：构造时遍历每个 router 的私有 `_routes` dict（通过 `Router.register(_StubApp())` 强制填充，因为 `_routes` 在 `register()` 中才被写入）
2. **路径匹配**：路径前缀 `/api/*` 命中后，把 `/api/users/abc` 翻译成 router 内部路径 `/users/abc`，再用模板路径（如 `/users/{id}`）查 handler 表
3. **请求解码**：从 ASGI scope 读 headers / query / body，构造 `RouteContext`（含 `user_id` — 从 `scope["state"]` 由 auth 中间件注入）
4. **调用 handler**：原 handler 是同步函数，返回 `(status, headers, body)` 三元组，bridge 把它写回 ASGI `send` 通道
5. **fall-through**：如果 path 在 `/api/*` 但 bridge 没有 handler（如 `/api/dashboard/health`），bridge 设置 `_bridge_handled = False` 并 return，wrapper 检测到没写过 response 就把请求 forward 给内层 FastAPI

### 57.3.2 关键 fix：template path → concrete path

原始 handler 用 `ctx.path.rsplit("/", 1)[-1]` 提取 id：

```python
@route("GET", "/users/{id}")
def get_user(self, ctx):
    target_id = ctx.path.rsplit("/", 1)[-1]   # ← 需要 concrete path
    ...
```

所以 bridge 必须把 **concrete 路径**（如 `/users/abc-123`）传给 handler，**不**是模板路径（`/users/{id}`）。模板路径只用作 handler dispatch 的 key。

### 57.3.3 关键 fix：bridge 不抢 `/api/dashboard/*`

bridge 只对 `web_routers/*` 拥有的 15 个路径响应（auth 除外 — 见下节）。dashboard-native 的 `/api/dashboard/{health,usage,system}` 不在 router 注册表里 → bridge fall-through → FastAPI 处理。

## 57.4 认证设计

### 57.4.1 真实 BasicAuthProvider

Round 50+ 已有 `zeloo_cli.dashboard_auth.BasicAuthProvider`：pbkdf2-sha256 哈希 + 文件用户存储 + 24h token TTL。我们用这个而不是 `AuthRouter`：

* `AuthRouter` 是 stub：任何 username + 任何 password 都通过（"login" 只创建 token，不验证）
* `BasicAuthProvider` 是真实的：密码校验 + token 生命周期 + revoke

### 57.4.2 三个关键不变量

1. **同一个 provider 实例**：`DashboardAuthMiddleware` 和 `/api/auth/login` / `/api/auth/me` 端点用**同一个** `BasicAuthProvider` 实例 — 这样 login 返回的 token 才能被 middleware 接受
2. **dashboard 自有 login endpoint**：不通过 bridge — 直接走 `provider.authenticate()`，避免 `AuthRouter` stub
3. **不挂载 auth_router 到 bridge**：`mount_web_routers(routers=(users, sessions, settings))` — auth 端点 dashboard 自己实现

### 57.4.3 中间件顺序

Starlette 的 `user_middleware` 列表：**第一个是最外层**（最靠近 client）。我们想让 auth 在外层、bridge 在内层：

```python
app.user_middleware = [
    Middleware(DashboardAuthMiddleware, ...),  # OUTERMOST
    *list(getattr(app, "user_middleware", []) or []),  # bridge
]
```

测试覆盖：401-without-token / 401-invalid-token / login-with-correct-pw / login-with-wrong-pw / logout-revokes-token / 路径模板（`/api/users/{id}` GET）。

### 57.4.4 默认 admin 引导

首次启动时没有 `users.json`，dashboard 调 `_default_auth_provider()` 自动创建 `admin/admin` 账号（密码通过 `BasicAuthProvider.add_user` 走 pbkdf2 哈希写入文件）。**生产部署必须立即改密码** — login.html 页面脚注也提示了这点。

## 57.5 5 个 Tab 的设计

| Tab | 数据源 | 主要 UI 元素 |
|-----|--------|---------------|
| **Overview** | `/api/dashboard/usage` + `/api/dashboard/health` | 4 个 KPI 卡（calls / in-tokens / out-tokens / cost）+ Top providers 进度条 + Health 列表 |
| **Sessions** | `/api/sessions` GET/POST/DELETE + `/api/sessions/{id}/archive` | 表格 + 行内 archive/delete 按钮 + 工具栏 ＋ New |
| **Users** | `/api/users` GET/POST/DELETE | 表格 + 删除按钮 + ＋ New（弹窗 prompt） |
| **Settings** | `/api/settings` GET/PUT + `/api/settings/system` | 4 字段表单 + system 只读 KV |
| **System** | `/api/dashboard/system` + `/api/dashboard/health` | Runtime KV + features 网格 + limits 网格 + health 列表 |

JavaScript 路由：纯 DOM 切换，5 个 section 用 `data-tab` 标记，`active` class 控制显示。每个 tab 首次激活时 fetch 一次数据，**不**用全局状态机（5 个 tab 状态独立简单）。

### 57.5.1 401 自动跳登录

所有 fetch 共享 `authFetch(path, init)` helper：

```js
async function authFetch(path, init = {}) {
    const r = await fetch(path, { ...init, headers: { Authorization: "Bearer " + token, ...init.headers } });
    if (r.status === 401) {
        localStorage.removeItem(TOKEN_KEY);
        location.assign("/login");
        return null;
    }
    return r;
}
```

这样 token 过期 / 被 revoke 后用户自动回到登录页，**不需要**前端定时器检查。

## 57.6 CLI 集成

```bash
# 独立启动（推荐）
zeloo web-dashboard                              # http://127.0.0.1:8081
zeloo web-dashboard --host 0.0.0.0 --port 8081
zeloo web-dashboard --reload                     # dev

# 合并到 chat（开发用）
zeloo web --with-dashboard                       # 把 dashboard 挂在同一进程
```

`zeloo web --with-dashboard` 用 `Starlette` Mount 把 dashboard 的子应用挂在 `/dashboard` / `/api/auth` / `/api/dashboard` 等前缀下，其余 `/` 路径走 chat。**生产环境不推荐** — dashboard 应单独部署在 internal port，由 Caddy / nginx 把 `/dashboard/*` 反代过去。

## 57.7 失败模式矩阵

| 场景 | 行为 |
|------|------|
| 缺 fastapi / uvicorn / jinja2 | `zeloo web-dashboard` 打印安装提示并返回 1 |
| 缺 token 访问受保护端点 | 401 + `{"error": "missing_token"}` + `WWW-Authenticate: Bearer` 头 |
| 错 token | 401 + `{"error": "invalid_token"}` |
| 错密码登录 | 401 + `{"error": "Invalid credentials"}` |
| 用户被删除后旧 token 还在用 | 24h 后自动过期（re-validate 时检查 `expires_at`） |
| 路径在 `/api/*` 但 bridge 不管（如 `/api/dashboard/health`） | bridge fall-through → FastAPI 处理 |
| 路径在 bridge 但 method 不对（如 `GET /auth/login`） | bridge 404 → FastAPI 也 404（标准 404） |
| usage DB 不存在 | `/api/dashboard/usage` 返回 `{"available": false, "error": "..."}` 不抛 500 |
| body 超过 1 MiB | 413 Payload Too Large |
| WebSocket 接 dashboard 路径 | 不处理（bridge 跳过非 http scope） |
| `BasicAuthProvider` 启动时缺 `users.json` | 调 `add_user("admin", "admin")` 自动 bootstrap |

## 57.8 测试覆盖

26 个测试，全过：

| 测试维度 | 数量 |
|---------|------|
| App 工厂 smoke | 1 |
| 页面路由（公开） | 3 |
| 静态资源 | 2 |
| 认证流（login / me / logout / 错密码 / 缺字段） | 5 |
| 401 拒绝（无 token / 错 token） | 2 |
| Bridge 端点（users / sessions / settings） | 4 |
| Dashboard-native 端点（health / usage / system） | 3 |
| Bridge fall-through | 1 |
| 路径模板（`/api/users/{id}` / `/api/sessions/{id}`） | 2 |
| `BasicAuthProvider` 单元 | 3 |

每个测试用 **独立的** `BasicAuthProvider`（tmp_path users_file）— 不污染全局状态、不依赖真实 `~/.Zeloo/` 目录。

## 57.9 依赖

复用 `zeloo_web` 的依赖：fastapi / uvicorn / jinja2（不需要 websockets — Dashboard 不走 WS）。已经在 Round 54 装过。

## 57.10 关键经验

* **`from __future__ import annotations` + FastAPI 0.141 不兼容**（同 Round 54）— 移除 `__future__` 导入。
* **Starlette 中间件顺序 = user_middleware 列表正序** — 第一个是最外层。要让 auth 包住 bridge，必须把 `DashboardAuthMiddleware` 放第一个，bridge 放第二个。
* **bridge 必须传 concrete path 给 handler** — `ctx.path.rsplit("/", 1)[-1]` 在 `/users/{id}` 上取到的是 `{id}` 文本，不是真实 id。
* **bridge 不能抢所有 `/api/*`** — 必须在没匹配时设置 `_bridge_handled = False` 并 return，让 wrapper 把请求 forward 给内层 FastAPI。
* **`Router._routes` 是 lazy** — 构造时为空，必须调 `register()`（哪怕用 stub app）才能填充。
* **token 必须来自同一个 AuthProvider** — middleware 和 login endpoint 共享 provider 实例，否则 token 永远验证不过（`AuthRouter` 跟 `BasicAuthProvider` 是两套 token store，跨实例不通）。
* **pytest-asyncio 0.24 + httpx 0.27 的 `async with AsyncClient`** — 某些版本组合会失败，fixture 改用显式 `try/finally + aclose()`。

## 57.11 已知限制 / 后续

* **5 tab 单页** — 不支持深链（如 `/dashboard#tab=users`）。Round 56 加 hash 路由。
* **无实时刷新** — 用户需点 Refresh 或 F5。Round 56 加 WebSocket 推送（与 TUI 共享 tui_gateway）。
* **无多 tenant** — 所有用户共享 sessions / users。Round 56+ 隔离。
* **用户管理用 `prompt()` 弹窗** — UX 差。Round 56 改 modal。
* **无 RBAC** — 所有登录用户都是 admin。Round 56 接 role 字段。
* **usage DB 在 sandbox 不可写** — `~/.Zeloo/usage.db` 在某些环境下报 disk I/O，UI 显示 "Usage DB unavailable" 卡片（不致命）。
* **无 RBAC 拒绝** — `provider.authenticate` 只验密码，不查 role。

## 57.12 启动示意

```
$ zeloo web-dashboard
2026-09-10 16:30:12 INFO uvicorn: Started server process [9876]
2026-09-10 16:30:12 INFO uvicorn: Uvicorn running on http://127.0.0.1:8081

# 浏览器打开 http://127.0.0.1:8081/login
#   username: admin
#   password: admin
# → 进入 /dashboard，看到 5 个 tab 的 SPA
```
