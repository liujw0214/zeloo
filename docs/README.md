# Zeloo Agent 开发文档

> **Zeloo** — The agent that grows with you.
> 一个自托管、自进化的常驻型 AI Agent 运行时框架。
>
> *项目原名 Zeloo，2026-09-09 正式更名为 Zeloo*

本套文档是 Zeloo 框架的完整开发规范，覆盖架构设计、核心模块、工程规范、安全约束与开发路线图。

---

## 文档索引

| 编号 | 文档 | 内容 |
|------|------|------|
| 01 | [整体架构设计](./01-architecture.md) | 分层组合式架构、核心设计哲学、模块边界 |
| 02 | [System Prompt 三层架构](./02-system-prompt.md) | stable/context/volatile 分层、prefix cache 优化、字节稳定性 |
| 03 | [Agent 对话循环](./03-agent-loop.md) | 思考-行动循环、迭代预算、并行工具执行、中断机制 |
| 04 | [工具系统与 MCP](./04-tool-system.md) | 工具自动发现、工具集分发、MCP 双传输、子代理委托、Voice 后端、插件系统 |
| 05 | [记忆与技能系统](./05-memory-skills.md) | 持久记忆、USER.md 画像、Skills 渐进披露、索引缓存 |
| 06 | [自进化闭环](./06-self-evolution.md) | 后台复盘、技能固化、记忆写入、轨迹采集、Nudge 机制 |
| 07 | [多平台网关与终端后端](./07-platform-gateway.md) | 消息网关、7 种终端后端、平台提示差异化、APIServer |
| 08 | [目录结构与工程规范](./08-project-structure.md) | 目录划分、命名规范、依赖锁定、配置隔离、profiles 隔离 |
| 09 | [浏览器自动化](./09-browser.md) | BrowserBase/Firecrawl 提供者、PageSnapshot、CrawlResult |
| 10 | [开发路线图](./10-roadmap.md) | 分阶段里程碑、当前完成状态、风险与依赖 |
| 11 | [核心模块详解](./11-core-modules.md) | estop/insights/i18n/credential_pool/error_classifier/cost_tracker/runtime_cwd/curator/kanban/hooks 完整 API |
| 12 | [Cron 定时任务系统](./12-cron-system.md) | CronScheduler 调度器、5 字段表达式、防重复触发、工具接入 |
| 13 | [OAuth 设备码授权](./13-oauth.md) | OAuth 2.0 设备授权流、Token 刷新、ProviderRouter 集成 |
| 14 | [MCP 系统](./14-mcp-system.md) | MCPServerManager/StdioMCPClient/HttpMCPClient 完整 API |
| 15 | [数据生成与轨迹压缩](./15-datagen.md) | 轨迹压缩策略、训练数据导出、压缩配置 |
| 16 | [配置参考手册](./16-config-reference.md) | 全部配置项详解（30 个配置节：模型/终端/语音/网关/平台/记忆/MCP/Cron/工作区/委托/多模态/国际化等） |
| 17 | [会话状态管理](./17-session-state.md) | SessionDB / SQLite WAL+FTS5 / 会话持久化 / 全文搜索 |
| 18 | [Agent 模块开发计划](./18-dev-plan-agent-modules.md) | 11 个缺失模块 API 设计（context_compressor/chat_completion_helpers/agent_init 等） |
 | 19 | [zeloo_cli 开发计划](./19-dev-plan-zeloo-cli.md) | CLI 子命令/配置加载/安装修复/仪表盘认证 |
 | 20 | [插件扩展开发计划](./20-dev-plan-plugins.md) | 已实现 2 模型/3 搜索/3 图像/3 视频生成提供者（目标 41/10/8/3） |
 | 21 | [可选技能模块](./21-optional-skills.md) | optional_skills Python 模块（software_dev/devops/data_science/security 等） |
 | 22 | [zeloo_state 状态管理](./22-zeloo-state.md) | 状态管理子系统：schema/repair/maintenance/guard/readpool/errors + 顶层状态文件 |
 | 23 | [agent/transports 开发计划](./23-transports.md) | 5 个传输适配器（Anthropic/Bedrock/Gemini/Azure） |
 | 24 | [可选 MCP 服务器](./24-optional-mcps.md) | 已实现 18 个 MCP 服务器（GitHub/GitLab/Notion/Linear/Gmail/Slack/Airtable 等，目标 65 个） |
 | 25 | [Docker 容器配置](./25-docker.md) | s6-overlay/entrypoint/docker-compose/Dockerfile |
 | 26 | [CI/CD 流水线](./26-cicd.md) | 11 个 GitHub Actions 工作流（ci/pr-checks/security/docker/release/docs/perf-regression/multi-platform/lint/test/typecheck） |
