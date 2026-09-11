# 08. 目录结构与工程规范

## 8.1 项目目录结构

```
Zeloo/                              # 项目根目录（Zeloo AI Agent 运行时框架）
│
# ══════════════ 根目录配置文件 ══════════════
├── .coderabbit.yaml                 # CodeRabbit AI 代码审查配置
├── .dockerignore                   # Docker 构建忽略规则
├── .env.example                    # 环境变量示例（多供应商配置）
├── .envrc                          # direnv 环境变量自动加载（uv 虚拟环境 + 别名）
├── .gitattributes                  # Git 属性（LFS、换行符 EOL 规则：PS1=CRLF，sh=LF）
├── .gitignore                      # Git 忽略规则（.venv/node_modules/__pycache__ 等）
├── .npmrc                          # npm 配置
├── .nvmrc                          # Node.js 版本锁定
├── .prettierignore                # Prettier 格式化忽略文件
├── .prettierrc                    # Prettier 代码格式化配置
├── .python-version                # Python 版本锁定（3.12）
│
# ══════════════ 根目录文档与入口 ══════════════
├── AGENTS.md                       # AI 代理工作区约定（Agent 行为规范，项目级静态注入）
├── COMPAT_MANIFEST.md             # 兼容性清单（Python/OS/浏览器/数据库/终端后端）
├── CONTRIBUTING.md                # 贡献指南（开发流程/PR 规范/CI 检查）
├── Dockerfile                     # Docker 镜像构建（多阶段构建，Python 3.12 + uv）
├── LICENSE                       # MIT 开源许可证
├── README.md                      # 项目说明
├── README.zh-CN.md               # 项目说明（简体中文）
├── README.es.md                   # 项目说明（西班牙语）
├── SECURITY.md                    # 安全策略（漏洞报告/依赖审计/密钥管理）
├── SOUL.md                        # Agent 人格/身份设定文件（项目级静态注入）
│
│  ─── 注 ───
│  项目根目录的 AGENTS.md / SOUL.md 用于**开发本项目**的 Agent 行为约束，
│  通过 IDE/CI 静态注入。运行时的**用户工作区**使用
│  workspace/templates/ 中的同名 MD 作为初始化材料。
│  两者作用域不同，内容互补：根目录 = 开发规范，工作区模板 = 用户初始化。
│
# ══════════════ 核心源码文件 ══════════════
├── run_agent.py                   # AIAgent 核心类，驱动对话循环（37KB）
├── model_tools.py                  # 工具编排层（discover_and_filter_tools / execute_tool）
├── toolsets.py                    # 工具集定义（zeloo_CORE_TOOLS 列表）
├── cli.py                         # 交互式 CLI 主入口（Zeloo 命令，35KB）
├── utils.py                       # 通用工具函数集
├── security.py                    # 安全工具（输入清理/凭证脱敏/rate limiting）
├── acp_adapter.py                # ACP 适配器（IDE 集成协议）
├── mcp_serve.py                  # MCP Server（将工具暴露为 MCP 服务）
├── rl_cli.py                      # RL 训练 CLI（框架已实现，atropos 后端待接入）
├── mini_swe_runner.py             # SWE-bench 评测运行器
├── zeloo_state.py                # 状态管理顶层入口（SessionDB）
├── zeloo_state_messages.py       # 消息持久化扩展（FTS5 搜索）
├── zeloo_state_search.py         # 状态搜索功能（WAL + FTS5）
├── zeloo_state_repair.py        # 状态自修复（Schema 迁移 + 数据校验）
├── zeloo_state_schema.py         # 状态数据库 Schema（版本管理与迁移）
├── _diag_state.py                # 状态诊断工具
├── zeloo_constants.py           # 全局常量定义（3KB）
│
# ══════════════ zeloo_state 子系统（状态管理核心）══════════════
> 注：zeloo_state 分为两层架构：
> - **顶层文件**（`zeloo_state*.py`）— SessionDB 核心 API，快速导入入口
> - **子包**（`zeloo_state/`）— 扩展子系统（维护/修复/监控/FTS/读写分离）
> - 两者共存：顶层封装核心 SQLite 操作，子包提供高级功能。不合并以保持向后兼容。
│
├── zeloo_state/                  # 状态管理子系统（子包）
│   ├── __init__.py              # 导出 SessionDB / StateRepair / MaintenanceScheduler 等
│   ├── schema.py                # Schema 版本管理与迁移（TABLES / INDEXES / migrate）
│   ├── repair.py                # 数据库自诊断与修复（StateRepair / RepairIssue / Severity）
│   ├── maintenance.py           # 定时维护任务（MaintenanceScheduler / MaintenanceStats）
│   ├── errors.py                # 状态异常类型（ZelooStateError / MigrationError / RepairError）
│   ├── usage.py                 # Token 用量追踪（SQLite WAL）
│   ├── guard.py                 # 状态写锁（StateGuard — 防并发写入）
│   ├── readpool.py              # 只读连接池（ReadConnectionPool — 读写分离）
│   ├── registry.py              # 会话注册表（SessionRegistry）
│   ├── fts.py                  # FTS5 全文搜索封装（build_fts_index / search_fts / highlight_fts_result）
│   ├── gateway.py               # 网关状态聚合（GatewayStats / GatewayState）
│   ├── wal.py                   # WAL 模式细粒度控制
│   ├── messages.py             # 消息 CRUD（Message 数据类 + MessageStore）
│   ├── search.py               # 搜索门面（MessageSearch 重导出 + search_all / get_recent_sessions）
│   └── sessions.py             # 会话生命周期（归档/恢复/合并/统计，SessionManager）
│
# ══════════════ 工作区管理 ══════════════
├── workspace/                     # 工作区管理
│   ├── __init__.py
│   ├── manager.py              # WorkspaceManager + WORKSPACE_MD_FILES
│   ├── snapshot.py             # WorkspaceSnapshot + ArchiveMetadata
│   ├── importer.py             # WorkspaceBundle 跨机器迁移
│   └── templates/              # 8 个 MD 模板（自动加载到每个工作区）
│       ├── SOUL.md            # Agent 人格、身份、价值观
│       ├── AGENTS.md          # Agent 集群规则、权限
│       ├── USER.md            # 用户信息、偏好
│       ├── TOOLS.md           # 工具定义与权限策略
│       ├── IDENTITY.md       # 身份标识、运行时信息
│       ├── HEARTBEAT.md      # 后台心跳/定时任务清单
│       ├── BOOTSTRAP.md      # 启动引导 Prompt
│       └── MEMORY.md         # 长期记忆存储
│
# ══════════════ 依赖与构建配置 ══════════════
├── pyproject.toml               # Python 项目配置（精确版本锁定 ==X.Y.Z）
├── requirements.txt             # 依赖清单（pip 兼容）
├── uv.lock                     # uv 锁文件（精确依赖图）
├── config.yaml.example         # 配置示例（完整配置参考）
├── docker-compose.yml          # Docker Compose 编排（CLI/Gateway/TUI/Web 多服务）
│
# ══════════════ CI/CD 与 GitHub ══════════════
├── .github/
│   ├── ISSUE_TEMPLATE/          # Issue 模板（bug_report.yml / feature_request.yml）
│   ├── actions/                # 自定义 GitHub Actions（detect-changes / get-app-token / nix-setup）
│   ├── scripts/               # CI 辅助脚本（按需扩展）
│   ├── workflows/             # GitHub Actions 工作流（11 个）
│   │   ├── ci.yml            #   单元测试 + 集成测试
│   │   ├── pr-checks.yml     #   PR 检查（lint + test + coverage）
│   │   ├── security.yml      #   Bandit + Safety 漏洞扫描
│   │   ├── docker.yml        #   Docker 镜像构建 + Trivy + ghcr.io push
│   │   ├── release.yml       #   发布打包 + PyPI 发布
│   │   ├── docs.yml          #   文档站点构建 + GitHub Pages 部署
│   │   ├── perf-regression.yml  # 性能回归基准对比
│   │   ├── multi-platform.yml   #   跨平台测试（Ubuntu/macOS/Windows）
│   │   ├── lint.yml          #   Ruff 格式检查
│   │   ├── test.yml          #   单元测试 + coverage
│   │   └── typecheck.yml     #   mypy 类型检查
│   ├── actionlint.yaml        # GitHub Actions workflow 语法检查配置
│   ├── dependabot.yml         # 依赖自动更新机器人配置
│   └── PULL_REQUEST_TEMPLATE.md  # PR 模板
│
# ══════════════ 模型提供商适配层（Provider Router）══════════════
├── model_providers/              # 模型提供商适配层（统一 ABC + Registry 模式）
│   ├── __init__.py
│   ├── base.py                  # ModelProvider ABC + ModelResult dataclass
│   ├── registry.py              # register_provider / get_provider / list_providers
│   ├── deepseek.py             # DeepSeek API 适配器
│   ├── gemini.py               # Google Gemini API 适配器
│   ├── openrouter.py            # OpenRouter API 适配器（100+ 模型，OpenAI 兼容）
│   ├── anthropic.py             # Anthropic API 适配器（Claude 系列，system 消息分离）
│   └── xai.py                   # xAI Grok 适配器（OpenAI 兼容）
│
# ══════════════ Web 搜索/抓取提供商 ══════════════
├── web_providers/               # Web 搜索/抓取提供商
│   ├── __init__.py
│   ├── base.py                  # SearchProvider ABC + SearchResult/SearchResponse
│   ├── registry.py              # register_provider / get_provider / list_providers
│   ├── tavily.py               # Tavily API（需要 API Key）
│   ├── duckduckgo.py           # DuckDuckGo Instant Answer（无需 Key）
│   └── perplexity.py           # Perplexity API（带 fallback）
│
# ══════════════ 图片生成提供商 ══════════════
├── image_gen/                   # 图片生成提供商
│   ├── __init__.py
│   ├── base.py                  # ImageProvider ABC + ImageResult/ImageResponse + StrEnum
│   ├── registry.py              # register_provider / get_provider / list_providers
│   ├── fal.py                   # FAL Queue API
│   ├── dalle.py                 # OpenAI DALL-E 3
│   └── stability.py            # Stability AI（base64 返回）
│
# ══════════════ 视频生成提供商 ══════════════
├── video_gen/                   # 视频生成提供商
│   ├── __init__.py
│   ├── base.py                  # VideoProvider ABC + VideoResult/VideoResponse
│   ├── registry.py              # register_provider / get_provider / list_providers
│   ├── fal.py                   # FAL AI Video API
│   ├── deepinfra.py            # DeepInfra Video API
│   └── xai.py                  # xAI Video API
│
# ══════════════ 浏览器自动化提供商 ══════════════
├── browser/                     # 浏览器自动化提供商
│   ├── __init__.py
│   ├── base.py                  # BrowserProvider ABC + PageSnapshot/CrawlResult
│   ├── registry.py              # register_provider / get_provider / list_providers
│   ├── browserbase.py          # BrowserBase 云浏览器
│   └── firecrawl.py           # Firecrawl AI 爬虫
│
# ══════════════ MCP (Model Context Protocol) 核心 ══════════════
├── mcp/                         # MCP 核心
│   ├── __init__.py
│   ├── manager.py               # MCPManager — 发现/加载/重载/卸载 MCP 服务器
│   ├── stdio_client.py         # STDIO 模式 MCP 客户端
│   ├── http_client.py          # HTTP/SSE 模式 MCP 客户端
│   └── tool_filter.py           # MCP 工具过滤与转换
│
# ══════════════ 可选 MCP 服务器实现 ══════════════
│   ├── optional_mcps/               # 可选 MCP 服务器（按需启用，65 个 server 实现）
│   ├── __init__.py
│   ├── base.py                  # MCPServer ABC 基类
│   ├── server_registry.py       # 服务器注册表
│   ├── github.py               # GitHub MCP Server（Issues/PR/Code Search）
│   ├── gmail.py                # Gmail MCP Server（邮件读写）
│   ├── notion.py               # Notion MCP Server（页面/数据库）
│   ├── slack.py                # Slack MCP Server（消息/频道）
│   ├── jira.py                 # Jira MCP Server（Issue 管理）
│   ├── linear.py               # Linear MCP Server（Issue 管理）
│   ├── figma.py                # Figma MCP Server（文件/评论）
│   ├── vercel.py               # Vercel MCP Server（部署管理）
│   ├── supabase.py             # Supabase MCP Server（数据库）
│   ├── sentry.py               # Sentry MCP Server（错误追踪）
│   ├── stripe.py               # Stripe MCP Server（支付管理）
│   ├── datadog.py              # Datadog MCP Server（指标/告警）
│   ├── circleci.py             # CircleCI MCP Server（CI/CD）
│   ├── railway.py              # Railway MCP Server（部署）
│   └── ...                     # 持续扩展中
│
# ══════════════ Agent 核心引擎（200+ 模块）══════════════
├── agent/                       # ★ 核心代理引擎（仓库最核心目录）
│   ├── AGENTS.md               #   代理工作区指令
│   ├── __init__.py             #   包初始化
│   ├── system_prompt.py        #   三层 system prompt 组装（stable/context/volatile）
│   ├── conversation_loop.py    #   对话主循环（22KB，turn 控制/错误处理）
│   ├── prompt_builder.py       #   提示词构建器（8KB）
│   ├── skill_utils.py          #   技能工具函数
│   ├── memory_manager.py       #   记忆管理（短期/长期/技能记忆）
│   ├── turn_finalizer.py       #   回合收尾（自进化触发/压缩决策）
│   ├── background_review.py     #   后台复盘（自进化核心，9KB）
│   ├── runtime_cwd.py          #   运行时 cwd 解析
│   ├── credential_pool.py      #   凭证池管理（10KB，多 Key 轮询/熔断/限流）
│   ├── error_classifier.py     #   错误分类器（10KB，结构化错误分类）
│   ├── curator.py              #   技能生命周期管理（9KB，active→stale→archived）
│   ├── kanban.py               #   多智能体协作看板
│   ├── insights.py             #   运行时洞察与报告（9KB）
│   ├── i18n.py                #   国际化（当前 2 语言：en/zh-CN）
│   ├── estop.py                #   紧急停止机制（E-STOP 安全阀）
│   ├── oauth.py               #   OAuth 设备码授权（Codex/Nous）
│   ├── agent_init.py           #   Agent 初始化逻辑（9KB）
│   ├── audit_log.py            #   审计日志（操作记录/合规审计）
│   ├── audit_observability.py  #   审计可观测性桥接（ErrorObserver/AuditObserver）
│   ├── error_observability.py  #   错误可观测性桥接（可配置截断长度）
│   ├── error_tracker.py        #   错误追踪
│   ├── cost_tracker.py         #   成本追踪（token 用量估算）
│   ├── secret_scanner.py      #   凭证/密钥泄露扫描
│   ├── credential_crypto.py    #   凭证加密（AES-GCM）
│   ├── memory_providers.py     #   记忆后端（9 个实现：LocalFile/Honcho/Mem0 等）
│   ├── adaptive_compression.py #   自适应压缩（基于 token 预算）
│   ├── rate_limiter.py        #   速率限制器（Token Bucket 算法）
│   ├── context_breakdown.py   #   上下文断点分析（token 预算分配）
│   ├── context_engine.py      #   上下文引擎（消息管理/窗口控制）
│   ├── context_compressor.py  #   上下文压缩器（14KB，多策略压缩）
│   ├── conversation_compression.py  # 对话压缩（8KB，历史摘要）
│   ├── compression_facade.py #   压缩门面（多策略统一接口）
│   ├── skill_webhooks.py      #   技能 Webhook（生命周期通知）
│   ├── skill_hot_reload.py    #   技能热重载（watchdog 监控）
│   ├── provider_router.py     #   提供商路由（故障转移/负载均衡）
│   ├── chat_completion_helpers.py  # Chat Completion 辅助（10KB，消息转换）
│   ├── auxiliary_client.py     #   辅助 LLM 客户端
│   ├── client_lifecycle.py     #   客户端生命周期（9KB，start/stop/resume）
│   ├── agent_runtime_helpers.py  # Agent 运行时辅助（7KB）
│   ├── langfuse_integration.py  # Langfuse 可观测性集成
│   ├── zeloo_constants.py    #   全局常量定义
│   ├── agents_workflow/       #   多 Agent 工作流
│   │   ├── __init__.py
│   │   ├── coordinator.py    #   工作流协调器
│   │   └── pipeline.py       #   工作流 Pipeline
│   └── transports/            #   LLM API 传输层适配器
│       ├── __init__.py
│       ├── base.py            #   Transport ABC 基类
│       ├── anthropic_adapter.py  # Anthropic API 适配器（Claude 系列）
│       ├── bedrock_adapter.py  #   AWS Bedrock 适配器
│       ├── azure_identity_adapter.py  # Azure Identity 适配器
│       ├── gemini_native_adapter.py  # Gemini Native 适配器
│       └── codex_runtime.py   #   Codex Runtime 适配器
│
# ══════════════ 工具实现（@tool 装饰器自动注册）══════════════
├── tools/                       # 工具实现
│   ├── __init__.py
│   ├── base.py                # @tool 装饰器 + ToolRegistry + discover_builtin_tools
│   ├── registry.py            # 工具注册表核心
│   ├── shell_tool.py          # shell 命令执行（subprocess / 安全白名单）
│   ├── file_tools.py          # 文件读写/编辑/搜索（glob/regex/路径安全）
│   ├── web_tools.py          # web_search / web_fetch（httpx 封装）
│   ├── skills_tool.py         # skill_view / skill_manage（动态加载/生命周期）
│   ├── memory_tool.py        # memory / session_search（SQLite FTS5）
│   ├── kanban_tools.py       # kanban_create/list/show/assign/complete/heartbeat
│   ├── cron_tool.py          # cron_add/list/remove（定时任务管理）
│   ├── code_exec.py          # execute_code（沙箱 Python 执行，超时控制）
│   ├── todo_tools.py         # todo_add/list/complete/remove（JSON 持久化）
│   ├── voice_tool.py         # voice_tts / voice_stt（语音合成/识别）
│   ├── browser_tools.py      # 11 个 browser_* Playwright 工具
│   ├── image_tools.py        # image_generate（多提供者路由）
│   ├── delegate_tool.py      # delegate_task / clarify（子代理委托）
│   ├── workspace_tools.py    # workspace CLI 工具
│   ├── output_scan.py        # 工具输出扫描（凭证检测）
│   ├── path_safety.py       # 路径安全检查（路径穿越/符号链接）
│   ├── threat_patterns.py   # scan_for_threats（prompt 注入检测）
│   └── computer_use/        # Computer Use 工具集
│       ├── display.py       #   屏幕显示工具
│       ├── keyboard.py      #   键盘输入工具
│       ├── mouse.py         #   鼠标操作工具
│       ├── screenshot.py    #   截图工具
│       ├── scroll.py        #   滚动工具
│       ├── state_tracker.py  #   窗口状态追踪
│       └── window_manager.py #   窗口管理工具
│
# ══════════════ 消息网关（多平台统一接入）══════════════
├── gateway/                    # ★ 消息网关（5 个核心模块 + 18 个平台适配器）
│   ├── __init__.py
│   ├── run.py                #   网关运行时
│   ├── platform_registry.py  #   平台注册表
│   ├── session.py            #   会话管理
│   ├── voice.py             #   语音处理
│   ├── api_server.py         #   HTTP API Server
│   └── platforms/           #   平台适配器（18 个）
│       ├── __init__.py
│       ├── telegram.py       #   Telegram Bot
│       ├── discord.py        #   Discord Bot
│       ├── slack.py         #   Slack Bot
│       ├── whatsapp.py      #   WhatsApp
│       ├── signal.py        #   Signal
│       ├── feishu.py        #   飞书（Lark）
│       ├── dingtalk.py      #   钉钉
│       ├── wecom.py         #   企业微信
│       ├── teams.py         #   Microsoft Teams
│       ├── matrix.py        #   Matrix
│       ├── google_chat.py   #   Google Chat
│       ├── sms.py           #   SMS（Twilio）
│       ├── qqbot.py         #   QQ 机器人
│       ├── irc.py           #   IRC
│       ├── line.py          #   LINE
│       ├── mattermost.py    #   Mattermost
│       ├── home_assistant.py  # Home Assistant
│       ├── email_adapter.py  #   Email 邮件
│       └── webhook_base.py   #   Webhook 基类
│
# ══════════════ 终端后端（7 种实现）══════════════
├── terminal/                   # 终端后端（7 种实现，工厂模式）
│   ├── __init__.py           # create_backend() 工厂函数 + 全部导出
│   ├── base.py               # CommandResult dataclass + TerminalBackend Protocol
│   ├── local.py              # LocalTerminalBackend — subprocess 本地执行
│   ├── docker.py             # DockerTerminalBackend — 容器隔离执行
│   ├── ssh.py                # SSHTerminalBackend — paramiko SSH 远程
│   ├── modal.py              # ModalTerminalBackend — Modal 云 serverless
│   ├── singularity.py         # SingularityTerminalBackend — HPC 容器
│   ├── daytona.py            # DaytonaTerminalBackend — Daytona 云沙箱
│   └── vercel_sandbox.py    # VercelSandboxTerminalBackend — Vercel Functions
│
# ══════════════ Zeloo CLI 子命令系统 ═══════════════
├── zeloo_cli/                 # ★ CLI 子命令系统
│   ├── __init__.py
│   ├── config.py            # load_config() 配置加载（YAML 合并/环境变量）
│   ├── profiles.py           # Profile 管理（~/.Zeloo/profiles/<name>/）
│   ├── install.py           # 安装子命令
│   ├── deploy.py           # 部署子命令
│   ├── workspace_templates.py  # 工作区模板
│   ├── _startup_fast.py    # 快速启动（技能索引缓存 / LazyImporter / Provider 预热）
│   ├── observability/       # 可观测性
│   │   ├── __init__.py
│   │   ├── usage.py        #   UsageTracker（SQLite WAL + FTS5 token 用量追踪）
│   │   └── health.py       #   HealthChecker（5 项健康检查）
│   ├── dashboard_auth/      # 仪表盘认证
│   │   └── __init__.py    #   Basic / Nous / SelfHosted OAuth2 实现
│   ├── subcommands/        # 子命令模块
│   │   ├── __init__.py
│   │   ├── doctor.py       #   Zeloo doctor — 环境诊断
│   │   ├── install.py      #   Zeloo install — 安装工作流
│   │   ├── mcp.py          #   Zeloo mcp — MCP 管理
│   │   ├── model.py        #   Zeloo model — 模型配置
│   │   ├── session.py      #   Zeloo session — 会话管理
│   │   ├── tools.py        #   Zeloo tools — 工具管理
│   │   ├── update.py       #   Zeloo update — 更新检查
│   │   └── workspace.py    #   Zeloo workspace — 工作区管理
│   ├── web_routers/        # Web 路由
│   │   ├── __init__.py
│   │   ├── base.py        #   基础路由 + CORS + 中间件
│   │   ├── auth.py        #   AuthRouter（登录/注册/退出/Token 刷新）
│   │   ├── users.py       #   UsersRouter（用户 CRUD）
│   │   ├── sessions.py     #   SessionsRouter（会话管理）
│   │   └── settings.py    #   SettingsRouter（配置管理）
│   ├── AGENTS.md           # 工作区指令
│   └── (规划中)            # local_runtime/ / proxy/ / data/（尚未创建）
│
# ══════════════ 插件系统 ═══════════════
├── plugins/                   # ★ 插件系统（按需加载/生命周期钩子）
│   ├── __init__.py
│   ├── manager.py            # 插件发现与加载（PluginManager）
│   ├── hooks.py              # 生命周期钩子注册表
│   ├── browser_providers.py  # 浏览器提供商插件接入
│   └── example_plugin.py     # 示例插件
│   # 注：当前仅 4 个核心文件，详细分类见 plugins/ 各子目录
│
# ══════════════ 内置技能（14 个目录式 YAML 配置）══════════════
├── skills/                   # ★ 内置技能（14 个，目录式，YAML 配置）
│   ├── AGENTS.md
│   ├── caveman/            # 极简模式技能（最小化输出）
│   ├── caveman-commit/     # 简化 Git 提交
│   ├── caveman-compress/   # 压缩工具
│   ├── caveman-review/     # 代码审查
│   ├── code-review/        # 专业代码审查
│   ├── debugging/          # 调试技能
│   ├── file-todos/        # 文件级待办
│   ├── git-workflow/      # Git 工作流
│   ├── planning/          # 项目规划
│   ├── ponytail/          # 极简代码优化（YAGNI 7 层梯子）
│   ├── reflect/           # 反思技能
│   ├── rtk/              # RTK 命令行输出压缩
│   ├── simplifying-code/   # 简化代码
│   └── verification-before-completion/  # 完成前验证
│
# ══════════════ 国际化语言包 ═══════════════
├── locales/                 # 国际化语言包（当前 2 种：en/zh-CN）
│   ├── en.yaml              # 英语（默认）
│   └── zh-CN.yaml           # 简体中文
│   # 注：可按需添加更多语言，复制 en.yaml 为 <lang>.yaml 即可
│
# ══════════════ 可选技能 Python 模块 ═══════════════
├── optional_skills/              # ★ 可选技能 Python 模块（函数调用式技能）
│   ├── AGENTS.md
│   ├── __init__.py              # 导出所有技能函数
│   ├── skill_loader.py          # 技能发现与加载（SkillInfo / load_skill_index）
│   ├── software_development.py  # 软件开发技能（code_review / refactor / generate_tests）
│   ├── devops.py                # DevOps 技能（cicd_analysis / docker_diagnostics）
│   ├── data_science.py          # 数据科学技能（eda / feature_analysis）
│   ├── mlops.py                 # MLOps 技能
│   ├── research.py              # 研究辅助技能
│   └── security.py              # 安全技能（dependency_audit / secret_detection）
│
# ══════════════ 定时任务调度 ═══════════════
├── cron/                   # ★ 定时任务系统
│   ├── AGENTS.md
│   ├── __init__.py
│   └── scheduler.py       # CronScheduler（5 字段解析/守护线程）
│
# ══════════════ 数据生成与训练数据 ═══════════════
├── datagen/               # 数据生成与训练数据导出
│   ├── __init__.py
│   ├── compress_trajectories.py  # 轨迹压缩（头尾保留 + 中间摘要）
│   ├── extract_trajectories.py   # DB 轨迹导出为 ShareGPT JSONL
│   └── AGENTS.md
│
# ══════════════ 评测套件 ═══════════════
├── evals/                 # 评测脚本
│   ├── AGENTS.md
│   └── token_counting/    # Token 计数评测
│       ├── __init__.py
│       ├── counter.py     # tiktoken + char 混合计数
│       ├── cl100k.py     # cl100k_base 分词器
│       └── dataset.py    # 评测数据集
│   # （可扩展：browser_use/codebase_navigability/compaction 等）
│
# ══════════════ 工具脚本 ═══════════════
├── scripts/               # 工具脚本集
│   ├── batch_runner.py   # 批量执行 prompt，输出 JSONL（回归测试）
│   └── _install_repair.py  # 环境诊断与自动修复（5 项检查）
│
# ══════════════ 配置示例 ═══════════════
├── config-examples/       # 多场景配置示例
│   ├── minimal.yaml       # 最小 CLI 配置
│   ├── development.yaml   # 全功能开发配置
│   ├── gateway.yaml       # 多平台网关配置
│   ├── mcp-integration.yaml  # MCP 集成配置
│   └── cost-optimized.yaml  # 成本优化配置
│
├── environments/          # 多环境配置模板
│   ├── base.yaml         # 基础配置
│   ├── dev.yaml          # 开发环境
│   ├── test.yaml         # 测试环境
│   └── prod.yaml         # 生产环境
│
# ══════════════ Web 与文档站点 ═══════════════
├── landing/              # Web 落地页
│   └── index.html
│
├── tui_gateway/         # TUI 网关（terminal UI 入口，当前仅含 AGENTS.md）
├── website/             # Docusaurus 文档站点
│   ├── docs/           #   文档内容
│   │   ├── intro.md
│   │   ├── roadmap.md
│   │   ├── architecture/
│   │   │   └── overview.md
│   │   └── getting-started/
│   │       └── installation.md
│   ├── docusaurus.config.ts
│   ├── sidebars.ts
│   ├── README.md
│   └── package.json

# ══════════════ Nix 构建配置 ═══════════════
├── nix/                 # Nix 构建配置
│   ├── flake.nix       # Nix Flake 主入口
│   ├── flake.lock       # Nix Flake 锁文件（自动生成）
│   ├── Zeloo.nix      # Zeloo 包定义
│   ├── devShell.nix    # 开发 Shell
│   ├── shell.nix       # 兼容旧版 Nixpkgs 的开发 Shell
│   ├── checks.nix      # 检查配置
│   ├── desktop.nix     # NixOS 桌面服务（systemd.user）
│   ├── homeManagerModules.nix  # Home Manager 模块（profile/providers/observability）
│   └── configMergeScript.nix   # NixOS 配置合并（systemd 服务 + Hardening）
│
# ══════════════ 原生扩展 ═══════════════
├── native/              # 原生扩展
│   └── fts5_cjk/       # FTS5 中文分词扩展（含 Rust crate 源码）
│       ├── __init__.py  # Python 绑定
│       ├── Cargo.toml   # Rust 依赖配置
│       └── README.md
│
# ══════════════ 测试套件 ═══════════════
│   ├── tests/               # ★ 测试套件（76 测试文件，1033+ 测试用例）
│   ├── conftest.py          # pytest 全局 fixtures
│   ├── __init__.py
│   ├── unit/           # 单元测试（67 测试文件）
│   │   ├── test_system_prompt.py
│   │   ├── test_conversation_loop.py
│   │   ├── test_memory.py  # MemoryStore + memory/session_search（14 测试）
│   │   ├── test_code_exec_sandbox.py  # 沙箱加固（22 测试）
│   │   ├── test_threat_patterns.py  # prompt 注入检测（15 测试）
│   │   ├── test_file_tools.py  # 文件读写编辑
│   │   ├── test_shell_tool.py  # shell 命令安全白名单
│   │   ├── test_terminal_backends.py  # 7 种终端后端
│   │   ├── test_delegate_tool.py  # 子代理委托工具
│   │   ├── test_token_counting.py  # Token 计数评测
│   │   ├── test_web_fetch.py
│   │   ├── test_profiles.py
│   │   ├── test_smart_model_router.py
│   │   ├── test_auxiliary_client.py
│   │   ├── test_cli_helpers.py
│   │   ├── test_oauth.py  # OAuth 设备码流程
│   │   ├── test_batch_runner.py  # 批量执行器（9 测试）
│   │   ├── test_phase5.py  # cron/execute_code/todo/browser
│   │   ├── test_curator.py  # Curator 技能生命周期（5 测试）
│   │   ├── test_kanban.py  # 多智能体看板（6 测试）
│   │   ├── test_new_modules.py  # estop/i18n/insights/credential_pool（14 测试）
│   │   ├── test_china_platforms.py  # 飞书/钉钉/企微（10 测试）
│   │   ├── test_platforms_batch2.py  # Teams/Matrix/SMS/QQ 等（28 测试）
│   │   ├── test_memory_providers.py  # 9 个记忆后端（24 测试）
│   │   ├── test_web_providers.py  # web_providers 适配层（12 测试）
│   │   ├── test_image_gen.py  # image_gen 适配层（13 测试）
│   │   ├── test_browser.py  # browser 适配层（8 测试）
│   │   ├── test_output_scan.py  # 工具输出扫描
│   │   ├── test_path_safety.py  # 路径安全检查
│   │   ├── test_secret_scanner.py  # 凭证泄露扫描
│   │   ├── test_observability_bridges.py  # 可观测性桥接（27 测试）
│   │   ├── test_audit_observability.py  # 审计可观测性
│   │   ├── test_audit_log.py  # 审计日志
│   │   ├── test_background_review.py  # 后台复盘
│   │   ├── test_turn_finalizer.py  # 回合收尾
│   │   ├── test_context_engine_and_coordinator.py  # 上下文引擎
│   │   ├── test_cron_tool.py  # cron 工具
│   │   ├── test_skill_hot_reload.py  # 技能热重载
│   │   ├── test_skill_webhooks.py  # 技能 Webhook
│   │   ├── test_langfuse_integration.py  # Langfuse 集成
│   │   ├── test_transports.py  # 传输层适配器
│   │   ├── test_gateway.py  # 网关
│   │   ├── test_state_schema_repair.py  # 状态 Schema 修复
│   │   ├── test_messages_search.py  # 消息搜索
│   │   ├── test_tool_discovery.py  # 工具自动发现
│   │   ├── test_environments.py  # 环境配置
│   │   ├── test_agent_runtime_helpers.py  # Agent 运行时辅助
│   │   ├── test_install_repair.py  # _install_repair.py 诊断（9 测试）
│   │   ├── test_workspace_cli.py  # workspace 子命令（12 测试）
│   │   ├── test_optional_mcps.py  # 可选 MCP 服务器
│   │   ├── test_m8.py  # M8 验收
│   │   ├── test_skill_injection.py  # 技能注入
│   │   ├── test_security.py  # 安全模块
│   │   ├── test_config.py  # 配置加载
│   │   ├── test_skills_tool.py
│   │   ├── test_image_tools.py
│   │   ├── test_voice_tool.py
│   │   ├── test_vercel_mcp.py
│   │   ├── test_notion_mcp.py
│   │   ├── test_slack_mcp.py
│   │   ├── test_jira_mcp.py
│   │   ├── test_figma_mcp.py
│   │   ├── test_gmail_mcp.py
│   │   ├── test_supabase_mcp.py
│   │   ├── test_sentry_mcp.py
│   │   ├── test_stripe_mcp.py
│   │   ├── test_datadog_mcp.py
│   │   ├── test_circleci_mcp.py
│   │   ├── test_linear_mcp.py
│   │   └── test_railway_mcp.py
│   ├── integration/    # 集成测试
│   │   ├── __init__.py
│   │   ├── test_agent_pipeline.py  # Agent Pipeline（12 测试）
│   │   └── test_gateway_and_state.py  # 网关与状态（11 测试）
│   ├── e2e/           # 端到端测试
│   │   ├── __init__.py
│   │   └── test_agent_conversation.py  # Agent 对话全流程（6 测试）
│   └── perf/          # 性能测试
│       ├── __init__.py
│       ├── test_benchmarks.py  # 基准测试
│       └── test_concurrent.py  # 并发测试
│
# ══════════════ Docker 部署配置 ═══════════════
├── docker/             # Docker 部署配置
│   ├── config.docker.yaml  # Docker 环境专用配置
│   ├── SOUL.md       # 容器身份设定
│   ├── entrypoint-dispatch.sh  # 入口分发（CLI/Gateway/TUI）
│   ├── tini-shim.sh   # tini 进程垫片（PID 1 初始化）
│   ├── cont-init.d/
│   │   └── 01-setup.sh  # s6 第一阶段：创建目录/初始化配置
│   └── s6-rc.d/user/
│       ├── cron/run      # 定时任务服务
│       ├── gateway/run    # 网关服务
│       └── Zeloo/run    # 主 Agent 服务
│
# ══════════════ 项目文档 ═══════════════
└── docs/               # 开发文档（36 个文件）
    ├── README.md
    ├── 01-architecture.md
    ├── 02-system-prompt.md
    ├── 03-agent-loop.md
    ├── 04-tool-system.md
    ├── 05-memory-skills.md
    ├── 06-self-evolution.md
    ├── 07-platform-gateway.md
    ├── 08-project-structure.md  # 本文件
    ├── 09-browser.md
    ├── 10-roadmap.md
    ├── 11-core-modules.md
    ├── 12-cron-system.md
    ├── 13-oauth.md
    ├── 14-mcp-system.md
    ├── 15-datagen.md
    ├── 16-config-reference.md  # 30 个配置节
    ├── 17-session-state.md
    ├── 18-dev-plan-agent-modules.md
    ├── 19-dev-plan-Zeloo-cli.md
    ├── 20-dev-plan-plugins.md
    ├── 21-optional-skills.md
    ├── 22-Zeloo-state.md
    ├── 23-transports.md
    ├── 24-optional-mcps.md  # 16 个实现清单
    ├── 25-docker.md
    ├── 26-cicd.md
    ├── 27-native-extensions.md
    ├── 28-nix-build.md
    ├── 29-computer-use.md
    ├── 30-agents-workflow.md
    ├── 31-supabase-mcp.md
    ├── 32-security.md
    ├── 33-workspace.md
    ├── 34-terminal-backends.md
    ├── 35-delegate-tool.md
    └── 36-i18n-and-environments.md
```

