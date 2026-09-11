# 16. 配置参考手册

## 16.1 概述

所有配置项在 `config.yaml`（项目级）或 `~/.Zeloo/config.yaml`（用户级）中设置。用户级优先于项目级。环境变量以 `${VAR_NAME}` 语法引用。

完整示例见 [`config.yaml.example`](./config.yaml.example)。

## 16.2 模型配置

```yaml
model: gpt-4o
provider: openai
temperature: 0.0
max_tokens: 4096
base_url: https://api.openai.com/v1   # OpenAI 兼容端点
api_key: ${OPENAI_API_KEY}
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model` | string | `gpt-4o` | 模型名称 |
| `provider` | string | `openai` | Provider 标识 |
| `temperature` | float | `0.0` | 采样温度 |
| `max_tokens` | int | `4096` | 最大输出 token |
| `base_url` | string | — | OpenAI 兼容端点 |
| `api_key` | string | — | API Key（支持 `${ENV_VAR}`） |

## 16.3 对话循环

```yaml
max_iterations: 90
iteration_budget: 100
budget_grace: true
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_iterations` | int | `90` | 工具调用迭代上限 |
| `iteration_budget` | int | `100` | 迭代预算（可超过 max_iterations） |
| `budget_grace` | bool | `true` | 预算耗尽后额外执行一次 |

## 16.4 终端后端

```yaml
terminal:
  backend: local      # local/docker/ssh/modal/daytona/vercel_sandbox/singularity
  timeout: 30
```

### 16.4.1 Docker 后端

```yaml
terminal:
  backend: docker
  image: python:3.12-slim
  container_name: Zeloo-sandbox
  volumes:
    "/data": "/workspace/data"
  working_dir: /workspace
```

### 16.4.2 SSH 后端

```yaml
terminal:
  backend: ssh
  host: example.com
  user: root
  port: 22
  key_file: ~/.ssh/id_rsa
  password: ${SSH_PASSWORD}
  connect_timeout: 10
```

### 16.4.3 Modal 后端

```yaml
terminal:
  backend: modal
  image: python:3.12-slim
  cpu: 2.0
  memory: 1024
  gpu: "T4"       # 可选：T4/A10G/A100
```

### 16.4.4 Daytona 后端

```yaml
terminal:
  backend: daytona
  api_url: https://app.daytona.io/api
  api_key: ${DAYTONA_API_KEY}
  image: ubuntu:22.04
```

### 16.4.5 Vercel Sandbox 后端

```yaml
terminal:
  backend: vercel_sandbox
  api_token: ${VERCEL_API_TOKEN}
  team_id: ${VERCEL_TEAM_ID}
```

## 16.5 语音后端

```yaml
voice:
  backend: openai    # console（无操作）或 openai
  # openai 后端参数
  tts_model: tts-1
  tts_voice: alloy    # alloy/echo/fable/onyx/nova/shimmer
  stt_model: whisper-1
```

## 16.6 网关配置

```yaml
gateway:
  session_idle_timeout: 3600   # 秒，超时释放 agent 实例
  eviction_interval: 300        # 秒，空闲回收检查间隔
  language: zh-CN             # i18n 语言（zh-CN / en）

  api:
    enabled: false
    host: 0.0.0.0
    port: 8080
    rate_limit_capacity: 60     # 每分钟最大请求数
    rate_limit_rate: 1.0
    auth_tokens:               # Bearer token 白名单
      - ${API_TOKEN}
```

## 16.7 消息平台配置

详见 [docs/07-platform-gateway.md](./07-platform-gateway.md) 平台适配器章节。

通用字段：

| 字段 | 说明 |
|------|------|
| `enabled` | 是否启用 |
| `token` | Bot/应用 Token |
| `allowed_users` | 白名单用户 ID 列表（空=允许所有） |

### 16.7.1 Telegram

```yaml
platforms:
  telegram:
    enabled: true
    token: ${TELEGRAM_BOT_TOKEN}
    allowed_users: []
```

### 16.7.2 飞书

```yaml
platforms:
  feishu:
    enabled: true
    app_id: ${FEISHU_APP_ID}
    app_secret: ${FEISHU_APP_SECRET}
    bot_name: Zeloo
```

### 16.7.3 钉钉

```yaml
platforms:
  dingtalk:
    enabled: true
    client_id: ${DINGTALK_CLIENT_ID}
    client_secret: ${DINGTALK_CLIENT_SECRET}
```

### 16.7.4 企业微信

```yaml
platforms:
  wecom:
    enabled: true
    corp_id: ${WECOM_CORP_ID}
    corp_secret: ${WECOM_CORP_SECRET}
    agent_id: ${WECOM_AGENT_ID}
```