| 27 | [原生扩展开发计划](./27-native-extensions.md) | FTS5 CJK 中文分词扩展（Rust） |
| 28 | [Nix 构建配置](./28-nix-build.md) | flake.nix/devShell/homeManager |
| 29 | [computer_use 计算机工具](./29-computer-use.md) | screenshot/mouse/keyboard/window 全套 API |
| 30 | [子包 AGENTS 工作流](./30-agents-workflow.md) | 各包 AGENTS.md 规范模板（cron/skills/evals 等） |
| 31 | [Supabase MCP 服务器](./31-supabase-mcp.md) | Supabase MCP Server 实现（数据库/Auth/Storage/Functions） |
| 32 | [安全设计](./32-security.md) | Prompt 注入扫描、权限管控、供应链安全、数据脱敏、threat_patterns |
| 33 | [工作区管理](./33-workspace.md) | WorkspaceManager + WorkspaceSnapshot（create/list/switch/archive/restore/delete） |
| 34 | [终端后端](./34-terminal-backends.md) | 7 种后端（local/ssh/docker/modal/daytona/vercel_sandbox/singularity）|
| 35 | [代理委托工具](./35-delegate-tool.md) | 子代理委托（leaf/orchestrator 角色、线程池、超时、零知识隔离） |
| 36 | [国际化与环境](./36-i18n-and-environments.md) | locales/ + environments/ + config-examples/ 三层配置体系 |
| 37 | [zeloo CLI 核心框架](./37-core-framework.md) | zeloo_cli/core：16 个企业级核心模块（事件/调度/缓存/限流/熔断/任务队列/中间件/多租户/实时/追踪/指标/特性开关/密钥/生命周期/插件/状态） |
| 38 | [视频生成模块](./38-video-gen.md) | video_gen 包：DeepInfra / FAL.ai / xAI Grok Video 三个 provider + 下载工具 + 实例缓存 + 完整 API 参考 |
| 39 | [框架完整性扫描报告](./39-framework-audit.md) | 综合扫描报告：5 维度成熟度评级 + 文档覆盖矩阵 + 待开发任务清单入口 |
| 40 | [待开发任务清单](./40-backlog.md) | Backlog 详细清单：P1/P2/P3 共 21 项任务 |
| 41 | [Provider 使用指南](./41-provider-guide.md) | LLM/Web/MCP/Image/Video/Messaging Provider 完整接入指南、环境变量配置、成本追踪 |
| 42 | [故障排查与 FAQ](./42-faq.md) | 23 个常见问题与解决方案（安装/配置/运行时/部署/运维） |
| 43 | [性能调优指南](./43-performance-tuning.md) | 性能基准测试、Token 优化、并发、缓存、数据库调优、CI 性能回归 |
| 44 | [贡献指南](./44-contributing.md) | 开发环境准备、代码规范、提交流程、测试指南、PR 审查标准 |
| 45 | [optional_skills API 参考](./45-optional-skills-api.md) | 6 个技能模块 + skill_loader 完整 API、工具集成、测试覆盖 |
| 46 | [深度扫描报告](./46-deep-scan-report.md) | Docker / CI/CD / perf / 文档站点 / 框架完整度评估 |
| 47 | [状态备份系统](./47-state-backup.md) | state backup / 加密 / 跨机恢复 |
| 48 | [性能基线对比](./48-perf-baseline.md) | perf baseline + p50/p95/p99 + 回归告警 |
| 49 | [SQLite PITR 增量恢复](./49-pitr.md) | WAL 归档 + 增量恢复 + RPO 控制 |
| 50 | [Segment 加密 + Off-Host 推送](./50-segment-encryption.md) | Fernet AES-128 segment 加密 + 异地推送 |
| 51 | [Off-Host 推送（多后端）](./51-offhost-push.md) | Local/S3/OSS pusher + 失败重试 + 完整性校验 |
| 52 | [部署 / 完成度 / 环境扫描审计](./52-deployment-audit.md) | Round 51 综合审计：项目规模 / 部署 / 配置层级 |
| 53 | [生产级 Docker 部署](./53-prod-deployment.md) | docker-compose.prod.yml + Caddy + Prometheus + 6 service 矩阵 |
| 54 | [前端完成度审计](./54-frontend-audit.md) | CLI / Landing / TUI / Web 4 维度评分 + backlog |
| 55 | [TUI 渲染（textual）](./55-tui-rendering.md) | textual App + TUIBridge + 4-pane 布局 + demo emitter |
| 56 | [Web Chat UI](./56-web-chat-ui.md) | FastAPI + WebSocket + 流式 chat + 工具调用可视化 + 任务对取消模式 |
| 57 | [Web Dashboard](./57-web-dashboard.md) | 操作员控制台 + 5 tab SPA + BasicAuthProvider + WebRouterBridge 复用 18 个 web_routers 端点 |
| 58 | [Hermes Agent 前端技术借鉴 + Web 技术栈](./58-hermes-inspired-frontends.md) | Setup Wizard / Skin Engine / TUI 历史+补全 / Web Markdown 渲染 / Session 持久化 / **Vue 3+Vite+TS 迁移规划** |
| 59 | [Vue 3 技能 UI](./59-vue3-skills-ui.md) | zeloo_web_ui: Vue 3 技能画廊 / 详情视图 / Pinia Store / SCSS Token / Naive UI |
| 60 | [部署环境扫描报告](./60-deployment-scan-report.md) | 依赖 / Docker / 环境变量 / 前端构建 / 生产 CheckList |
| 61 | [.env 双端同步指南](./61-env-sync-guide.md) | ZELOO_HOME 大小写修正 + 项目根与 ZELOO_HOME 同步策略 |
| 62 | [Zeloo 框架深度解析](./62-zeloo-framework-guide.md) | zeloo (hermes-desktop) 框架 / 结构 / 配置 / 二次开发指南 |
| 63 | [Zeloo 二次开发实操](./63-zeloo-dev-playbook.md) | 10 类常见修改场景 + 代码模板 + 调试技巧 + 测试与性能 |
| 64 | [Zeloo × Hermes Agent 界面借鉴对齐报告](./64-zeloo-hermes-alignment.md) | docs/58 借鉴清单 + 32 测试 + 双 TUI 模式 + SQLite WAL 持久化集成 |

