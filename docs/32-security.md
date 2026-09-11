# 32. 安全设计

## 32.1 安全威胁模型

Zeloo 作为常驻型 Agent，面临以下核心安全威胁：

| 威胁 | 影响 | 防护措施 |
|------|------|----------|
| Prompt 注入 | Agent 被劫持执行恶意操作 | 上下文文件扫描、工具结果清洗 |
| 越权操作 | Agent 执行未授权操作 | 工具权限分级、用户确认、沙箱隔离 |
| 数据泄露 | 敏感信息暴露 | 数据脱敏、日志过滤、传输加密 |
| 供应链攻击 | 依赖包被篡改 | 精确版本锁定、漏洞扫描 |
| 会话劫持 | 未授权访问 Agent | 平台白名单、Token 鉴权 |

## 32.2 Prompt 注入防护

### 32.2.1 上下文文件扫描

所有注入 system prompt 的上下文文件（AGENTS.md、.cursorrules、SOUL.md 等）必须经过威胁扫描：

`tools/threat_patterns.py` 中的实际实现采用双列表结构：

**关键注入模式（Critical，context + suspicious 范围均检测）**：

| 正则 | 威胁名 | 说明 |
|------|--------|------|
| `(?i)(ignore\|disregard\|forget)\s+(all\s+)?(previous\|above\|prior\|system)\s+(instructions?\|prompts?)` | `instruction-override` | 忽略/忘记先前指令 |
| `(?i)(you\s+are\s+now\|act\s+as\|pretend\s+to\s+be)\s+(a\|an\|the)\s+(DAN\|jailbreak\|unrestricted\|admin\|root)` | `role-hijack` | 角色劫持 |
| `(?i)(print\|reveal\|show\|output\|display\|repeat)\s+(the\s+)?(system\s+)?(prompt\|instructions?)` | `system-prompt-leak-attempt` | 试图泄露系统提示词 |
| `(?i)<\s*system\s*>` | `system-tag-injection` | `<system>` XML 标签注入 |

**可疑模式（Suspicious，仅 context 范围检测）**：

| 正则 | 威胁名 | 说明 |
|------|--------|------|
| `(?i)(prompt\s+injection\|jailbreak\|ignore\s+rules)` | `suspicious-keyword` | 注入/越狱相关关键词 |
| `(?i)from\s+now\s+on` | `persona-reset-attempt` | "从现在起" 指令重置尝试 |

**扫描 API**：

```python
from tools.threat_patterns import scan_for_threats, is_blocked_for_context

# 扫描用户输入（"input" scope：只检测 critical）
findings = scan_for_threats(user_text, scope="input")

# 扫描上下文文件（"context" scope：critical + suspicious 均检测）
if is_blocked_for_context(file_content):
    # 文件被阻止注入，替换为 [BLOCKED: <filename>]

# 扫描工具结果（"context" scope：强制使用）
findings = scan_for_threats(tool_result, scope="context")
```

**处理方式**：
- context 范围命中 → 原文**永不进入** system prompt，替换为 `[BLOCKED: <filename> contained potential prompt injection]`
- suspicious 范围仅记录 warning 日志，不阻止
- 记录 `threat_patterns.<threat_name>` 指标

### 32.2.2 工具结果清洗

工具返回结果在注入 messages 前经过清洗：

```python
def sanitize_tool_result(content: str) -> str:
    # 1. 威胁扫描（strict 范围）
    findings = scan_for_threats(content, scope="strict")
    if findings:
        content = f"[REDACTED: potential threat detected: {', '.join(findings)}]"

    # 2. 截断过长内容
    if len(content) > MAX_TOOL_RESULT_LENGTH:
        content = content[:MAX_TOOL_RESULT_LENGTH] + "\n...[truncated]"

    # 3. 去除控制字符
    content = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", content)

    return content
```

### 32.2.3 系统提示词与用户内容分离

system prompt 中明确分隔符，防止用户内容被误认为指令：

```
<system>
... system instructions ...
</system>

<user_input>
{actual_user_message}
</user_input>
```

## 32.3 工具权限管控

### 32.3.1 危险工具分级

```python
@tool(name="shell", dangerous=True, confirmation_required=True)
def shell(command: str) -> str: ...

@tool(name="file_write", dangerous=True)
def file_write(path: str, content: str) -> str: ...

@tool(name="file_read", dangerous=False)
def file_read(path: str) -> str: ...
```

| 级别 | 说明 | 处理 |
|------|------|------|
| `safe` | 只读操作 | 直接执行 |
| `dangerous` | 修改系统状态 | 日志记录，可配置需确认 |
| `confirmation_required` | 高风险操作 | 执行前必须用户确认 |

### 32.3.2 shell_unsafe — 受限只读 Shell

为满足只读探查需求同时避免全功能 shell 的风险，提供 `shell_unsafe` 工具：

- **白名单命令**：仅允许 `ls`、`cat`、`head`、`tail`、`grep`、`find`、`pwd`、`stat`、`wc` 等只读命令
- **禁止重定向**：拦截 `>`、`>>`、`<`、`|`、`;`、`&`、`$()`、反引号等
- **禁止路径穿越**：拦截包含 `..` 的路径参数
- **超时保护**：默认 10s 超时