### 8.1.1 Provider 适配层架构

model_providers / web_providers / image_gen / video_gen / browser 五个模块遵循统一的三层架构：

```
Provider ABC (base.py)
    ↓ 实现
Provider Impl (tavily.py / dalle.py / firecrawl.py ...)
    ↓ 注册
Registry (registry.py) — register_provider / get_provider / list_providers
    ↓ 消费
Agent / Tools — 通过 registry 获取 provider 实例
```

所有 Provider 均为可选依赖，通过 `HAS_<PROVIDER>` 或 try-import 检测实现优雅降级。

### 8.1.2 `zeloo_cli/profiles.py` — Profile 隔离

Profile 实现 `~/.Zeloo/profiles/<name>/` 的多配置隔离，每个 Profile 有独立的 config.yaml、skills/、memories/ 和 state.db：

```python
from zeloo_cli.profiles import get_profiles_root, get_profile_dir, set_profile_home

# ~/.Zeloo/profiles/
get_profiles_root()  # → Path("~/.Zeloo/profiles")

# ~/.Zeloo/profiles/work/
get_profile_dir("work")

# 激活 Profile（切换 zeloo_HOME）
set_profile_home("work")
```

Profile 目录结构：

```
~/.Zeloo/profiles/<name>/
├── config.yaml       # Profile 级配置（覆盖全局）
├── skills/           # 该 Profile 的技能
├── memories/         # 该 Profile 的记忆
├── trajectories/     # 该 Profile 的轨迹
└── state.db          # 该 Profile 的会话数据库
```