---

## 核心设计原则

1. **循环保持简洁，能力通过组合扩展** — 核心 Loop 不超过 10 行，功能以工具/插件形式挂载
2. **按变化频率切分系统提示词** — 三层架构最大化 LLM prefix cache 命中率
3. **记忆与技能运行时可变，缓存层保持稳定** — 自进化不增加 token 成本
4. **安全左移** — 上下文文件注入前必须经过威胁扫描
5. **字节稳定性优先** — 可缓存的内容必须跨重建保持字节一致

---

## 技术栈

| 类别 | 选型 |
|------|------|
| 主语言 | Python 3.11+ |
| 包管理 | uv + pip |
| 数据库 | SQLite (WAL + FTS5) |
| 前端 | Node.js 22+ / pnpm (TUI / 桌面端) |
| LLM 接入 | OpenAI 兼容协议，支持 30+ Provider |
| 终端后端 | local / docker / ssh / modal / daytona / vercel_sandbox / singularity |

---

## 快速开始

```bash
# 克隆仓库
git clone <Zeloo-repo-url>
cd Zeloo

# 使用 uv 安装
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install -e .

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 LLM Provider 的 API Key

# 启动 CLI
Zeloo

# 常用子命令
Zeloo config show              # 查看完整配置
Zeloo config get model         # 读取配置项
Zeloo config set model gpt-4o  # 修改配置项（自动保存）
Zeloo doctor                   # 诊断依赖与配置
Zeloo status                   # 查看模型/平台状态
Zeloo sessions                 # 列出最近会话
Zeloo skills                   # 列出可用技能
Zeloo model                    # 查看当前模型
Zeloo backup -o ./backup.zip   # 备份 ~/.Zeloo 目录
```
