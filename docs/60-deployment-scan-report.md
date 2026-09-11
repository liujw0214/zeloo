# 60 · 部署环境扫描报告

> 时间：2026-09-10
> 范围：依赖 / Docker / 环境变量 / 生产配置 / 前端构建

---

## 1. 依赖层扫描

### 1.1 Python 运行时

| 依赖 | 版本要求 | 说明 |
|------|---------|------|
| Python | ≥ 3.10 | 核心运行时 |
| FastAPI | ≥ 0.141 | Web API 框架 |
| Starlette | — | FastAPI 依赖 |
| uvicorn | — | ASGI 服务器 |
| httpx | ≥ 0.27 | HTTP 客户端 |
| pydantic | ≥ 2.5 | 数据校验 |
| pytest | ≥ 8.0 | 单元测试 |
| ruff | ≥ 0.4 | Lint + 格式化 |

**uv / pip 安装建议**：`uv sync --frozen`（Docker build 使用冻结锁）。

### 1.2 Node.js 运行时（前端构建）

| 工具 | 版本要求 |
|------|---------|
| Node.js | ≥ 18（推荐 20 LTS）|
| npm | — |
| Vite | ≥ 6.0 |
| vue-tsc | — |

### 1.3 Python 可选特性组（`pip install Zeloo[feature]`）

| 特性 | 依赖包 |
|------|--------|
| `voice` | sounddevice |
| `browser` | playwright |
| `mcp` | mcp ≥ 1.0 |
| `tui` | textual ≥ 0.60, rich ≥ 13.0 |
| `dev` | pytest, ruff, mypy |
| `all` | 全部可选特性 |

### 1.4 zeloo_web_ui 前端依赖

| 包 | 版本 | 用途 |
|-----|------|------|
| vue | ^3.5 | 框架 |
| vue-router | ^4.5 | 路由 |
| pinia | ^2.3 | 状态管理 |
| naive-ui | ^2.40 | UI 组件库 |
| @vueuse/core | — | 工具 hook |
| sass | — | 样式预处理 |
| @types/node | — | TS 节点类型 |

---

## 2. Docker 部署扫描

### 2.1 现有 Dockerfile 分析

**路径**：`Dockerfile`（根目录）

**构建阶段**：
1. `AS builder` — 安装 uv + `uv sync --frozen`
2. `AS production` — 运行镜像，基于 `python:3.12-slim`
3. `AS s6` — 多服务 overlay

**安全特性**：
- ✅ 非 root 用户（`groupadd zeloo / useradd zeloo --uid 1000 --gid 1000）
- ✅ 只读文件系统（Dockerfile 中 `read_only: true`）
- ✅ Capability drop（`cap_drop: [ALL]`）
- ✅ 健康检查（healthcheck 内置）
- ✅ 资源限制（cpus / memory 配置）

### 2.2 docker-compose.yml 服务矩阵

| Profile | 服务 | 端口 | 用途 |
|---------|------|------|------|
| gateway | `gateway` | 8080 | FastAPI 网关 |
| cli | `cli` | — | 交互式 CLI（tty:true）
| s6 | `Zeloo-s6` | 8080 | 多服务 overlay |
| backup | backup | — | 定时快照 |

### 2.3 docker-compose.prod.yml 扩展

| 配置项 | 状态 |
|--------|------|
| 非 root 运行 | ✅ |
| 只读 FS + tmpfs | ✅ |
| Off-host 备份 | ✅ local / S3 / OSS 三后端 |
| Caddy 反代 | ✅（profile caddy）|
| Prometheus /metrics | ✅ |
| 资源限制（CPU/memory） | ✅ |
| 健康检查 | ✅ |
| 定时快照 | ✅ cron 调度 |
| 加密 WAL 归档 | ✅ Fernet AES-128 |
| 多 profile 切换 | ✅ gateway/cli/s6/backup/caddy/metrics |

---

## 3. 环境变量配置

### 3.1 .env.example（开发）

**强制填写的密钥**（`export` 模板）：
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`
- `OPENROUTER_API_KEY` / `DEEPSEEK_API_KEY`
- 所有 Provider API keys