切换 Profile 后所有 Agent 运行时数据写入对应目录，实现完全隔离。

### 8.1.3 `cron/` — 定时任务调度

| 文件 | 职责 |
|------|------|
| `cron/scheduler.py` | CronScheduler 调度器（5 字段解析、守护线程 `_tick_loop`、`_parse_field`、`cron_matches`） |

详细 API 见 [docs/12-cron-system.md](./12-cron-system.md)。

### 8.1.4 `scripts/` — 工具脚本

| 脚本 | 用途 |
|------|------|
| `batch_runner.py` | 批量执行 prompt 并输出 JSONL，适合回归测试 |
| `_install_repair.py` | 环境诊断与自动修复（5 项检查 + 自动修复） |

**根目录独立脚本：**

| 脚本 | 用途 |
|------|------|
| `rl_cli.py` | RL 训练 CLI（框架已实现，atropos 后端待接入） |
| `mini_swe_runner.py` | 迷你 SWE-bench 评测运行器 |
| `run_agent.py` | 独立 Agent 运行入口 |
| `mcp_serve.py` | MCP 服务器（StdioServer 实现） |
| `security.py` | 安全工具（输入清理/凭证脱敏/rate limiting） |
| `toolsets.py` | 工具集注册与发现 |
| `model_tools.py` | 模型工具函数 |

