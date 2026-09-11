# 36. 国际化、环境与配置示例

## 36.1 `locales/` — 国际化语言包

### 36.1.1 目录结构

```
locales/
├── en.yaml              # 英语（默认）
└── zh-CN.yaml           # 简体中文
```

### 36.1.2 YAML 键值格式

```yaml
# locales/en.yaml
hello_world: "Hello, world"
tool_call_failed: "Tool call failed: {tool}"
session_started: "Session started"
gateway_started: "Gateway starting with {count} platform(s)"
```

**占位符语法：** 使用 `{name}` 占位符，运行时由 Python `str.format()` 注入。

### 36.1.3 加载机制

```python
from agent.i18n import t, set_locale, get_locale

# 默认 locale 为 en
print(t("hello_world"))                  # "Hello, world"

# 切换为简体中文
set_locale("zh-CN")
print(t("tool_call_failed", tool="web_search"))
# "工具调用失败: web_search"

# 查询当前 locale
get_locale()                              # "zh-CN"
```

### 36.1.4 添加新语言

1. 复制 `en.yaml` 为 `<lang>.yaml`
2. 翻译所有键值
3. 提交 PR 并在 `agent/i18n.py` 注册

### 36.1.5 已实现键

| 键 | 用途 |
|----|------|
| `hello_world` | 启动欢迎语 |
| `session_started` / `session_ended` | 会话生命周期 |
| `tool_call_failed: {tool}` | 工具调用失败 |
| `estop_triggered: {reason}` | 紧急停止 |
| `curator_skill_stale: {skill} {days}` | Curator 检测技能陈旧 |
| `curator_skill_archived: {skill}` | 技能已归档 |
| `kanban_task_created: {title}` | Kanban 任务创建 |
| `kanban_task_completed: {title}` | Kanban 任务完成 |
| `kanban_zombie_reclaimed: {task_id}` | 僵尸任务回收 |
| `insights_report_generated` | 洞察报告生成 |
| `credential_key_disabled: {label} {reason}` | 凭证禁用 |
| `error_rate_limit: {seconds}` | 速率限制重试 |
| `gateway_started: {count}` | 网关启动 |
| `gateway_stopped` | 网关停止 |
| `platform_registered: {name}` | 平台注册 |

---

## 36.2 `environments/` — 多环境配置模板

### 36.2.1 目录结构

```
environments/
├── __init__.py          # 包初始化
├── base.yaml            # 基础默认值（所有环境继承）
├── dev.yaml             # 开发环境
├── test.yaml            # 测试环境
└── prod.yaml            # 生产环境
```

### 36.2.2 继承与覆盖

`base.yaml` 是所有环境的根配置；其他环境通过 deep-merge 覆盖：

```yaml
# environments/base.yaml（基线）
provider: openai
voice:
  backend: console
memory:
  enabled: true
self_evolution:
  background_review:
    enabled: false
mcp:
  servers: []
```

```yaml
# environments/dev.yaml（开发环境覆盖）
provider: openai
voice:
  backend: console
debug: true                     # 仅开发环境开启调试
log_level: DEBUG                # 仅开发环境 DEBUG 日志
mcp:
  servers:
    - github
    - notion
```

### 36.2.3 使用方式

```bash
# 通过环境变量激活环境
zeloo_ENV=dev uv run Zeloo run

# 通过 CLI 参数激活
Zeloo run --env dev
```

### 36.2.4 环境矩阵

| 环境 | 用途 | 调试 | MCP 服务器 | 日志级别 |
|------|------|------|-----------|---------|
| `base` | 默认基线 | ❌ | [] | INFO |
| `dev` | 本地开发 | ✅ | github/notion | DEBUG |
| `test` | 自动化测试 | ❌ | [] | WARNING |
| `prod` | 生产部署 | ❌ | 已配置 | INFO |

---

## 36.3 `config-examples/` — 配置示例集合

### 36.3.1 目录结构

```
config-examples/
├── minimal.yaml             # 最小 CLI 配置（最快上手）
├── development.yaml         # 全功能开发配置
├── gateway.yaml             # 多平台网关配置
├── mcp-integration.yaml     # MCP 集成配置
└── cost-optimized.yaml      # 成本优化配置
```

### 36.3.2 minimal.yaml — 最小配置

```yaml
model: gpt-4o
provider: openai
temperature: 0.0
max_tokens: 4096
max_iterations: 90

terminal:
  backend: local
  timeout: 30

memory:
  enabled: true
  user_profile_enabled: true
  max_chars: 8000
```

适用场景：快速验证、CI 流水线。

### 36.3.3 development.yaml — 全功能开发

启用所有开发功能（debug、MCP 服务器、cost_tracker、observability、cron）。

### 36.3.4 gateway.yaml — 多平台网关

预配置 5+ 消息平台（telegram / discord / slack / feishu / wecom），启用 voice / api_server。

### 36.3.5 mcp-integration.yaml — MCP 集成

预配置 5+ MCP 服务器（github / linear / notion / sentry / slack），启用 tool_filter。

### 36.3.6 cost-optimized.yaml — 成本优化

```yaml
# 配置示例
model: gpt-4o-mini            # 使用低成本模型
provider: openai
temperature: 0.0
max_tokens: 2048              # 限制输出 token
max_iterations: 30            # 限制迭代次数

compression:
  enabled: true
  threshold: 0.7              # 70% 上下文使用触发压缩

caching:
  prompt_cache_enabled: true  # 启用 prompt cache
```

### 36.3.7 使用方式

```bash
# 复制示例为实际配置
cp config-examples/minimal.yaml ~/.Zeloo/config.yaml

# 验证配置
Zeloo config validate
```

---

## 36.4 三者协同

```
┌─────────────────────────────────────────────────────────────┐
│                       启动流程                                │
├─────────────────────────────────────────────────────────────┤
│  1. 读取 ~/.Zeloo/config.yaml（用户配置）                    │
│  2. 加载 environments/<env>.yaml（环境层叠加）                │
│  3. 应用 config-examples/*.yaml（场景化基线）                  │
│  4. CLI 参数覆盖（最高优先级）                                  │
│  5. 加载 locales/<lang>.yaml（根据 zeloo_LANG）              │
└─────────────────────────────────────────────────────────────┘
```

优先级：**CLI 参数 > 用户配置 > 环境配置 > 示例配置**

---

## 36.5 测试覆盖

| 测试文件 | 覆盖功能 | 用例数 |
|----------|----------|--------|
| `test_environments.py` | environments 多环境加载 | — |