**Zeloo 特有变量**：
| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZELOO_HOME` | `~/.Zeloo` | 数据根目录 |
| `ZELOO_MODE` | `cli` | 运行模式（cli / gateway）|
| `ZELOO_MODEL` | `gpt-4o` | 默认模型 |
| `ZELOO_PROVIDER` | `openai` | 默认 Provider |
| `ZELOO_DANGEROUS_POLICY` | `allow` | 危险工具策略 |
| `ZELOO_BG_REVIEW` | `false` | 后台自进化复盘 |
| `ZELOO_STREAM` | `true` | 流式输出开关 |
| `ZELOO_COST_WARN_THRESHOLD` | `10.0 USD` | 成本警告阈值 |
| `ZELOO_COST_ABORT_THRESHOLD` | `100 USD` | 成本熔断阈值 |
| `ZELOO_BACKEND` | `local` | 终端后端 |

### 3.2 .env.prod.example（生产）
- 强制设置 `ZELOO_API_TOKEN`（32 字节 hex）
- `ZELOO_MODE=gateway`
- 备份调度 + S3/OS S 端点配置

### 3.3 数据库存储路径约定

| 路径 | 用途 |
|------|------|
| `$ZELOO_HOME/.env` | Provider API Keys |
| `$ZELOO_HOME/skills/` | 技能定义 |
| `$ZELOO_HOME/memory/` | 记忆存储 |
| `$ZELOO_HOME/sessions/` | 会话状态 |
| `$ZELOO_HOME/web_chat.db` | Web Chat WAL（Round 56）|
| `$ZELOO_HOME/web_chat.db-wal` | WAL 日志 |
| `$ZELOO_HOME/skills/` | 技能目录 |

---

## 4. 前端构建与部署

### 4.1 zeloo_web_ui 构建流程

```bash
cd zeloo_web_ui
npm install
npm run build     # vue-tsc + Vite 构建产物 → dist/
```

**构建产物（dist/）**：
- `index.html` — 入口
- `assets/index-*.js` — 主 bundle（含 Naive UI，约 1.3MB gzip 348KB）
- `assets/vue-router-*.js` — 路由模块（gzip 62KB）
- `assets/SkillsView-*.js` — 视图懒加载 chunk
- `assets/*View-*.css` — 视图样式

### 4.2 FastAPI 挂载方式（Round 57）

**开发模式**（`npm run dev`）：
- Vite dev server：端口 5173
- Vite proxy：`/api` → `http://localhost:8000`
- 浏览器访问 `http://localhost:5173`

**生产模式**（Docker / 直接部署）：
- Vite 构建产物由 FastAPI 托管：
  - `/skills/` → `zeloo_web_ui/dist/index.html`（SPA 根）
  - `/skills/assets/*` → `zeloo_web_ui/dist/assets/*`
  - `/api/*` → FastAPI REST 路由（优先于 StaticFiles）
  - `/ws/chat/*` → WebSocket 端点

### 4.3 Caddy 反代（生产推荐）

```nginx
# docker-compose.prod.yml profile=caddy
# Caddyfile 配置（docker/cont-init.d/ 中生成）
```

### 4.4 端口映射

| 服务 | 端口 | 说明 |
|------|------|------|
| FastAPI / uvicorn | 8080 | 生产 gateway 模式 |
| Vite dev | 5173 | 开发时使用 |
| Caddy | 80/443 | 生产反代 |
| Prometheus | 9090 | 指标抓取 |
| pgAdmin（可选） | 5050 | PostgreSQL 管理 |
| Redis（可选）| 6379 | 会话缓存 |

---

## 5. 生产部署清单

### 5.1 前置条件
- [ ] Python ≥ 3.10 环境
- [ ] Node.js ≥ 18 + npm
- [ ] Docker + docker-compose
- [ ] 至少一个 LLM API Key（`OPENAI_API_KEY` 等）
- [ ] 域名（生产环境）

### 5.2 部署步骤

```bash
# 1. 构建前端
cd zeloo_web_ui && npm run build

# 2. 填入环境变量
cp .env.example .env
# 编辑 .env 填入真实 API Keys

# 3. 启动（开发）
uvicorn zeloo_web:build_app --factory --reload --port 8000

# 4. 生产启动
docker compose -f docker-compose.prod.yml --profile gateway up -d

# 5. 验证
curl http://localhost:8080/healthz
```

### 5.3 生产 Checklist

- [ ] API Keys 已填入 `.env`
- [ ] `ZELOO_API_TOKEN` 已生成（32 字节 hex）
- [ ] 非 root 用户运行
- [ ] 资源限制（CPU / memory）已配置
- [ ] SSL 证书（Caddy auto-LetsEncrypt）或手动配置
- [ ] 备份策略（cron / S3 / OSS）已配置
- [ ] 日志轮转（日志文件告警阈值设置
- [ ] 监控（PROMETHEUS 端点 `/metrics`）

---

## 相关文档

| 文件 | 用途 |
|------|------|
| `pyproject.toml` | Python 依赖定义 |
| `requirements.txt` | pip 冻结依赖 |
| `Dockerfile` | 镜像构建 |
| `docker-compose.yml` | 开发编排 |
| `docker-compose.prod.yml` | 生产编排 |
| `.env.example` | 开发变量模板 |
| `.env.prod.example` | 生产变量模板 |
| `package.json`（zeloo_web_ui/） | 前端依赖 |
| `vite.config.ts`（zeloo_web_ui/） | 前端构建配置 |
| `AGENTS.md` | 工作区规范 |

---

## 相关文档

- [docs/53-prod-deployment.md](file:///c:/Users/38324/OneDrive/Desktop/primus/docs/53-prod-deployment.md) — Docker 生产部署手册
- [docs/58-hermes-inspired-frontends.md](file:///c:/Users/38324/OneDrive/Desktop/primus/docs/58-hermes-inspired-frontends.md) — Web 前端技术栈
- [docs/59-vue3-skills-ui.md](file:///c:/Users/38324/OneDrive/Desktop/primus/docs/59-vue3-skills-ui.md) — Vue 3 技能 UI
- [docs/README.md](file:///c:/Users/38324/OneDrive/Desktop/primus/docs/README.md) — 文档索引