**_install_repair.py 检测项：**

1. Python 版本（≥3.11）
2. 核心依赖（pydantic / httpx / openai / pytest / ruff）
3. API Key 环境变量
4. zeloo_HOME 路径有效性
5. Git 仓库状态

### 8.1.5 `agent/transports/` — LLM API 传输层

传输层将 AIAgent 与具体 LLM API 解耦，支持以下适配器：

| 适配器 | 支持平台 |
|--------|----------|
| `anthropic_adapter.py` | Anthropic（Claude 系列） |
| `bedrock_adapter.py` | AWS Bedrock |
| `azure_identity_adapter.py` | Azure OpenAI |
| `gemini_native_adapter.py` | Google Gemini Native |
| `codex_runtime.py` | OpenAI Codex Runtime |

### 8.1.6 `agent/agents_workflow/` — 多 Agent 工作流

| 文件 | 职责 |
|------|------|
| `coordinator.py` | 多 Agent 协作协调器 |
| `pipeline.py` | 工作流 Pipeline 定义与执行 |

### 8.1.7 `optional_mcps/` — 可选 MCP 服务器

按需启用，无需全部安装。每个 MCP Server 继承 `MCPServer` ABC，可通过配置按需加载：

| 服务器 | 功能 |
|--------|------|
| `github.py` | GitHub Issues / PR / Code Search |
| `gmail.py` | Gmail 邮件读写 |
| `notion.py` | Notion 页面与数据库 |
| `slack.py` | Slack 消息与频道 |
| `jira.py` | Jira Issue 管理 |
| `linear.py` | Linear Issue 管理 |
| `figma.py` | Figma 文件与评论 |
| `vercel.py` | Vercel 部署管理 |
| `supabase.py` | Supabase 数据库 |
| `sentry.py` | Sentry 错误追踪 |
| `stripe.py` | Stripe 支付管理 |
| `datadog.py` | Datadog 指标与告警 |
| `circleci.py` | CircleCI CI/CD |
| `railway.py` | Railway 部署 |