## 16.8 记忆后端

```yaml
memory:
  provider: local      # local/honcho/mem0/supermemory/openviking/byterover/hindsight/holographic/retaindb
  max_chars: 8000
```

各后端额外参数：

```yaml
memory:
  provider: mem0
  api_key: ${MEM0_API_KEY}
  user_id: user_001

memory:
  provider: supermemory
  api_key: ${SUPERMEMORY_API_KEY}
  base_url: https://api.supermemory.ai
```

## 16.9 技能配置

```yaml
skills:
  enabled: true
  auto_update: true          # 自动检测 skills/ 目录变化
  auto_activate_on_call: true  # 调用时自动激活
  curator_enabled: true      # 启用 Curator 生命周期管理
```

## 16.10 Curator 配置

```yaml
curator:
  enabled: true
  stale_after_days: 30        # N 天未使用 → stale
  archive_after_days: 90      # M 天仍未使用 → archived
  skills_dir: ~/.Zeloo/skills
```

## 16.11 Kanban 配置

```yaml
kanban:
  enabled: true
  zombie_timeout_seconds: 300  # 无心跳超过此时间 → 僵尸回收
  default_max_retries: 3
```

## 16.12 MCP 配置

```yaml
mcp:
  servers:
    - name: filesystem
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
    - name: memory
      transport: http
      url: https://mcp.example.com/sse
      headers:
        Authorization: "Bearer ${MCP_TOKEN}"
```

## 16.13 OAuth 配置

```yaml
oauth:
  providers:
    codex:
      authorization_url: https://auth.openai.com/authorize
      token_url: https://auth.openai.com/oauth/token
      client_id: auth0-openai-client
      scope: "openid profile email offline_access"
      audience: https://api.openai.com/v1
    nous:
      authorization_url: https://nousresearch.auth0.com/oauth/device/code
      token_url: https://nousresearch.auth0.com/oauth/token
      client_id: nous-cli
      scope: offline_access
```

## 16.14 Profile 隔离

```yaml
profiles:
  default:
    model: gpt-4o
    provider: openai
    toolsets: [web, terminal, file, browser, code_execution, delegation, skills, memory, todo, mcp, cron, voice]
  code_reviewer:
    model: gpt-4o
    provider: openai
    toolsets: [file, code_execution, terminal, web]
  data_scientist:
    model: gpt-4o
    provider: openai
    toolsets: [file, code_execution, terminal, web, data]

user_profiles:
  "user_123": code_reviewer
  "user_456": data_scientist
```

## 16.15 插件配置

```yaml
plugins:
  enabled: true
  dirs:
    - "~/.Zeloo/plugins"
    - "./plugins"
```

## 16.16 Insights 配置

```yaml
insights:
  enabled: true
  report_interval: 3600   # 自动报告间隔（秒）
  top_n_tools: 10         # 报告中显示前 N 工具
```

## 16.17 安全配置

```yaml
security:
  allowed_tools: [file_read, file_edit, web_search, web_fetch, shell]
  dangerous_tools: [execute_code, file_write, shell]
  require_approval_for:
    - file_write
    - shell
  max_file_size_kb: 10240
  sandbox_network: false   # code_exec 是否允许网络
```

## 16.18 成本与用量追踪

```yaml
cost_tracker:
  enabled: true
  warn_threshold_usd: 10.0     # 单会话警告阈值（触发 warn callback + 日志）
  abort_threshold_usd: 100.0   # 单会话中止阈值（触发 abort callback + 抛出 CostLimitExceeded）
  persist: true               # 持久化到 ~/.Zeloo/usage.db

# 也可通过环境变量覆盖：zeloo_COST_WARN_THRESHOLD / zeloo_COST_ABORT_THRESHOLD
# 代码中使用 register_warn_callback() / register_abort_callback() 注册回调
# 或通过 CostTracker.warn_threshold_usd / abort_threshold_usd 属性在运行时调整阈值

usage_tracking:
  provider: sqlite             # sqlite / jsonl
  db_path: ~/.Zeloo/usage.db
  retention_days: 90           # 保留天数（超出清理）
```

## 16.19 Observability（Langfuse 集成）

```yaml
observability:
  enabled: false
  provider: langfuse          # langfuse / custom
  langfuse:
    public_key: ${LANGFUSE_PUBLIC_KEY}
    secret_key: ${LANGFUSE_SECRET_KEY}
    host: https://cloud.langfuse.com
  sampling_rate: 1.0          # 0.0~1.0
  stack_trace_max_chars: 1000 # 错误追踪最大字符
```

## 16.20 Cron 调度配置

