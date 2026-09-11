# COMPAT_MANIFEST.md — Zeloo 兼容性清单

本文档记录 Zeloo 支持的所有外部集成及其版本兼容性要求。

## Python 环境

| 运行时 | 最低版本 | 推荐版本 | 状态 |
|--------|---------|---------|------|
| Python | 3.11 | 3.12 | ✅ 支持 |
| uv | 0.4 | 最新 | ✅ 支持 |
| pip | 24.0 | 最新 | ✅ 支持 |

## LLM 模型提供者

| 提供者 | API 版本 | 最低模型 | 上下文要求 | 状态 |
|--------|---------|---------|---------|------|
| OpenAI | chat/completions v1 | gpt-4o | 128K | ✅ 支持 |
| Anthropic | 2023-06-01 | claude-3-5-sonnet | 200K | ✅ 支持 |
| DeepSeek | v1 | deepseek-chat | 64K | ✅ 支持 |
| Google Gemini | v1beta | gemini-1.5-flash | 1M | ✅ 支持 |
| AWS Bedrock | — | Claude 3 Sonnet | 200K | P2 |
| Azure OpenAI | 2024-08-01 | gpt-4o | 128K | P2 |
| OpenRouter | — | — | — | P1 |
| Groq | — | llama-3.1 | 128K | P1 |

## 消息平台

| 平台 | 协议版本 | API 要求 | 状态 |
|------|---------|---------|------|
| Telegram | Bot API 6.9+ | Bot Token | ✅ 支持 |
| Discord | v10 | Bot Token | ✅ 支持 |
| Slack | Bolt SDK | Bot Token | ✅ 支持 |
| 飞书 | 开放平台 v3 | App ID/Secret | ✅ 支持 |
| 钉钉 | 5.0 | AppKey/Secret | ✅ 支持 |
| 企业微信 | 3.1 | CorpID/Secret | ✅ 支持 |
| Microsoft Teams | Graph API | Client ID/Secret | ✅ 支持 |
| WhatsApp | Cloud API | Phone Number ID | ✅ 支持 |
| Signal | — | — | P2 |
| SMS (Twilio) | — | SID/AuthToken | P2 |

## 终端后端

| 后端 | 最低要求 | 状态 |
|------|---------|------|
| local | 系统 Shell | ✅ 支持 |
| docker | Docker daemon | ✅ 支持 |
| ssh | SSH client | ✅ 支持 |
| modal | modal.com account | P2 |
| daytona | Daytona.io account | P2 |
| vercel_sandbox | Vercel account | P2 |
| singularity | SingularityCE | P2 |

## 记忆后端

| 后端 | 类型 | 状态 |
|------|------|------|
| LocalFile | SQLite 本地 | ✅ 支持 |
| Honcho | 第三方服务 | ✅ 支持 |
| Mem0 | 第三方服务 | ✅ 支持 |
| OpenViking | 第三方服务 | ✅ 支持 |
| Supermemory | 第三方服务 | ✅ 支持 |
| Byterover | 第三方服务 | ✅ 支持 |
| Hindsight | 第三方服务 | ✅ 支持 |
| Holographic | 第三方服务 | ✅ 支持 |
| RetainDB | 第三方服务 | ✅ 支持 |

## MCP 服务器

### 内置支持

| 服务器 | 状态 |
|--------|------|
| stdio 本地 | ✅ 支持 |
| HTTP 远程 | ✅ 支持 |

### 可选 MCP（详细见 docs/24）

| 类别 | 示例 | 状态 |
|------|------|------|
| 开发工具 | GitHub, GitLab, Notion | P1 |
| 项目管理 | Linear, Jira, Asana | P2 |
| 通信 | Slack, Discord, Teams | P2 |
| 支付 | Stripe, PayPal | P2 |
| 数据库 | Supabase, Neon | P2 |

## 操作系统

| OS | 支持版本 | 状态 |
|----|---------|------|
| Linux (Ubuntu) | 20.04+ | ✅ 支持 |
| Linux (Debian) | 11+ | ✅ 支持 |
| macOS | 12+ (Intel/Apple Silicon) | ✅ 支持 |
| Windows | 10/11 (WSL2 recommended) | ✅ 支持 |
| NixOS | 24.05+ | P2 |

## 容器化

| 工具 | 版本 | 状态 |
|------|------|------|
| Docker | 24.0+ | ✅ 支持 |
| docker-compose | 2.20+ | ✅ 支持 |
| s6-overlay | v3 | P2 |
| Nix Flakes | 0.20+ | P2 |

## 浏览器自动化

| 工具 | 状态 |
|------|------|
| Playwright (browser_tools.py) | ✅ 支持 |
| computer_use 工具 | P2 |

## 数据库

| 数据库 | 版本 | 用途 | 状态 |
|--------|------|------|------|
| SQLite | 3.45+ | 会话存储 | ✅ 支持 |
| FTS5 | — | 全文搜索 | ✅ 支持 |
| WAL mode | — | 并发读写 | ✅ 支持 |

## Node.js（前端工具）

| 用途 | 最低版本 | 推荐版本 | 状态 |
|------|---------|---------|------|
| MCP 工具执行 | 18+ | 22 | ✅ 支持 |
| TUI 界面 | 18+ | 22 | P2 |
| 桌面客户端 | 22 | 22 | P3 |
| Web 管理界面 | 18+ | 22 | P3 |

## 依赖兼容性

所有 Python 依赖通过 `uv sync --frozen` 精确锁定版本。依赖变更必须通过以下流程：

1. 在 `pyproject.toml` 中更新版本
2. 运行 `uv lock` 重新生成 `uv.lock`
3. 提交变更并说明原因
4. CI 验证 `uv.lock` 一致性

## 已知兼容性限制

1. **Windows 原生**：部分终端工具（shell/SSH）需要 WSL2 或 Git Bash
2. **macOS Apple Silicon**：可能需要 Rosetta 2 运行部分 Node.js 工具
3. **Linux headless**：browser_tools 需要 xvfb 或无头模式
4. **旧版 SQLite**：低于 3.45 可能缺少 FTS5 高级特性