## 8.2 命名规范

### 8.2.1 文件命名

| 类型 | 规范 | 示例 |
|------|------|------|
| Python 模块 | `snake_case.py` | `system_prompt.py` |
| 配置文件 | `kebab-case.yaml` | `config.yaml` |
| 测试文件 | `test_<module>.py` | `test_system_prompt.py` |
| 技能目录 | `kebab-case/` | `git-workflow/` |
| MCP 服务器 | `<service>.py` | `github.py` |
| Provider 实现 | `<provider>.py` | `tavily.py` / `dalle.py` |

### 8.2.2 代码命名

| 类型 | 规范 | 示例 |
|------|------|------|
| 类 | `PascalCase` | `AIAgent`, `ToolRegistry`, `ModelProvider` |
| 函数/方法 | `snake_case` | `build_system_prompt()` |
| 常量 | `UPPER_SNAKE_CASE` | `DEFAULT_AGENT_IDENTITY` |
| 私有成员 | `_` 前缀 | `_cached_system_prompt` |
| 工具函数 | `_` 前缀（模块内） | `_join_tier()` |

### 8.2.3 工具命名

工具名使用 `snake_case`，简洁且表意：

```python
@tool(name="file_read", description="...")
@tool(name="skill_view", description="...")
@tool(name="delegate_task", description="...")
```