不在白名单或命中拦截规则的命令直接拒绝并返回错误信息，不执行。

### 32.3.3 沙箱隔离

代码执行和 shell 命令在隔离环境中运行：

- 进程隔离：独立子进程
- 文件系统隔离：限制可访问目录
- 资源限制：CPU、内存、超时
- 网络隔离：可配置禁止网络访问

### 32.3.3 子代理权限降级

子代理默认使用受限工具集：

```python
SUBAGENT_TOOLS = ["file_read", "web_search", "web_fetch", "skill_view", "memory"]
# 排除：shell, file_write, file_edit, delegate_task
```

## 32.4 数据安全

### 32.4.1 敏感信息脱敏

日志和轨迹中的敏感信息自动脱敏：

```python
def redact_secrets(text: str) -> str:
    patterns = [
        (r"sk-[a-zA-Z0-9]{20,}", "[REDACTED_API_KEY]"),
        (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "[REDACTED_KEY]"),
        (r"(?i)(password|secret|token)\s*[=:]\s*\S+", r"\1=[REDACTED]"),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text, flags=re.DOTALL)
    return text
```

### 32.4.2 传输加密

- 所有外部 API 调用使用 HTTPS
- 网关与平台通信使用 TLS
- 本地 API Server 默认启用 HTTPS（可配置）

### 32.4.3 存储安全

- SQLite 数据库文件权限 `chmod 600`
- `.env` 文件权限 `chmod 600`
- 记忆/技能文件不包含明文密钥

### 32.4.4 凭证持久化安全

凭证池（CredentialPool）的安全措施：

- **文件权限**：凭证存储文件 `credentials.json` 权限强制设为 `0600`
- **值脱敏**：日志和状态输出中 API Key 自动脱敏（`sk-t...1234`）
- **熔断隔离**：认证失败（401/403）的 Key 被永久禁用，不参与后续轮询
- **环境变量优先**：优先使用环境变量中的 Key，避免明文写入配置文件
- **密钥来源**：支持 Bitwarden、1Password 等密码管理器作为凭证源（`secret_sources`）

## 32.5 访问控制

### 32.5.1 平台白名单

消息网关配置允许的用户列表：

```yaml
gateway:
  platforms:
    telegram:
      allowed_users: [123456789, 987654321]
    discord:
      allowed_guilds: [123456789]
      allowed_roles: ["admin"]
```

未授权用户的消息被忽略并记录日志。

### 32.5.2 API 鉴权

API Server 使用 Bearer Token 鉴权：

```yaml
api_server:
  auth:
    type: bearer
    tokens:
      - ${zeloo_API_TOKEN}
```

### 32.5.3 Profile 隔离

不同 profile 的数据严格隔离：

- 每个 profile 有独立的 skills/、memories/、plugins/
- Agent 通过 `_agent_home()` 确保从自己的 profile 读取
- 网关通过 ContextVar 绑定 profile，避免串身份

## 32.6 供应链安全

### 32.6.1 依赖锁定

- 所有依赖精确版本锁定（`==X.Y.Z`）
- 使用 `uv.lock` 锁定完整依赖树
- CI 中验证 `uv.lock` 与 `pyproject.toml` 一致

### 32.6.2 漏洞扫描

CI 流水线中集成多种扫描工具：

```bash
# 扫描 Python 依赖漏洞
pip-audit -r requirements.txt

# OSV 漏洞数据库扫描（覆盖多语言）
osv-scanner -r .

# 供应链审计
supply-chain-audit

# 扫描 npm 依赖
npm audit
```

**代码审查**：集成 CodeRabbit AI 进行自动化代码审查，覆盖安全、性能、可读性维度。

### 32.6.3 最小依赖

- 核心依赖不超过 20 个
- 可选功能通过 extras 安装
- 定期审查依赖，移除未使用的

## 32.7 日志与审计

### 32.7.1 日志分级

| 级别 | 内容 |
|------|------|
| `DEBUG` | 详细调试信息（工具调用参数、LLM 请求） |
| `INFO` | 关键事件（会话开始/结束、工具执行） |
| `WARNING` | 异常但可恢复（Provider 切换、注入拦截） |
| `ERROR` | 错误（工具失败、连接超时） |
| `CRITICAL` | 严重错误（数据损坏、安全事件） |

### 32.7.2 审计日志

危险操作单独记录审计日志：

```json
{
  "timestamp": "2026-09-07T10:00:00Z",
  "session_id": "...",
  "user_id": "...",
  "tool": "shell",
  "command": "rm -rf /tmp/test",
  "result": "success",
  "confirmation": "user_approved"
}
```

### 32.7.3 日志脱敏

日志中的敏感信息自动脱敏（见 9.4.1）。

## 32.8 安全检查清单

发布前必须通过以下检查：

- [ ] 所有上下文文件经过威胁扫描
- [ ] 所有工具结果经过清洗
- [ ] 危险工具有确认机制
- [ ] 沙箱隔离正常工作
- [ ] 日志中无明文密钥
- [ ] 依赖无已知高危漏洞
- [ ] 平台白名单配置正确
- [ ] `.env` 文件权限为 600
- [ ] API Server 启用鉴权
- [ ] Profile 隔离无串身份
