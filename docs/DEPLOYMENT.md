# Zeloo 部署配置与使用文档

> **版本**：0.16.0 — The Surface Release
> **最后更新**：2026-09-11
> **覆盖范围**：从本地开发到生产 K8s 集群的全场景部署指南

---

## 目录

1. [快速开始](#1-快速开始)
2. [安装方式](#2-安装方式)
3. [配置体系](#3-配置体系)
4. [环境配置详解](#4-环境配置详解)
5. [CLI 子命令参考](#5-cli-子命令参考)
6. [服务部署](#6-服务部署)
7. [容器化部署](#7-容器化部署)
8. [Kubernetes 部署](#8-kubernetes-部署)
9. [Helm Chart 部署](#9-helm-chart-部署)
10. [系统服务](#10-系统服务)
11. [CI/CD 集成](#11-cicd-集成)
12. [安全加固](#12-安全加固)
13. [备份与恢复](#13-备份与恢复)
14. [故障排查](#14-故障排查)

---

## 1. 快速开始

### 1.1 极简安装（pip / uv）

```bash
# pip
pip install zeloo==0.16.0

# uv（推荐，更快）
uv pip install zeloo==0.16.0

# 验证安装
zeloo --version
# 输出: Zeloo 0.16.0  —  The Surface Release
```

### 1.2 首次配置

```bash
# 交互式配置向导（推荐首次使用）
zeloo setup

# 或手动初始化
zeloo init --provider openai --model gpt-4o

# 设置 API Key（任选一种）
zeloo auth openai  # 交互式输入
export OPENAI_API_KEY=sk-...  # 环境变量
```

### 1.3 启动使用

```bash
# 交互式对话
zeloo chat

# TUI 界面
zeloo tui

# 单次查询
zeloo chat --query "解释一下什么是 RESTful API"

# Oneshot 快速模式
zeloo z "what is 2+2?"
```

---

## 2. 安装方式

Zeloo 支持 **8 种安装渠道**，覆盖所有主流平台：

| 安装方式 | 命令 | 适用场景 |
|---|---|---|
| **pip / uv** | `pip install zeloo` | 开发者、Python 环境 |
| **Homebrew** | `brew install zeloo` | macOS / Linux |
| **winget** | `winget install zeloo.zeloo` | Windows |
| **Debian (.deb)** | `dpkg -i zeloo_0.16.0_amd64.deb` | Debian / Ubuntu |
| **RPM (.rpm)** | `rpm -i zeloo-0.16.0-1.x86_64.rpm` | RHEL / Fedora |
| **Snap** | `snap install zeloo` | Ubuntu Snap 环境 |
| **Arch AUR** | `yay -S zeloo` | Arch Linux |
| **PowerShell** | `irm https://zeloo.io/install.ps1 \| iex` | Windows（无 Python）|

### 2.1 详细安装步骤

#### pip / uv（通用）

```bash
# 创建虚拟环境（推荐）
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .\.venv\Scripts\activate  # Windows

# 安装
pip install zeloo==0.16.0

# 或使用 uv（需要先安装 uv）
# pip install uv
# uv pip install zeloo==0.16.0
```

#### Homebrew（macOS / Linux）

```bash
# 添加源
brew tap zeloo/tap

# 安装
brew install zeloo

# 更新
brew upgrade zeloo
```

#### winget（Windows）

```powershell
# PowerShell 7+
winget install zeloo.zeloo

# 更新
winget upgrade zeloo.zeloo
```

#### Debian / Ubuntu

```bash
# 下载 deb 包
wget https://github.com/zeloo/zeloo/releases/download/v0.16.0/zeloo_0.16.0_amd64.deb

# 安装
sudo dpkg -i zeloo_0.16.0_amd64.deb
sudo apt-get install -f  # 自动解决依赖

# 验证
zeloo --version
```

#### RPM（RHEL / Fedora / CentOS）

```bash
# 下载 rpm 包
sudo rpm -i zeloo-0.16.0-1.x86_64.rpm

# 验证
zeloo --version
```

#### Arch Linux（AUR）

```bash
# 使用 yay 或其他 AUR helper
yay -S zeloo

# 或手动编译
git clone https://aur.archlinux.org/zeloo.git
cd zeloo
makepkg -si
```

#### Snap（Ubuntu）

```bash
# 安装
sudo snap install zeloo

# 赋予必要权限
sudo snap connect zeloo:dot-zeloo          # 配置文件
sudo snap connect zeloo:network            # 网络访问
sudo snap connect zeloo:ssh-keys           # SSH 密钥

# 验证
zeloo --version
```

#### Windows PowerShell（无需 Python）

```powershell
# 以管理员身份运行 PowerShell
irm https://zeloo.io/install.ps1 | iex

# 验证
zeloo --version
```

---

## 3. 配置体系

### 3.1 配置文件位置

Zeloo 按以下优先级加载配置（前者优先）：

| 优先级 | 路径 | 说明 |
|---|---|---|
| 1 | 命令行 `--config` 参数 | 显式指定配置文件 |
| 2 | `ZELOO_CONFIG` 环境变量 | 环境变量指定 |
| 3 | `./config.yaml` | 当前目录（项目级）|
| 4 | `~/.zeloo/config.yaml` | 用户主目录（用户级）|
| 5 | `/etc/zeloo/config.yaml` | 系统级（Linux）|

### 3.2 配置文件格式

Zeloo 使用 **YAML** 格式，支持环境变量插值 `${VAR_NAME}`：

```yaml
# 最小配置示例
llm:
  default_provider: openai
  default_model: gpt-4o
  providers:
    openai:
      enabled: true
      api_key: ${OPENAI_API_KEY}
```

### 3.3 多环境配置

Zeloo 内置 3 套开箱即用的环境配置：

```bash
# 设置环境（自动加载对应配置）
export ZELOO_ENV=development   # 开发：DEBUG 日志，所有功能开启
export ZELOO_ENV=production    # 生产：WARNING 日志，安全加固
export ZELOO_ENV=ci            # CI：INFO 日志，mock provider

# 或手动指定
zeloo chat --config config_examples/production.yaml
```

**环境配置差异对照**：

| 维度 | development | production | ci |
|---|---|---|---|
| 日志级别 | DEBUG | WARNING | INFO |
| LLM Provider | 全部开启 | 仅核心 3 个 | mock |
| 记忆后端 | local（内存）| Redis | SQLite |
| 浏览器 | 有头模式 | 无头模式 | 无头模式 |
| 熔断器 | 禁用 | 启用 | 启用（快速失败）|
| 安全检查 | 宽松 | 严格 | 基础 |
| Vault | 禁用 | 启用 | 禁用 |
| 遥测采样 | 100% | 10% | 禁用 |
| 最大迭代 | 50 | 10 | 5 |
| Gateway Auth | 禁用 | 启用 TLS+Token | 禁用 |

### 3.4 .env 环境变量

在 `~/.zeloo/.env`（或项目根目录 `.env`）配置敏感信息：

```bash
# 复制模板
cp .env.example ~/.zeloo/.env

# 编辑配置
vim ~/.zeloo/.env
```

关键环境变量：

```bash
# ==================== LLM Provider ====================
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
DEEPSEEK_API_KEY=sk-...
GROQ_API_KEY=gsk_...

# ==================== Zeloo 配置 ====================
ZELOO_HOME=~/.Zeloo
ZELOO_MODEL=gpt-4o
ZELOO_PROVIDER=openai
ZELOO_ENV=development

# ==================== 成本控制 ====================
ZELOO_COST_WARN_THRESHOLD=10.0    # 警告阈值（USD）
ZELOO_COST_ABORT_THRESHOLD=100.0  # 中止阈值（USD）

# ==================== 终端后端 ====================
TERMINAL_BACKEND=local            # local / docker / ssh
DOCKER_IMAGE=python:3.12-slim

# ==================== 安全策略 ====================
# allow / deny / confirm
ZELOO_DANGEROUS_POLICY=confirm

# ==================== 离线模式 ====================
ZELOO_OFFLINE=0                   # 1=禁用所有网络
```

---

## 4. 环境配置详解

### 4.1 LLM Provider 配置

Zeloo 支持 **14 个 LLM Provider**，可同时启用多个并设置故障转移：

```yaml
llm:
  default_provider: anthropic
  default_model: claude-3-5-sonnet-20241022
  fallback_chain:
    - provider: openai
      model: gpt-4o
    - provider: deepseek
      model: deepseek-chat

  providers:
    anthropic:
      enabled: true
      api_key: ${ANTHROPIC_API_KEY}
      max_retries: 3
      timeout: 300

    openai:
      enabled: true
      api_key: ${OPENAI_API_KEY}
      base_url: https://api.openai.com/v1

    deepseek:
      enabled: true
      api_key: ${DEEPSEEK_API_KEY}
      base_url: https://api.deepseek.com

    groq:
      enabled: true
      api_key: ${GROQ_API_KEY}
      base_url: https://api.groq.com/openai/v1

    ollama:
      enabled: false
      base_url: http://localhost:11434

    local:
      enabled: false
      base_url: http://localhost:8000/v1

    azure:
      enabled: false
      api_key: ${AZURE_OPENAI_API_KEY}
      endpoint: ${AZURE_OPENAI_ENDPOINT}
      deployment: ${AZURE_OPENAI_DEPLOYMENT}

    bedrock:
      enabled: false
      region: us-east-1
      # 使用 AWS credentials chain（环境变量 / IAM Role / config file）

    fireworks:
      enabled: false
      api_key: ${FIREWORKS_API_KEY}

    together:
      enabled: false
      api_key: ${TOGETHER_API_KEY}
```

### 4.2 Agent 配置

```yaml
agent:
  max_iterations: 50          # 单次任务最大迭代次数
  temperature: 0.7            # 生成温度（0-1）
  timeout_seconds: 120        # 整体超时
  step_timeout_seconds: 60    # 单步超时
  keep_full_trace: true       # 保留完整执行 trace

  # 熔断器（防止 Provider 故障时持续重试）
  circuit_breaker:
    enabled: true
    failure_threshold: 5       # 连续失败 N 次后熔断
    reset_timeout_seconds: 60  # 熔断后 60s 尝试恢复

  # 自适应压缩（上下文超长时自动压缩）
  context:
    compression:
      enabled: true
      trigger_tokens: 80000
      strategy: summarize_then_truncate

  # 成本优化
  cost_optimizer:
    enabled: true
    warn_threshold: 10.0
    abort_threshold: 100.0
```

### 4.3 Memory 配置

```yaml
memory:
  backend: local              # local / sqlite / redis / postgres
  max_chars: 16000            # 单会话最大字符数

  # SQLite 配置
  sqlite:
    path: ~/.Zeloo/memory.db

  # Redis 配置（生产推荐）
  redis:
    url: ${REDIS_URL}
    ttl: 3600

  # 自动归档
  auto_archive:
    enabled: true
    archive_threshold: 2x     # 超过 max_chars 的 2 倍时归档
    archive_path: ~/.Zeloo/archive/

  # 记忆整理
  curator:
    enabled: true
    auto_curate: true
    curate_interval_minutes: 60
    retention_days: 90
```

### 4.4 Gateway 配置

```yaml
gateway:
  enabled: true
  api:
    host: 0.0.0.0             # 监听地址
    port: 9113                # 监听端口
    rate_limit_capacity: 60   # 速率限制容量
    rate_limit_rate: 1.0      # 速率限制速率（请求/秒）
    auth_tokens:              # Bearer Token 认证
      - ${ZELOO_API_KEY}
    # TLS 配置（生产必须）
    tls:
      enabled: false          # 生产改为 true
      cert_file: /path/to/cert.pem
      key_file: /path/to/key.pem
    # CORS 配置
    cors:
      allowed_origins:
        - https://example.com
      allowed_methods:
        - GET
        - POST
      allowed_headers:
        - Authorization
        - Content-Type

  session:
    idle_timeout: 3600        # 空闲会话超时（秒）
    eviction_interval: 300    # 会话回收检查间隔（秒）

  # 平台集成（钉钉/飞书/企业微信/Slack 等）
  platforms:
    telegram:
      enabled: false
      bot_token: ${TELEGRAM_BOT_TOKEN}
    discord:
      enabled: false
      bot_token: ${DISCORD_BOT_TOKEN}
```

### 4.5 MCP 配置

```yaml
mcp:
  # 启用 MCP 服务器
  servers:
    # 文件系统 MCP
    - name: filesystem
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
      enabled: true

    # Git MCP
    - name: git
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-git", "--repository", "."]
      enabled: true

    # GitHub MCP
    - name: github
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: ${GITHUB_TOKEN}
      enabled: false

    # PostgreSQL MCP
    - name: postgres
      transport: stdio
      command: python
      args: ["-m", "mcp_servers.postgres"]
      env:
        POSTGRES_HOST: ${POSTGRES_HOST}
        POSTGRES_PORT: ${POSTGRES_PORT}
        POSTGRES_DB: ${POSTGRES_DB}
        POSTGRES_USER: ${POSTGRES_USER}
        POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      enabled: false

  # 自动发现（扫描 npm/pip 全局安装的 MCP）
  auto_discovery:
    enabled: true
    scan_sources:
      - npm_global
      - pip_global

  # OAuth 配置（MCP 服务器认证）
  oauth:
    enabled: true
    encrypt_tokens: true
    token_rotation_buffer_seconds: 60
```

### 4.6 Browser 配置

```yaml
browser:
  headless: false             # 开发用有头，生产用无头
  timeout: 60000              # 页面加载超时（毫秒）
  save_screenshots: true      # 是否保存截图
  screenshot_dir: ~/.Zeloo/screenshots
  max_concurrent: 5           # 最大并发浏览器数

  # 云端浏览器（可选，高并发场景）
  cloud:
    provider: browserless     # browserless / browserbase / steel
    api_key: ${BROWSERLESS_API_KEY}
    endpoint: https://chrome.browserless.io

  # 视觉理解（截图 + AI 分析）
  vision:
    enabled: true
    model: gpt-4o
    detect_captcha: true
```

### 4.7 Security 配置

```yaml
security:
  sanitize_input: true        # 输入净化
  validate_output: true       # 输出验证
  threat_scan: true           # 威胁扫描
  rate_limit: true            # 速率限制
  output_scan_strict: true    # 输出严格模式（检测密钥泄露）

  # 危险工具策略
  dangerous_policy: confirm   # allow / deny / confirm
  dangerous_tools:
    - shell
    - file_write
    - execute_code
    - delegate_task

  # 输出扫描规则
  output_scan:
    patterns:
      - api[_-]?key
      - secret
      - password
      - token
      - private[_-]?key
    action: redact            # redact / block / warn

# Vault 配置（生产推荐）
vault:
  enabled: false              # 生产改为 true
  url: ${VAULT_URL}
  token: ${VAULT_TOKEN}
  mount_point: secret
  rotation_interval_hours: 24
```

---

## 5. CLI 子命令参考

### 5.1 核心命令

```bash
# 对话与交互
zeloo chat                        # 交互式对话
zeloo chat --query "问题"         # 单次查询
zeloo chat --resume latest        # 恢复会话
zeloo chat --continue             # 继续上次对话

zeloo tui                         # 启动 TUI 界面
zeloo z "问题"                    # Oneshot 快速模式

# 服务
zeloo gateway                     # 启动 Gateway API
zeloo gateway foreground          # 前台运行（systemd 用）
zeloo serve                       # 启动 HTTP API 服务
zeloo serve --port 8000           # 指定端口
zeloo serve --workers 4           # 多 worker

# 配置
zeloo setup                       # 交互式配置向导
zeloo init --provider openai      # 初始化配置
zeloo config                      # 查看配置
zeloo config set model gpt-4o     # 修改配置
zeloo config --editor             # 编辑配置文件

# 模型
zeloo model                       # 查看可用模型
zeloo model list                  # 列出所有模型
zeloo model set anthropic         # 切换 provider
```

### 5.2 认证与 Provider

```bash
# 认证
zeloo auth                        # 查看当前认证状态
zeloo auth openai                 # 交互式认证 OpenAI
zeloo auth anthropic              # 交互式认证 Anthropic
zeloo auth list                   # 列出所有 provider 认证状态

# 远端执行
zeloo run "问题"                  # 本地执行
zeloo run --remote https://...    # 远端 Gateway 执行
zeloo run --check                 # 检查远端连接

# 登出
zeloo logout                      # 登出当前 provider
zeloo logout --all                # 清除所有认证
```

### 5.3 记忆与会话

```bash
# 记忆管理
zeloo memory                      # 查看记忆状态
zeloo memory list                 # 列出所有记忆
zeloo memory add "事实"           # 添加记忆
zeloo memory search "关键词"      # 搜索记忆
zeloo memory forget "关键词"      # 删除记忆
zeloo memory gc                   # 垃圾回收
zeloo memory compress             # 压缩记忆
zeloo memory stats                # 记忆统计
zeloo memory export file.json     # 导出记忆
zeloo memory import file.json     # 导入记忆
zeloo memory clear                # 清除所有记忆

# 会话管理
zeloo sessions                    # 列出所有会话
zeloo sessions list               # 同上
zeloo session <id>                # 查看会话详情
zeloo session <id> --export       # 导出会话
```

### 5.4 定时任务

```bash
# Cron 任务
zeloo cron                        # 列出所有定时任务
zeloo cron list                   # 同上
zeloo cron add my-task "0 2 * * *" "echo hi"  # 添加任务
zeloo cron remove my-task         # 删除任务
zeloo cron enable my-task         # 启用任务
zeloo cron disable my-task        # 禁用任务

# 支持 shell: 前缀执行复杂命令
zeloo cron add backup "0 3 * * *" "shell: tar -czf backup.tar.gz data/"
```

### 5.5 Skills 管理

```bash
# Skills
zeloo skills                      # 列出所有 skills
zeloo skills list                 # 同上
zeloo skills search "代码审查"    # 搜索 skills
zeloo skills install code-review  # 安装 skill
zeloo skills install /path/to/skill  # 从本地安装
zeloo skills install https://...  # 从 URL 安装
zeloo skills remove code-review   # 卸载 skill
zeloo skills update               # 更新所有 skills
```

### 5.6 MCP 管理

```bash
# MCP
zeloo mcp                         # 列出所有 MCP 服务器
zeloo mcp list                    # 同上
zeloo mcp add github              # 添加 MCP 服务器
zeloo mcp remove github           # 移除 MCP 服务器
zeloo mcp status                  # 查看状态
zeloo mcp restart                 # 重启 MCP 服务器
```

### 5.7 工作区管理

```bash
# 工作区
zeloo workspace                   # 列出所有工作区
zeloo workspace create my-project # 创建工作区
zeloo workspace switch my-project # 切换工作区
zeloo workspace delete my-project # 删除工作区
zeloo workspace archive           # 快照工作区
zeloo workspace restore snapshot  # 恢复快照

# Git Worktree（隔离执行）
zeloo worktree                    # 列出 worktree
zeloo worktree add feature-xyz    # 创建 worktree
zeloo worktree remove feature-xyz # 移除 worktree
zeloo worktree cleanup            # 清理过期 worktree
zeloo worktree cleanup --dry-run  # 预览清理
zeloo worktree cleanup --older-than-hours 24  # 清理 24h 前
zeloo worktree prune              # 修剪孤立 worktree

# 远程 worktree
zeloo worktree add --remote https://github.com/user/repo feature
```

### 5.8 工具与插件

```bash
# 工具
zeloo tools                       # 列出所有可用工具
zeloo tools list                  # 同上
zeloo tools call <tool>           # 调用工具

# 插件
zeloo plugins                     # 列出所有插件
zeloo plugins list                # 同上
zeloo plugins install <plugin>    # 安装插件
zeloo plugins enable <plugin>     # 启用插件
zeloo plugins disable <plugin>    # 禁用插件
zeloo plugins remove <plugin>     # 卸载插件
zeloo plugins update              # 更新插件
```

### 5.9 诊断与修复

```bash
# 环境诊断
zeloo doctor                      # 完整诊断
zeloo doctor --verbose            # 详细输出
zeloo doctor --fix                # 自动修复问题

# 修复安装
zeloo repair                      # 完整修复
zeloo repair --venv               # 修复虚拟环境
zeloo repair --deps               # 修复依赖
zeloo repair --config             # 修复配置文件
zeloo repair --all                # 全部修复

# 重置工作区
zeloo reset                       # 重置所有（需确认）
zeloo reset --config              # 重置配置
zeloo reset --memory              # 重置记忆
zeloo reset --sessions            # 重置会话
zeloo reset --cache               # 重置缓存
zeloo reset --all --yes           # 无确认全部重置

# 验证
zeloo verify                      # 验证安装完整性
zeloo verify --checksum           # 验证校验和

# 卸载
zeloo uninstall                   # 卸载 Zeloo
zeloo uninstall --purge           # 清除所有数据
```

### 5.10 备份与导出

```bash
# 备份
zeloo backup                      # 创建备份
zeloo backup --name snap-001      # 命名备份
zeloo backup list                 # 列出备份
zeloo backup restore snap-001     # 恢复备份
zeloo backup delete snap-001      # 删除备份

# 导出
zeloo export backup.tar.zst       # 导出全部
zeloo export backup.tar.zst --config  # 仅导出配置
zeloo export backup.tar.zst --sessions  # 仅导出会话
zeloo export backup.tar.zst --memory   # 仅导出记忆

# 导入
zeloo import backup.tar.zst       # 导入（合并）
zeloo import backup.tar.zst --replace  # 替换现有
```

### 5.11 其他命令

```bash
# 状态
zeloo status                      # 查看状态
zeloo status --json               # JSON 格式输出
zeloo status --watch              # 实时监控

# 日志
zeloo logs                        # 查看日志
zeloo logs --lines 100            # 最近 100 行
zeloo logs --level error          # 仅错误
zeloo logs --follow               # 实时跟踪

# 同步
zeloo sync                        # 同步配置

# Profile
zeloo profile                     # 管理 profile

# 使用统计
zeloo usage                       # 查看使用统计
zeloo usage --period month        # 本月统计
zeloo usage --cost                # 成本统计

# 更新
zeloo update                      # 检查更新
zeloo update --install            # 安装更新
zeloo update --check              # 仅检查

# Hook
zeloo hooks                       # 管理钩子
zeloo hooks list                  # 列出钩子
zeloo hooks add on-start          # 添加钩子
zeloo hooks remove on-start       # 移除钩子

# Secrets
zeloo secrets                     # 管理密钥
zeloo secrets list                # 列出密钥
zeloo secrets set KEY value       # 设置密钥
zeloo secrets get KEY             # 获取密钥
zeloo secrets delete KEY          # 删除密钥

# Dashboard
zeloo dashboard                   # 启动 Web Dashboard
zeloo dashboard --port 3000       # 指定端口
zeloo dashboard --stop            # 停止 Dashboard

# Shell 补全
zeloo completion install          # 安装补全脚本
zeloo completion bash             # 生成 bash 补全
zeloo completion zsh              # 生成 zsh 补全
zeloo completion fish             # 生成 fish 补全
zeloo completion powershell       # 生成 PowerShell 补全

# Fallback Chain
zeloo fallback                    # 查看 fallback chain
zeloo fallback list               # 同上
zeloo fallback add openai gpt-4o  # 添加 fallback
zeloo fallback remove openai      # 移除 fallback
zeloo fallback set-model openai gpt-4o-mini  # 设置模型
zeloo fallback validate           # 验证配置
```

---

## 6. 服务部署

### 6.1 本地服务模式

```bash
# 前台运行（开发/调试）
zeloo gateway foreground

# 后台运行（nohup）
nohup zeloo gateway > /var/log/zeloo/gateway.log 2>&1 &

# systemd 管理（见 §10）
sudo systemctl start zeloo
sudo systemctl enable zeloo
```

### 6.2 Gateway API 服务

```bash
# 基础启动
zeloo serve

# 生产配置
zeloo serve \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 \
  --api-key ${ZELOO_API_KEY} \
  --cors-origins "https://app.example.com" \
  --model-name gpt-4o

# 使用 Supervisor 管理（/etc/supervisor/conf.d/zeloo.conf）
[program:zeloo]
command=zeloo serve --host 0.0.0.0 --port 8000 --workers 4
directory=/opt/zeloo
user=zeloo
autostart=true
autorestart=true
stderr_logfile=/var/log/zeloo/err.log
stdout_logfile=/var/log/zeloo/out.log
environment=HOME="/var/lib/zeloo",ZELOO_HOME="/var/lib/zeloo"
```

### 6.3 远端 Gateway 客户端

```bash
# 连接远端 Gateway
zeloo run "分析这段代码" --remote https://gateway.example.com

# 检查远端连接
zeloo run --check --remote https://gateway.example.com

# 远端 Gateway 配置（~/.zeloo/config.yaml）
gateway:
  remote:
    url: https://gateway.example.com
    api_key: ${REMOTE_API_KEY}
    timeout: 60
```

---

## 7. 容器化部署

### 7.1 Docker 单容器

```dockerfile
# Dockerfile
FROM python:3.12-slim

LABEL maintainer=" Zeloo Team <team@zeloo.io>"
LABEL version="0.16.0"

# 安装依赖
RUN pip install --no-cache-dir zeloo==0.16.0

# 创建非 root 用户
RUN useradd -m -u 1000 zeloo
USER zeloo

WORKDIR /app

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD zeloo doctor || exit 1

ENTRYPOINT ["zeloo"]
CMD ["gateway", "foreground"]
```

```bash
# 构建镜像
docker build -t zeloo:0.16.0 .

# 运行容器
docker run -d \
  --name zeloo \
  -p 8000:8000 \
  -p 9113:9113 \
  -v zeloo-data:/data \
  -e OPENAI_API_KEY=${OPENAI_API_KEY} \
  -e ZELOO_HOME=/data \
  zeloo:0.16.0

# 查看日志
docker logs -f zeloo

# 进入容器调试
docker exec -it zeloo /bin/bash
```

### 7.2 Docker Compose（完整栈）

```yaml
# docker-compose.yml
version: "3.9"

services:
  zeloo:
    image: zeloo:0.16.0
    container_name: zeloo
    restart: unless-stopped
    ports:
      - "8000:8000"    # HTTP API
      - "9113:9113"    # Gateway
      - "3000:3000"    # Dashboard
    volumes:
      - zeloo-data:/data
      - ./config.yaml:/data/config.yaml:ro
    environment:
      - ZELOO_HOME=/data
      - ZELOO_ENV=production
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - REDIS_URL=redis://redis:6379
    depends_on:
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "zeloo", "doctor"]
      interval: 30s
      timeout: 10s
      retries: 3

  redis:
    image: redis:7-alpine
    container_name: zeloo-redis
    restart: unless-stopped
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3

  # 可选：PostgreSQL（用于会话持久化）
  postgres:
    image: postgres:16-alpine
    container_name: zeloo-postgres
    restart: unless-stopped
    volumes:
      - postgres-data:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=zeloo
      - POSTGRES_USER=zeloo
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U zeloo"]
      interval: 10s
      timeout: 5s
      retries: 3

volumes:
  zeloo-data:
  redis-data:
  postgres-data:
```

```bash
# 启动
docker compose up -d

# 查看状态
docker compose ps

# 查看日志
docker compose logs -f zeloo

# 停止
docker compose down
```

### 7.3 GPU 支持（CUDA）

```dockerfile
# Dockerfile.gpu
FROM nvidia/cuda:12.1-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y \
    python3.12 python3.12-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir zeloo==0.16.0

# 后续同上...
```

```bash
# 运行 GPU 容器
docker run -d \
  --gpus all \
  --name zeloo-gpu \
  -p 8000:8000 \
  -e OPENAI_API_KEY=${OPENAI_API_KEY} \
  zeloo:0.16.0-gpu
```

---

## 8. Kubernetes 部署

### 8.1 快速部署

```bash
# 克隆配置
kubectl apply -f k8s/

# 查看部署状态
kubectl get pods -l app=zeloo

# 查看日志
kubectl logs -l app=zeloo -f
```

### 8.2 Secret 配置

```bash
# 创建 Secret（API Keys）
kubectl create secret generic zeloo-secrets \
  --from-literal=openai-api-key=${OPENAI_API_KEY} \
  --from-literal=anthropic-api-key=${ANTHROPIC_API_KEY} \
  --from-literal=zeloo-api-key=${ZELOO_API_KEY:-$(openssl rand -hex 32)}

# 或使用 KSOPS/Vault 集成
# kubectl annotate secret zeloo-secrets \
#   kustomize.toolkit.fluxcd.io/force-recreate=true
```

### 8.3 ConfigMap 配置

```yaml
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: zeloo-config
  namespace: default
data:
  provider: "anthropic"
  model: "claude-3-5-sonnet-20241022"
  log-level: "WARNING"
  # 可注入完整配置
  config.yaml: |
    llm:
      default_provider: anthropic
      default_model: claude-3-5-sonnet-20241022
```

### 8.4 HPA 自动扩缩容

```bash
# 基于 CPU 自动扩缩
kubectl autoscale deployment zeloo --cpu-percent=70 --min=2 --max=10

# 基于自定义指标（需要 Prometheus Adapter）
kubectl apply -f k8s/hpa.yaml
```

### 8.5 Ingress 配置

```yaml
# k8s/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: zeloo-ingress
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "100m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - zeloo.example.com
      secretName: zeloo-tls
  rules:
    - host: zeloo.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: zeloo
                port:
                  number: 8000
```

### 8.6 PVC 持久化存储

```yaml
# k8s/pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: zeloo-data
  namespace: default
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: standard-ssd  # 根据云厂商调整
  resources:
    requests:
      storage: 50Gi
```

---

## 9. Helm Chart 部署

### 9.1 添加 Helm Repo

```bash
# 添加 Helm Repo（如果有）
helm repo add zeloo https://charts.zeloo.io
helm repo update

# 或使用本地 Chart
git clone https://github.com/zeloo/zeloo.git
cd zeloo/helm/zeloo
```

### 9.2 安装 Chart

```bash
# 创建命名空间
kubectl create namespace zeloo

# 安装（使用默认配置）
helm install zeloo ./helm/zeloo -n zeloo

# 自定义配置
helm install zeloo ./helm/zeloo -n zeloo \
  --set image.tag=v0.16.0 \
  --set replicaCount=3 \
  --set gateway.port=8000 \
  --set resources.limits.cpu=2000m \
  --set resources.limits.memory=4Gi \
  --set persistence.enabled=true \
  --set persistence.size=50Gi

# 从 values 文件安装
helm install zeloo ./helm/zeloo -n zeloo -f my-values.yaml
```

### 9.3 values.yaml 关键配置

```yaml
# helm/zeloo/values.yaml 关键字段

image:
  repository: zeloo/zeloo
  tag: v0.16.0
  pullPolicy: IfNotPresent

replicaCount: 2

imagePullSecrets: []
# - name: regcred

service:
  type: ClusterIP
  port: 8000
  metricsPort: 9090

ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: zeloo.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: zeloo-tls
      hosts:
        - zeloo.example.com

resources:
  limits:
    cpu: 2000m
    memory: 4Gi
  requests:
    cpu: 500m
    memory: 1Gi

persistence:
  enabled: true
  storageClass: standard-ssd
  size: 50Gi
  accessMode: ReadWriteOnce

config:
  env: production
  provider: anthropic
  model: claude-3-5-sonnet-20241022

secrets:
  # 使用外部 Secret（推荐）
  existingSecret: zeloo-secrets

affinity: {}
# nodeAffinity:
#   preferredDuringSchedulingIgnoredDuringExecution:
#     - weight: 100
#       preference:
#         matchExpressions:
#           - key: node-type
#             operator: In
#             values:
#               - compute-optimized

tolerations: []

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80

prometheus:
  enabled: true
  serviceMonitor:
    enabled: true
    interval: 30s
```

### 9.4 升级与回滚

```bash
# 升级
helm upgrade zeloo ./helm/zeloo -n zeloo --set image.tag=v0.16.1

# 回滚
helm rollback zeloo -n zeloo

# 查看历史
helm history zeloo -n zeloo

# 卸载
helm uninstall zeloo -n zeloo
```

---

## 10. 系统服务

### 10.1 Linux systemd

```bash
# 安装服务
sudo cp packaging/systemd/zeloo.service /etc/systemd/system/
sudo cp packaging/systemd/zeloo-gateway.socket /etc/systemd/system/
sudo cp packaging/scripts/install_systemd.sh .

# 创建用户和目录
sudo useradd -r -m -s /usr/sbin/nologin zeloo
sudo mkdir -p /var/lib/zeloo /var/log/zeloo
sudo chown -R zeloo:zeloo /var/lib/zeloo /var/log/zeloo

# 配置环境变量
sudo cp config_examples/production.yaml /etc/zeloo/config.yaml
sudo vim /etc/zeloo/zeloo.env  # 填入 API Keys

# 启用并启动
sudo systemctl daemon-reload
sudo systemctl enable zeloo
sudo systemctl start zeloo

# 查看状态
sudo systemctl status zeloo

# 查看日志
sudo journalctl -u zeloo -f
```

### 10.2 macOS launchd

```bash
# 复制配置文件
mkdir -p ~/Library/LaunchAgents
cp packaging/launchd/com.zeloo.agent.plist ~/Library/LaunchAgents/

# 创建数据目录
mkdir -p ~/Library/Application\ Support/Zeloo

# 加载服务
launchctl load ~/Library/LaunchAgents/com.zeloo.agent.plist

# 查看状态
launchctl print gui/$UID/com.zeloo.agent

# 重启服务
launchctl kickstart -k gui/$UID/com.zeloo.agent
launchctl load ~/Library/LaunchAgents/com.zeloo.agent.plist
```

### 10.3 Windows Service

```powershell
# PowerShell（管理员）
# 下载安装脚本
Invoke-WebRequest -Uri https://raw.githubusercontent.com/zeloo/zeloo/main/packaging/windows/install-service.ps1 -OutFile install-service.ps1

# 执行安装（自动请求管理员权限）
.\install-service.ps1

# 安装后配置 .env
$env:ZELOO_HOME = "$env:ProgramData\Zeloo"
$env:OPENAI_API_KEY = "sk-..."

# 查看服务状态
Get-Service -Name Zeloo
Get-Service -Name Zeloo | Format-List

# 查看日志
Get-WinEvent -FilterHashtable @{LogName="Application";ProviderName="Zeloo"} -MaxEvents 50
```

---

## 11. CI/CD 集成

### 11.1 GitHub Actions

```yaml
# .github/workflows/zeloo-ci.yml
name: Zeloo CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    env:
      ZELOO_ENV: ci
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}

    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install Zeloo
        run: pip install zeloo==0.16.0 pytest

      - name: Run tests
        run: |
          zeloo doctor
          pytest tests/unit/ -q --tb=short

      - name: Security scan
        run: |
          zeloo secrets scan
          zeloo verify --checksum
```

### 11.2 GitLab CI

```yaml
# .gitlab-ci.yml
stages:
  - test
  - security
  - deploy

zeloo-test:
  stage: test
  image: python:3.12-slim
  before_script:
    - pip install zeloo==0.16.0 pytest
  script:
    - zeloo doctor
    - pytest tests/unit/ -q
  variables:
    ZELOO_ENV: ci
    OPENAI_API_KEY: $OPENAI_API_KEY

zeloo-security:
  stage: security
  image: python:3.12-slim
  before_script:
    - pip install zeloo==0.16.0
  script:
    - zeloo verify
    - zeloo secrets scan
  only:
    - main
    - merge_requests

deploy-production:
  stage: deploy
  image: bitnami/kubectl
  script:
    - kubectl apply -f k8s/
    - kubectl rollout status deployment/zeloo
  environment:
    name: production
  only:
    - main
  when: manual
```

### 11.3 GitHub Release + PyPI

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags:
      - "v*"

jobs:
  release:
    runs-on: ubuntu-latest
    permissions:
      id-token: write  # 用于 OIDC 认证 PyPI

    steps:
      - uses: actions/checkout@v4

      - name: Build & Publish
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          password: ${{ secrets.PYPI_TOKEN }}

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v1
        with:
          files: dist/*
          generate_release_notes: true
```

---

## 12. 安全加固

### 12.1 生产环境安全检查清单

```bash
# 1. 检查当前安全状态
zeloo doctor --verbose | grep -i security

# 2. 扫描密钥泄露
zeloo secrets scan

# 3. 验证安装完整性
zeloo verify --checksum

# 4. 配置危险工具策略
zeloo config set security.dangerous_policy confirm

# 5. 启用 Vault（生产推荐）
export VAULT_URL=https://vault.example.com
export VAULT_TOKEN=$VAULT_TOKEN
zeloo config set vault.enabled true
```

### 12.2 网络安全

```bash
# 防火墙规则（Linux）
sudo ufw allow 8000/tcp comment "Zeloo Gateway"
sudo ufw allow 9113/tcp comment "Zeloo API"
sudo ufw deny 8000/tcp from 0.0.0.0/0  # 仅内网访问

# 限制 API 访问（IP 白名单）
# config.yaml
gateway:
  api:
    allowed_ips:
      - 10.0.0.0/8
      - 192.168.0.0/16
```

### 12.3 资源限制

```yaml
# systemd 资源限制（/etc/systemd/system/zeloo.service）
[Service]
MemoryMax=2G
MemorySwapMax=1G
LimitNOFILE=65536
LimitNPROC=1024
CPUQuota=200%
```

### 12.4 日志审计

```bash
# 启用结构化日志
export ZELOO_LOG_FORMAT=json
export ZELOO_LOG_LEVEL=WARNING

# 日志集中收集（ELK/Loki）
# config.yaml
logging:
  format: json
  output: syslog
  syslog:
    facility: daemon
    address: udp://loki:514
```

---

## 13. 备份与恢复

### 13.1 自动备份脚本

```bash
#!/bin/bash
# backup.sh - 每日备份脚本（crontab: 0 2 * * * /opt/zeloo/backup.sh）

set -euo pipefail

BACKUP_DIR="/var/backups/zeloo"
DATE=$(date +%Y%m%d_%H%M%S)
ZELOO_HOME="${ZELOO_HOME:-/var/lib/zeloo}"

mkdir -p "$BACKUP_DIR"

# 备份配置文件
tar -czf "$BACKUP_DIR/config_${DATE}.tar.gz" \
  "$ZELOO_HOME/config.yaml" \
  "$ZELOO_HOME/.env" 2>/dev/null || true

# 备份记忆和会话
zeloo export "$BACKUP_DIR/memory_${DATE}.tar.zst"

# 备份 MCP 配置
tar -czf "$BACKUP_DIR/mcp_${DATE}.tar.gz" \
  "$ZELOO_HOME/mcp_config.json" 2>/dev/null || true

# 保留最近 30 天
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete
find "$BACKUP_DIR" -name "*.tar.zst" -mtime +30 -delete

# 上传到 S3（可选）
# aws s3 sync "$BACKUP_DIR" s3://my-bucket/zeloo-backups/

echo "[$(date)] Backup completed: $DATE"
```

### 13.2 恢复流程

```bash
# 1. 停止服务
sudo systemctl stop zeloo

# 2. 备份当前数据
sudo cp -r /var/lib/zeloo /var/lib/zeloo.bak.$(date +%Y%m%d)

# 3. 恢复配置
tar -xzf /var/backups/zeloo/config_YYYYMMDD.tar.gz -C /var/lib/zeloo/

# 4. 恢复记忆
zeloo import /var/backups/zeloo/memory_YYYYMMDD.tar.zst --replace

# 5. 验证
zeloo doctor
zeloo memory stats

# 6. 重启服务
sudo systemctl start zeloo
```

---

## 14. 故障排查

### 14.1 常见问题

| 问题 | 原因 | 解决方案 |
|---|---|---|
| `zeloo: command not found` | PATH 未包含 | `export PATH="$HOME/.local/bin:$PATH"` |
| `API Key 无效` | Key 格式错误/过期 | `zeloo auth <provider>` 重新认证 |
| `Connection timeout` | 网络/防火墙问题 | 检查代理设置 `http_proxy`/`https_proxy` |
| `MemoryError` | 上下文超长 | `zeloo memory compress` 或重启会话 |
| `Permission denied` | 文件权限问题 | `chmod +x $(which zeloo)` |
| `ModuleNotFoundError` | 依赖缺失 | `pip install --upgrade zeloo` |

### 14.2 诊断命令

```bash
# 完整诊断
zeloo doctor

# 详细诊断
zeloo doctor --verbose --fix

# 查看配置
zeloo config

# 查看日志
zeloo logs --level debug --lines 100

# 测试 API 连接
curl -X POST http://localhost:9113/v1/chat/completions \
  -H "Authorization: Bearer $ZELOO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}'

# 检查 Gateway 健康
curl http://localhost:9113/health
```

### 14.3 日志位置

| 平台 | 日志位置 |
|---|---|
| systemd | `journalctl -u zeloo -f` |
| Docker | `docker logs zeloo -f` |
| Kubernetes | `kubectl logs -l app=zeloo -f` |
| macOS launchd | `~/Library/Logs/Zeloo/` |
| Windows | 事件查看器 → 应用程序日志 |
| 本地前台 | 直接输出到 stdout |

### 14.4 性能调优

```bash
# 1. 增加 LLM 超时（处理慢响应）
export ZELOO_LLM_TIMEOUT_SECONDS=600

# 2. 启用 Redis 缓存（高并发）
export REDIS_URL=redis://localhost:6379

# 3. 调整内存限制
# systemd: MemoryMax=4G
# Docker: --memory=4g

# 4. 增加 worker 数（多核）
zeloo serve --workers 8

# 5. 启用压缩（减少网络传输）
zeloo config set context.compression.enabled true
```

---

## 附录 A：环境变量速查表

| 变量 | 说明 | 默认值 |
|---|---|---|
| `ZELOO_HOME` | Zeloo 主目录 | `~/.Zeloo` |
| `ZELOO_ENV` | 环境（development/production/ci）| `development` |
| `ZELOO_CONFIG` | 配置文件路径 | 自动探测 |
| `ZELOO_MODEL` | 默认模型 | `gpt-4o` |
| `ZELOO_PROVIDER` | 默认 Provider | `openai` |
| `ZELOO_BASE_URL` | 自定义 API 端点 | — |
| `ZELOO_API_KEY` | Gateway 认证 Token | — |
| `ZELOO_OFFLINE` | 离线模式（1=启用）| `0` |
| `ZELOO_LLM_TIMEOUT_SECONDS` | LLM 超时（秒）| `300` |
| `ZELOO_STREAM` | 流式输出 | `true` |
| `ZELOO_BG_REVIEW` | 后台复盘 | `false` |
| `ZELOO_COST_WARN_THRESHOLD` | 成本警告阈值 | `10.0` |
| `ZELOO_COST_ABORT_THRESHOLD` | 成本中止阈值 | `100.0` |
| `ZELOO_DANGEROUS_POLICY` | 危险工具策略 | `allow` |
| `TERMINAL_BACKEND` | 终端后端 | `local` |
| `TERMINAL_CWD` | 终端工作目录 | `.` |

---

## 附录 B：端口映射

| 端口 | 协议 | 用途 |
|---|---|---|
| `8000` | HTTP | HTTP API 服务（`zeloo serve`）|
| `9113` | HTTP | Gateway API（`zeloo gateway`）|
| `3000` | HTTP | Web Dashboard（`zeloo dashboard`）|
| `9090` | HTTP | Prometheus Metrics |
| `6379` | TCP | Redis（外部，可选）|
| `5432` | TCP | PostgreSQL（外部，可选）|