## 8.3 依赖管理

### 8.3.1 精确版本锁定

所有核心依赖使用精确版本锁定（`==X.Y.Z`），不接受版本范围：

```toml
# pyproject.toml
[project]
dependencies = [
    "openai==1.50.0",
    "httpx==0.27.2",
    "pydantic==2.9.2",
    "pyyaml==6.0.2",
    "rich==13.8.1",
]
```

**原因**：供应链安全，避免意外升级引入不兼容变更或恶意版本。

### 8.3.2 依赖分层

```
[project]
dependencies = [...]          # 核心运行时依赖

[project.optional-dependencies]
dev = ["pytest", "ruff", "mypy"]     # 开发依赖
gateway = ["python-telegram-bot", ...]  # 网关依赖
browser = ["playwright"]              # 浏览器依赖
```

### 8.3.3 供应链安全

- 定期运行 `pip-audit` 扫描已知漏洞
- `.env` 文件权限 `chmod 600`，与 `config.yaml` 分离
- 敏感信息只通过环境变量注入，不硬编码

## 8.4 配置管理

### 8.4.1 配置分层

```
~/.Zeloo/
├── config.yaml        # 用户级配置（不入库）
├── profiles/
│   └── <name>/
│       ├── config.yaml  # Profile 级配置
│       ├── skills/
│       ├── memories/
│       └── plugins/
└── state.db           # 会话数据库
```