```yaml
cron:
  enabled: true
  max_concurrent_jobs: 10
  history_retention_days: 30
  jobs:
    - name: cleanup_old_logs
      schedule: "0 3 * * *"        # 每天 3:00
      command: "rm -rf /var/log/*.gz"
      on_failure: notify
```

## 16.21 工作区配置

```yaml
workspace:
  home: ~/.Zeloo/workspace
  active: default
  auto_snapshot_on_delete: true   # 删除前自动快照
  max_workspaces: 20
  archive:
    format: tar.gz                # tar.gz
    compression_level: 6
```

## 16.22 子代理委托配置

```yaml
delegation:
  max_concurrent: 3               # 最大并发子 Agent 数
  default_timeout_seconds: 300    # 默认超时
  default_role: leaf              # leaf / orchestrator
  max_nested_depth: 2             # 嵌套深度上限
  model_overrides:
    complex: gpt-4o
    simple: gpt-4o-mini
```

## 16.23 多模态 Provider 配置

### 16.23.1 图片生成

```yaml
image_gen:
  default_provider: dalle        # dalle / fal / stability
  dalle:
    model: dall-e-3
    size: 1024x1024
    quality: standard
  fal:
    api_key: ${FAL_KEY}
    model: fal-ai/flux-pro
```

### 16.23.2 视频生成

```yaml
video_gen:
  default_provider: fal          # fal / deepinfra / xai
  fal:
    api_key: ${FAL_KEY}
    model: fal-ai/wan-t2v
```

### 16.23.3 浏览器自动化

```yaml
browser:
  default_provider: browserbase  # browserbase / firecrawl
  browserbase:
    api_key: ${BROWSERBASE_API_KEY}
    project_id: ${BROWSERBASE_PROJECT_ID}
  firecrawl:
    api_key: ${FIRECRAWL_API_KEY}
```

### 16.23.4 Web 搜索

```yaml
web_providers:
  default: tavily                # tavily / duckduckgo / perplexity
  tavily:
    api_key: ${TAVILY_API_KEY}
    max_results: 10
  duckduckgo: {}                 # 无需 API Key
```

## 16.24 Computer Use 配置

```yaml
computer_use:
  enabled: false                 # 需要图形界面
  default_backend: x11           # x11 / wayland / windows
  display: :0
  screenshot_dir: ~/.Zeloo/screenshots
  max_idle_seconds: 60
```

## 16.25 评测配置

```yaml
evals:
  token_counting:
    enabled: true
    model: gpt-4o
    datasets: [default, short, long_context]
    output_path: ~/.Zeloo/evals/token_counting
```

## 16.26 国际化配置

```yaml
locale: zh-CN                    # zh-CN / en
i18n:
  fallback_locale: en
  reload_on_change: false
```

## 16.27 环境配置

```bash
# 通过 zeloo_ENV 激活环境（详见 docs/36）
zeloo_ENV=dev uv run Zeloo run
zeloo_ENV=prod uv run Zeloo gateway
```

环境文件位于 `environments/`，按 base/dev/test/prod 分层覆盖。

## 16.28 Zeloo State 配置

```yaml
zeloo_state:
  db_path: ~/.Zeloo/state.db
  wal_enabled: true              # 启用 WAL 模式
  fts_enabled: true              # 启用 FTS5 全文搜索
  read_pool_size: 5              # 只读连接池大小
  guard_timeout_seconds: 30      # 写锁等待超时
  maintenance:
    enabled: true
    vacuum_interval_hours: 168   # 每周清理一次
    wal_checkpoint_interval_hours: 6
  repair:
    auto_on_startup: true        # 启动时自动修复
    max_repair_attempts: 3
```

## 16.29 完整配置示例

完整的端到端配置示例：

```yaml
# ~/.Zeloo/config.yaml
provider: openai
model: gpt-4o
temperature: 0.0
max_tokens: 4096
max_iterations: 90

terminal:
  backend: local
  timeout: 30

memory:
  provider: localfile
  max_chars: 8000

mcp:
  servers:
    - github
    - notion

cost_tracker:
  enabled: true
  warn_threshold_usd: 10.0     # 警告阈值（触发 warn callback + 日志）
  abort_threshold_usd: 100.0   # 中止阈值（触发 abort callback + CostLimitExceeded）
  # 也可通过环境变量：zeloo_COST_WARN_THRESHOLD / zeloo_COST_ABORT_THRESHOLD

observability:
  enabled: false

cron:
  enabled: true

workspace:
  active: default

locale: zh-CN
```

## 16.30 配置验证

```bash
# 验证配置语法
Zeloo config validate

# 查看完整解析后配置
Zeloo config show

# 查看配置项
Zeloo config get memory.provider

# 修改配置（自动保存）
Zeloo config set model gpt-4o-mini
```