优先级：命令行参数 > 环境变量 > profile config > 全局 config > 默认值

### 8.4.2 环境变量

```bash
# .env.example
zeloo_HOME=~/.Zeloo
zeloo_MODEL=claude-sonnet-4
zeloo_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

敏感信息**只**通过环境变量提供，`.env` 文件不入库。

### 8.4.3 配置热重载

- `config.yaml` 修改后，下次会话自动生效
- 运行中的会话不受影响（配置在会话开始时加载）
- MCP 服务器支持热重载（无需重启 gateway）

## 8.5 代码规范

### 8.5.1 类型注解

所有公共函数必须有类型注解：

```python
def build_system_prompt(agent: AIAgent, system_message: Optional[str] = None) -> str:
    ...
```

### 8.5.2 Docstring

公共函数必须有 docstring，说明用途、参数、返回值：

```python
def _scan_context_content(content: str, filename: str) -> str:
    """Scan context file content for injection. Returns sanitized content.

    Uses the "context" scope from the shared threat-pattern library.
    Content matching is BLOCKED because the file would otherwise enter
    the system prompt verbatim.
    """
```

### 8.5.3 错误处理

- 工具执行异常不中断循环，返回错误信息给 LLM
- 不可恢复错误抛出明确异常类型
- 所有异常记录日志（`logger.exception`）

### 8.5.4 Lint 与格式化

```toml
# pyproject.toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
strict = true
```

## 8.6 测试规范

### 8.6.1 测试分层

| 层级 | 说明 | 位置 |
|------|------|------|
| 单元测试 | 单个函数/类 | `tests/unit/` (67 文件) |
| 集成测试 | 多模块交互 | `tests/integration/` |
| 端到端测试 | 完整对话流程 | `tests/e2e/` |
| 性能测试 | 基准与并发 | `tests/perf/` |

### 8.6.2 Mock 策略

- LLM API 调用必须 mock
- 工具执行可 mock 或使用测试 fixture
- 文件操作使用 `tmp_path` fixture
- 环境变量使用 `monkeypatch.setenv`
- Windows 兼容：`pytest.skip` 处理平台特有功能

### 8.6.3 覆盖率要求

- 核心模块（system_prompt, conversation_loop）> 90%
- 工具模块 > 70%
- 网关模块 > 60%

### 8.6.4 当前测试覆盖（941 用例）

| 测试文件 | 覆盖模块 | 用例数 |
|----------|----------|--------|
| `test_memory.py` | MemoryStore + memory/session_search | 14 |
| `test_code_exec_sandbox.py` | execute_code 沙箱 | 22 |
| `test_threat_patterns.py` | prompt 注入检测 | 15 |
| `test_shell_tool.py` | shell 安全白名单 | 16 |
| `test_batch_runner.py` | 批量执行器 | 9 |
| `test_memory_providers.py` | 9 个记忆后端 | 24 |
| `test_web_providers.py` | web_providers 适配层 | 12 |
| `test_image_gen.py` | image_gen 适配层 | 13 |
| `test_browser.py` | browser 适配层 | 8 |
| `test_observability_bridges.py` | 可观测性桥接 | 27 |
| `test_curator.py` | Curator 技能生命周期 | 5 |
| `test_kanban.py` | 多智能体看板 | 6 |
| `test_new_modules.py` | estop/i18n/insights/credential_pool | 14 |
| `test_china_platforms.py` | 飞书/钉钉/企微 | 10 |
| `test_platforms_batch2.py` | Teams/Matrix/SMS/QQ 等 | 28 |
| `test_install_repair.py` | _install_repair.py 诊断 | 9 |
| `test_workspace_cli.py` | workspace 子命令 | 12 |
| `test_agent_pipeline.py`（integration） | Agent Pipeline | 12 |
| `test_gateway_and_state.py`（integration） | 网关与状态 | 11 |
| `test_agent_conversation.py`（e2e） | Agent 对话全流程 | 6 |

## 8.7 Git 工作流

### 8.7.1 分支策略

| 分支 | 用途 |
|------|------|
| `main` | 稳定发布分支 |
| `develop` | 开发集成分支 |
| `feature/<name>` | 功能开发 |
| `fix/<name>` | Bug 修复 |
| `release/<version>` | 发布准备 |

### 8.7.2 提交规范

遵循 Conventional Commits：

```
feat: add skill_manage patch action
fix: resolve system prompt cache invalidation
docs: update architecture overview
refactor: extract tool registry from run_agent
```

### 8.7.3 版本号

遵循 SemVer：`MAJOR.MINOR.PATCH`

- MAJOR：不兼容的 API 变更
- MINOR：向后兼容的功能新增
- PATCH：向后兼容的 Bug 修复
