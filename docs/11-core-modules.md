# 11. 核心模块详解

本文档对 Zeloo 核心模块进行系统化梳理，涵盖所有新增模块的架构设计、核心 API 和集成方式。
文档系统化梳理所有核心模块，并标注各模块的设计决策。

## 11.1 模块总览

`agent/` 目录共 **53 个** Python 模块（主目录 43 个 + transports 7 个 + agents_workflow 3 个），按职责分为 7 大类：

```
agent/
├── ─── 核心引擎 ───────────────────────────────────────────
├── conversation_loop.py      # 思考-行动循环（主循环）
├── conversation_compression.py # 对话压缩（语义压缩，token 节省）
├── context_compressor.py     # 上下文压缩器（静态+动态压缩）
├── compression_facade.py    # 压缩门面（统一多种压缩策略）
├── context_engine.py         # 上下文管理引擎
├── context_breakdown.py      # 上下文用量分解
├── provider_router.py        # Provider 路由（多模型自动切换）
├── chat_completion_helpers.py # Chat Completion 辅助工具
├── auxiliary_client.py       # 辅助客户端封装
├── client_lifecycle.py       # 客户端生命周期管理
├── agent_init.py             # Agent 初始化
├── agent_runtime_helpers.py  # 运行时辅助函数集
├── runtime_cwd.py            # 运行时工作目录解析
│
├── ─── 凭证与安全 ─────────────────────────────────────────
├── credential_pool.py        # 多 Key 凭证池（轮询/熔断/冷却）
├── credential_crypto.py      # 凭证加密（AES-GCM，secfile 格式）
├── secret_scanner.py         # 密钥检测（正则匹配 leaked key）
│
├── ─── 可观测性 ───────────────────────────────────────────
├── langfuse_integration.py   # Langfuse 链路追踪（HTTP 直连）
├── audit_observability.py     # AuditLog → Langfuse 桥接
├── error_observability.py    # ErrorTracker → Langfuse 桥接
├── audit_log.py              # 追加式哈希链审计日志（JSONL）
├── error_tracker.py           # 运行时错误追踪
├── cost_tracker.py            # Token 成本跟踪
│
├── ─── 技能与知识 ─────────────────────────────────────────
├── memory_manager.py         # 记忆管理器
├── memory_providers.py        # 9 个记忆后端实现
├── skill_utils.py            # 技能工具函数
├── curator.py                # 技能生命周期管理（active→stale→archived）
├── skill_hot_reload.py       # 技能热重载（文件监听）
├── skill_webhooks.py         # 技能远程 Webhook
│
├── ─── 工具与工具集 ───────────────────────────────────────
├── prompt_builder.py          # 提示词构建器
├── display.py                 # 显示/格式化工具
├── estop.py                  # 全局紧急停止
├── insights.py               # 运行时洞察（指标采集）
├── i18n.py                   # 国际化（2 种语言：en/zh-CN）
├── oauth.py                  # OAuth 授权
├── error_classifier.py        # 错误分类（可重试/降级策略）
├── background_review.py       # 后台复盘
├── kanban.py                 # 多智能体看板
│
├── ─── 目录 ──────────────────────────────────────────────
├── transports/               # LLM API 传输层适配器
│   ├── base.py
│   ├── anthropic_adapter.py
│   ├── bedrock_adapter.py
│   └── codex_runtime.py
│
├── agents_workflow/          # 多 Agent 工作流
│   ├── coordinator.py
│   └── pipeline.py
│
└── __init__.py
```

---

## 11.2 AuditLog（追加式哈希链审计日志）

### 11.2.1 设计目标

记录所有安全相关事件（文件操作、API 调用、Webhook 投递、技能注册、estop 触发）到 `~/.Zeloo/audit.log`，采用追加写模式 + SHA-256 哈希链确保防篡改。

### 11.2.2 事件记录格式（JSONL）

```json
{
  "ts": "2026-09-08T12:34:56.789Z",
  "seq": 42,
  "kind": "file_write",
  "actor": "user:alice",
  "resource": "/path/to/file",
  "outcome": "ok",
  "detail": {...},
  "prev_hash": "sha256:<64 hex>",
  "hash": "sha256:<64 hex>"
}
```

### 11.2.3 核心 API

```python
from agent.audit_log import AuditLog, AuditChainError

log = AuditLog()

# 记录事件
log.record(kind="file_write", actor="user:alice",
           resource="/path/to/file", outcome="ok", detail={...})

# 验证哈希链完整性
log.verify()  # 被篡改则抛出 AuditChainError

# 日志轮转（创建新链）
log.rotate()

# 查询事件
events = log.query(kind="file_write", limit=100)
```

### 11.2.4 安全特性

| 特性 | 说明 |
|------|------|
| 追加写 | 无公开 API 删除事件 |
| 哈希链 | SHA-256(prev_hash ‖ json(event))，篡改即断链 |
| 线程安全 | RLock + per-file Lock 序列化写 |
| 零依赖 | 仅 stdlib，可运行在最小容器中 |

---

## 11.3 Langfuse Integration（Langfuse 链路追踪）

### 11.3.1 设计目标

通过 HTTP 直连 Langfuse API 实现 LLM 可观测性，支持 trace/span 上报、批量缓冲、异步后台队列。

### 11.3.2 环境变量

```bash
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=https://cloud.langfuse.com  # 可选，默认为官方服务
```

### 11.3.3 核心 API

```python
from agent.langfuse_integration import LangfuseTracer, langfuse_tracer

tracer = LangfuseTracer(public_key=..., secret_key=..., host=...)

# 追踪 LLM 调用
with tracer.start_span(name="llm_call", model="gpt-4o") as span:
    span.log_input("user message...")
    response = llm.chat(...)
    span.log_output(response.content)
    span.log_usage(usage.dict())

# 追踪工具调用
with tracer.start_span(name="tool_call", tool_name="file_read") as span:
    result = file_read(...)
    span.log_output(str(result))

# 全局追踪器
langfuse_tracer.log_llm_call(model="gpt-4o", messages=[...], response=response)
langfuse_tracer.log_tool_call(tool_name="shell", args={...}, result="...")
```

### 11.3.4 批量缓冲

- BATCH_SIZE = 100 条
- FLUSH_INTERVAL = 5 秒
- 后台线程异步发送，不阻塞 Agent 主循环

---

## 11.4 ErrorObservability（错误追踪 → Langfuse 桥接）

### 11.4.1 设计目标

将 `ErrorTracker` 的运行时错误事件转发到 Langfuse，与 AuditLog → Langfuse 桥接（`audit_observability.py`）形成完整的可观测性体系。

### 11.4.2 严重级别映射

| ErrorEvent.severity | Langfuse level |
|---------------------|----------------|
| `fatal` | ERROR |
| `error` | ERROR |
| `warning` | WARNING |
| `info` | DEFAULT |

### 11.4.3 核心 API

```python
from agent.error_observability import ErrorObserver, install_default_observer

# 手动挂载
observer = ErrorObserver(sample_rate=0.1)
tracker.attach_observer(observer)

# 自动挂载（推荐）
install_default_observer(sample_rate=1.0)

# 严重程度映射（fatal/error → ERROR，warning → WARNING，info → DEFAULT）
# 去重感知：当 fingerprint 已存在时，occurrence_count 作为 metadata 转发
```

---

## 11.5 SkillHotReload（技能热重载）

### 11.5.1 设计目标

技能文件变更时自动重新加载，无需重启 Agent 进程。适用于技能迭代开发阶段。

### 11.5.2 核心 API

```python
from agent.skill_hot_reload import SkillHotReloader, start_hot_reload

# 启动热重载监听
stop = start_hot_reload(skills_dir="~/.Zeloo/skills", on_change=callback)

# 手动触发重载
reloader = SkillHotReloader(skills_dir="~/.Zeloo/skills")
reloader.reload_all()

# 停止监听
stop()
```

### 11.5.3 实现机制

- 使用 `watchdog` 库监听文件变更事件
- 变更时清除技能缓存，重新从磁盘读取
- 回调函数可选择性刷新 Agent 的技能注册表

---

## 11.6 SkillWebhooks（技能远程 Webhook）

### 11.6.1 设计目标

支持将技能执行结果或状态变更推送到远程 Webhook URL，实现技能与外部系统（CI/CD、通知系统、监控系统）的集成。

### 11.6.2 核心 API

```python
from agent.skill_webhooks import SkillWebhooks, register_webhook, trigger_webhook

webhooks = SkillWebhooks()

# 注册 Webhook
webhooks.register(
    skill_name="python-testing",
    url="https://ci.example.com/webhook",
    events=["skill_executed", "skill_failed"],
    secret="shared-secret-for-hmac",
)

# 触发 Webhook
webhooks.trigger(
    skill_name="python-testing",
    event="skill_executed",
    payload={"result": "passed", "duration_ms": 1234},
)

# 列出所有 Webhook
for wh in webhooks.list():
    print(f"{wh.skill_name} -> {wh.url} ({wh.events})")
```

### 11.6.3 安全

- HMAC-SHA256 签名（`X-Skill-Signature` 头）
- TLS 传输（`https://` 强制）
- 超时控制（默认 10 秒）

---

## 11.7 CredentialCrypto（凭证加密）

### 11.7.1 设计目标

使用 AES-256-GCM 对 `~/.Zeloo/credentials.json` 中的敏感凭证进行加密存储，防止磁盘泄露导致密钥暴露。

### 11.7.2 核心 API

```python
from agent.credential_crypto import encrypt_value, decrypt_value, derive_key

# 从密码派生密钥（PBKDF2）
key = derive_key(password="your-password", salt=b"salt-16-bytes")

# 加密
ciphertext = encrypt_value(plaintext="sk-abc123...", key=key)

# 解密
plaintext = decrypt_value(ciphertext=ciphertext, key=key)
```

### 11.7.3 secfile 格式

凭证文件格式（兼容 Unix `pass` 工具的 secfile）：

```
openai
PASSAGE
protocol: AES256GCM
key_id: key-v1
ciphertext: base64-encoded-ciphertext
```

---

## 11.8 SecretScanner（密钥泄漏检测）

### 11.8.1 设计目标

在工具输出、文件内容、用户消息中扫描可能泄漏的 API 密钥、Token、证书等敏感信息，防止凭证通过 Agent 对话泄露。

### 11.8.2 支持模式

| 类型 | 正则模式 |
|------|----------|
| OpenAI Key | `sk-...` |
| Anthropic Key | `sk-ant-...` |
| AWS Key | `AKIA...` |
| GitHub Token | `gh[pousr]_...` |
| Private Key | `-----BEGIN.*PRIVATE KEY-----` |
| Generic Bearer | `Bearer [A-Za-z0-9_.-]+` |

### 11.8.3 核心 API

```python
from agent.secret_scanner import scan_for_secrets, SecretMatch

matches: list[SecretMatch] = scan_for_secrets(text="your api key is sk-abc123...")

for match in matches:
    print(f"{match.kind} at pos {match.start}-{match.end}")
    print(f"  Redacted: {match.redacted}")  # sk-***...
```

---

## 11.9 BackgroundReview（后台复盘）

### 11.9.1 设计目标

Agent 运行结束后在后台异步分析会话轨迹，提炼可复用知识、更新记忆、生成建议，为下一次会话提供更好的上下文。

### 11.9.2 核心 API

```python
from agent.background_review import BackgroundReview, schedule_review

reviewer = BackgroundReview()

# 安排复盘（异步执行，不阻塞返回）
schedule_review(session_id="sess-123", reviewer=reviewer)

# 复盘内容
# - 总结对话主题和关键结论
# - 提取关键决策和行动
# - 更新用户记忆（通过记忆后端）
# - 生成改进建议
```

---

## 11.10 RateLimiter（速率限制器）

### 11.10.1 设计目标

对 Provider API 调用实施速率限制，防止触发限流（429）并支持公平调度。

### 11.10.2 核心 API

```python
from agent.rate_limiter import RateLimiter, TokenBucket

limiter = RateLimiter()

# 按 Provider 限流
limiter.acquire("openai", tokens=1)  # 阻塞直到获取
limiter.try_acquire("openai", tokens=1)  # 非阻塞

# Token Bucket 算法
bucket = TokenBucket(capacity=60, refill_rate=60)  # 60 req/min
```

---

## 11.11 AdaptiveCompression（自适应压缩）

### 11.11.1 设计目标

根据上下文用量动态决定何时压缩、压缩哪些消息，平衡压缩质量与 token 节省。

### 11.11.2 核心 API

```python
from agent.adaptive_compression import AdaptiveCompressor

compressor = AdaptiveCompressor(
    target_ratio=0.5,    # 目标压缩到 50%
    min_messages=5,       # 至少保留 5 条消息
)

compressed = compressor.compress(messages, current_context_tokens=80000)
# 返回压缩后的 messages 列表
```

---

## 11.12 Estop（紧急停止）

### 11.12.1 设计目标

提供全局紧急停止能力，可立即终止所有 Agent 活动，不依赖线程中断（避免资源泄漏）。
停止信号在下一次迭代边界检查并退出，保证状态一致性。

### 11.12.2 集成位置

对话循环开头：

```python
# agent/conversation_loop.py
def run_conversation(self, message: str) -> str:
    if estop.is_stopped():
        return f"[emergency stop: {estop.get_reason()}]"

    while self.iteration_budget.remaining > 0:
        # ...主循环体
```

### 11.12.3 API

```python
from agent.estop import estop, EstopManager

# 触发停止（reason: str, by: str = "system"）
estop.trigger(reason="用户请求停止", by="user")

# 查询状态
if estop.is_stopped():
    print(estop.get_reason())  # "用户请求停止"

# 重置（解除停止）
estop.reset()

# 获取触发栈（嵌套触发时有用）
stack = estop.get_stack()  # [{"reason": ..., "by": ..., "ts": ...}]

# 全局单例
manager = EstopManager()
manager.trigger("安全威胁检测", by="security")
```

### 11.12.4 触发场景

| 场景 | by 字段 | 说明 |
|------|----------|------|
| 用户主动请求停止 | `user` | Ctrl+C 或 `/stop` |
| 安全威胁 | `security` | Prompt 注入、越权操作 |
| 资源耗尽 | `system` | 内存、磁盘告警 |
| 超时 | `timeout` | 会话超时 |

### 11.12.5 嵌套触发

支持栈式嵌套触发，`is_stopped()` 只读顶层状态，`reset()` 弹出栈顶：

```
trigger("reason A")      # stack: [A]
trigger("reason B")       # stack: [A, B]
is_stopped() → True      # 任一层触发则停止
reset()                  # stack: [A]  — 仍停止
reset()                  # stack: []    — 解除
```

---

## 11.13 Insights（运行时洞察）

### 11.13.1 设计目标

采集运行时指标（工具调用、错误分类、Token 用量、会话统计），在 Agent 运行时和结束时输出可操作的优化建议。

### 11.13.2 集成位置

工具执行时记录：

```python
# run_agent.py execute_tool()
insights.record_tool_call(tool_name, elapsed_ms, error=err)
```

### 11.13.3 采集指标

| 指标 | 记录时机 | 聚合方式 |
|------|----------|----------|
| `tool_call` | 每次工具调用 | 次数、平均耗时、错误率 |
| `tool_error` | 工具抛出异常 | 按 tool_name + error_type 聚合 |
| `llm_call` | 每次 LLM API 调用 | Token 用量、响应时长 |
| `session` | 会话开始/结束 | 会话数、迭代次数 |

### 11.13.4 API

```python
from agent.insights import Insights, insights

# 记录工具调用
insights.record_tool_call("file_read", elapsed_ms=120)

# 记录工具错误
insights.record_tool_error("shell", "TimeoutError")

# 记录 LLM 调用
insights.record_llm_call(
    model="gpt-4o",
    input_tokens=800,
    output_tokens=400,
    latency_ms=850,
)

# 生成报告
report = insights.generate_report()
# {
#   "summary": {"total_calls": 24, "total_iterations": 8},
#   "top_tools": [...],
#   "top_errors": [...],
#   "token_usage_hourly": {...},
#   "recommendations": ["file_read 错误率偏高，建议检查路径解析"]
# }

# 持久化到文件
insights.persist()
```

### 11.13.5 自动建议

基于采集数据自动生成优化建议：

| 触发条件 | 建议内容 |
|----------|----------|
| 某工具错误率 > 10% | 检查工具实现或参数格式 |
| Token 用量 > 5000/轮 | 建议开启上下文压缩 |
| 无效重试 > 3 次 | 检查 Provider 状态或切换 Key |
| 某 Provider 错误集中 | 建议检查 API Key 或降级到备用 Provider |

---

## 11.14 i18n（国际化）

### 11.14.1 设计目标

基于 YAML 的轻量国际化系统，核心场景是网关消息和 CLI 输出的多语言支持。
语言包位于 `locales/` 目录，每个语言一个 YAML 文件。

### 11.14.2 语言文件格式

```yaml
# locales/en.yaml
hello: "Hello, {name}!"
tool_call_failed: "Tool '{tool}' failed: {error}"
not_authorized: "You are not authorized to use this service."
internal_error: "An internal error occurred. Please try again."
error_rate_limit: "Rate limited, retrying in {seconds}s"

# locales/zh-CN.yaml
hello: "你好，{name}！"
tool_call_failed: "工具 '{tool}' 执行失败：{error}"
not_authorized: "您没有权限使用此服务。"
internal_error: "发生内部错误，请稍后重试。"
error_rate_limit: "触发限流，{seconds} 秒后重试"
```

### 11.14.3 API

```python
from agent.i18n import gettext, set_language, get_available_languages

# 设置语言
set_language("zh-CN")

# 翻译（支持 {var} 占位符）
gettext("hello", name="Alice")  # "你好，Alice！"

# 获取当前语言
from agent.i18n import current_language
print(current_language())  # "zh-CN"

# 列出可用语言
print(get_available_languages())  # ["en", "zh-CN"]
```

### 11.14.4 网关集成

网关和所有平台适配器的内部错误消息均已接入 i18n：

```python
# gateway/run.py
from agent.i18n import gettext

def _t(key: str, **kwargs: object) -> str:
    try:
        return gettext(key, **kwargs)
    except Exception:
        return key  # fallback to key itself

# 网关初始化时从 config 读取语言
gateway = Gateway(config)
# config["gateway"]["i18n"]["default_language"] 或 config["language"]

# 平台适配器内部错误
from agent.i18n import gettext
reply = gettext("internal_error")
```

### 11.14.5 线程安全

每个线程可独立设置语言（使用 `contextvars`），主 Agent 和子 Agent 互不影响。

---

## 11.15 CredentialPool（凭证池）

### 11.15.1 设计目标

集中管理多 Provider 的 API Key，支持多 Key 轮询、自动熔断（永久禁用认证失败 Key）和冷却恢复（临时禁用非致命错误 Key）。

### 11.15.2 核心能力

| 能力 | 说明 |
|------|------|
| **多 Key 轮询** | 同一 Provider 配置多个 Key，round-robin 轮换 |
| **永久熔断** | 401/403 认证失败 → 永久禁用该 Key |
| **冷却恢复** | 限流/超时等非致命错误 → 临时禁用（默认 300s），到期自动恢复 |
| **失败计数** | 累计失败达阈值（默认 3 次）→ 永久禁用 |
| **环境变量回退** | 池中无可用 Key → 回退到 `zeloo_<PROVIDER>_API_KEY` |
| **加密持久化** | 凭证存储在 `~/.Zeloo/credentials.json`（权限 0600） |

### 11.15.3 API

```python
from agent.credential_pool import CredentialPool

pool = CredentialPool(
    storage_path="~/.Zeloo/credentials.json",
    cooldown_seconds=300,
    max_failures=3,
)

# 添加 Provider 的多个 Key
pool.add_provider_keys("openai", ["sk-abc", "sk-def", "sk-ghi"])

# 获取可用 Key（自动跳过禁用/冷却中的 Key）
key = pool.get_key("openai")  # 返回 "sk-abc" 或 None

# 报告成功（重置失败计数）
pool.report_success("openai", key)

# 报告失败（401 → 永久熔断；其他 → 冷却）
pool.report_failure("openai", key, status_code=429)

# 强制禁用 Key
pool.disable_key("openai", key, permanent=True)

# 强制启用 Key
pool.enable_key("openai", key)
```

### 11.15.4 Provider Router 集成

```python
# agent/provider_router.py
class ProviderRouter:
    def __init__(self, config: dict):
        self._pool = CredentialPool.from_config(config.get("credential_pool", {}))

    def resolve(self, provider: str) -> str:
        key = self._pool.get_key(provider)
        if key:
            return key
        # fallback to environment variable
        return os.environ.get(f"zeloo_{provider.upper()}_API_KEY", "")

    def _on_provider_error(self, provider: str, status_code: int):
        key = self.resolve(provider)
        self._pool.report_failure(provider, key, status_code=status_code)
```

---

## 11.16 ErrorClassifier（错误分类器）

### 11.16.1 设计目标

将 Provider 返回的异常和 LLM 错误响应转化为结构化分类，提供统一的重试/降级策略，指导 Provider Router 的行为。

### 11.16.2 错误类别

| 类别 | 触发条件 | 可重试 | 降级 Provider |
|------|----------|--------|---------------|
| `AUTH` | 401/403、invalid api key | 否 | 是 |
| `RATE_LIMIT` | 429、rate limit 提示 | 是（30s 延迟） | 是 |
| `TIMEOUT` | 超时异常 | 是（10s 延迟） | 是 |
| `SERVER_ERROR` | 5xx 响应 | 是（5s 延迟） | 是 |
| `CONTEXT_OVERFLOW` | context length exceeded | 是（压缩后） | 否 |
| `CONTENT_FILTER` | content policy violation | 否 | 否 |
| `NETWORK` | 连接错误 | 是（5s 延迟） | 是 |
| `VALIDATION` | 400/422 参数错误 | 否 | 否 |

### 11.16.3 API

```python
from agent.error_classifier import classify_error, ErrorResult

result: ErrorResult = classify_error(
    exception=exc,
    provider="openai",
    status_code=429,
    response_text="rate limit exceeded",
)

print(result.category)              # "RATE_LIMIT"
print(result.retryable)             # True
print(result.should_fallback_provider)  # True
print(result.retry_delay_seconds)   # 30
print(result.message)               # "Rate limited, retrying in 30s"
```

### 11.16.4 Provider Router 集成

```python
# agent/provider_router.py
def _call_with_error_handling(self, payload: dict) -> dict:
    try:
        return self._call(payload)
    except Exception as exc:
        result = classify_error(
            exc,
            provider=self._provider,
            status_code=getattr(exc, "status_code", None),
        )
        if not result.retryable:
            # 不可重试 → 直接抛出
            raise
        # 可重试 → 等待后重试
        time.sleep(result.retry_delay_seconds)
        if result.should_fallback_provider:
            self.switch_to_next_provider()
        return self._call_with_error_handling(payload)
```

### 11.16.5 配置

```yaml
# config.yaml
error_classifier:
  enabled: true
  rate_limit_window_seconds: 60
  max_retries_per_provider: 3
```

---

## 11.17 CostTracker（Token 成本跟踪）

### 11.17.1 设计目标

`agent/cost_tracker.py` 从 LLM 响应的 `usage` 对象中提取 token 数量，结合内置定价表计算会话的美元成本。

### 11.17.2 内置定价表

| 模型 | 输入 $/1M | 输出 $/1M |
|------|-----------|-----------|
| gpt-4o | 2.50 | 10.00 |
| gpt-4o-mini | 0.15 | 0.60 |
| o1 | 15.00 | 60.00 |
| claude-3-5-sonnet | 3.00 | 15.00 |
| deepseek-chat | 0.14 | 0.28 |
| gemini-1.5-flash | 0.075 | 0.30 |

未知模型使用默认定价：`$5.00 / $15.00`。定价为近似值，配置按需更新。

### 11.17.3 API

```python
from agent.cost_tracker import CostTracker, get_model_price

# 查定价
price = get_model_price("gpt-4o")  # → (2.5, 10.0)

# 会话成本跟踪
tracker = CostTracker(model="gpt-4o")
tracker.record_usage(response.usage)
print(tracker.summary())
# Tokens: 1,250 (in=800, out=450, cached=200) | Cost: $0.0041 (in=$0.0020, out=$0.0045)
```

### 11.17.4 缓存 Token 处理

`record_usage()` 自动识别三种缓存 token 格式：
- OpenAI：`prompt_tokens_details.cached_tokens`
- Anthropic：`cache_read_input_tokens`
- 缓存 token 按 10% 价格计费

---

## 11.18 RuntimeCWD（运行时工作目录解析）

### 11.18.1 设计目标

`agent/runtime_cwd.py` 统一解析 Agent 的运行时工作目录，用于上下文文件发现（AGENTS.md/.cursorrules）和文件工具的基准路径。

### 11.18.2 解析优先级

```
1. TERMINAL_CWD 环境变量（最高）
2. set_context_cwd() 编程覆盖
3. launch 时 os.getcwd()（兜底）
```

### 11.18.3 API

```python
from agent.runtime_cwd import set_context_cwd, resolve_context_cwd, resolve_agent_cwd

# 编程设置（CLI/TUI 启动时调用）
set_context_cwd("/path/to/project")

# 上下文发现用（可为 None）
cwd = resolve_context_cwd()  # → Path("/path/to/project") 或 None

# Agent 自身工作目录（永不为 None）
agent_cwd = resolve_agent_cwd()  # → Path
```

### 11.18.4 与上下文文件的关系

上下文文件（AGENTS.md 等）在 `resolve_context_cwd()` 指向的目录中搜索。Agent 在不同项目目录中启动时，自动切换上下文。

---

## 11.19 Curator（技能生命周期管理）

### 11.19.1 设计目标

管理技能的完整生命周期，确保技能库始终保持高质量。状态机：`active → stale → archived`，永不删除。

### 11.19.2 状态机

```
active ──(N 天未使用)──► stale ──(M 天仍未使用)──► archived
  ▲                         │                          │
  └──── 使用技能重新激活 ◄────┴──────────────────────────┘
```

### 11.19.3 API

```python
from agent.curator import Curator, SkillLifecycle

curator = Curator(skills_dir="~/.Zeloo/skills")

# 跟踪技能使用
curator.track_usage("python-testing")  # → active

# 运行生命周期评估（定期调用）
curator.run_cycle()  # 更新所有技能状态

# 查询技能状态
state = curator.get_state("python-testing")
# SkillLifecycle.ACTIVE

# 强制归档
curator.archive("unused-skill")

# 获取过时技能列表（stale 或 archived）
old_skills = curator.get_stale_skills()
```

### 11.19.4 Skill 工具集成

```python
# tools/skills_tool.py 中 skill_view 实现
def skill_view(name: str) -> str:
    # 技能被使用时自动激活
    curator = get_curator()
    curator.track_usage(name)
    # ...返回技能内容
```

### 11.19.5 状态文件

状态存储在 `~/.Zeloo/skills/.curator_state.json`：

```json
{
  "python-testing": {
    "state": "active",
    "last_used": "2026-09-07T10:30:00Z",
    "use_count": 42
  },
  "old-skill": {
    "state": "archived",
    "last_used": "2026-06-01T08:00:00Z",
    "use_count": 3
  }
}
```

### 11.19.6 配置

```yaml
curator:
  enabled: true
  stale_after_days: 30      # N 天未使用 → stale
  archive_after_days: 90    # M 天仍未使用 → archived
```

---

## 11.20 Kanban（多智能体看板）

### 11.20.1 设计目标

持久化多智能体协作看板，支持复杂任务的分工与追踪。隔离模型：`Board`（硬边界）→ `Tenant`（软命名空间）→ `Worker`。

### 11.20.2 核心机制

| 机制 | 说明 |
|------|------|
| **心跳** | Worker 定期调用 `heartbeat(task_id)` 报告存活 |
| **僵尸检测** | 超过 `zombie_timeout_seconds` 无心跳 → 自动回收 |
| **重试预算** | 失败任务自动重试，超过 `max_retries` → BLOCKED |
| **优先级排序** | 按 priority + created_at 排序 |
| **幻觉门控** | 检测重复已完成任务，阻止重复执行 |

### 11.20.3 工具 API

```python
# kanban_create
kanban_create(name: str, tenant: str = "default") -> str

# kanban_list
kanban_list(tenant: str = "default") -> list[dict]

# kanban_show
kanban_show(board_id: str) -> dict

# kanban_assign
kanban_assign(task_id: str, worker_id: str) -> str

# kanban_complete
kanban_complete(task_id: str, result: str) -> str

# kanban_heartbeat
kanban_heartbeat(task_id: str) -> str
```

### 11.20.4 任务状态流转

```
todo ──assign──► in_progress ──complete──► completed
  ▲                  │
  │                  └──fail──► todo (retry) / blocked (exhausted)
  └──── reclaim zombie ────────┘
```

### 11.20.5 配置

```yaml
kanban:
  enabled: true
  zombie_timeout_seconds: 300
  default_max_retries: 3
```

---

## 11.21 Hooks（生命周期钩子）

### 11.21.1 设计目标

在 Agent 运行的关键节点注入回调，实现观测、修改或拦截操作。
提供统一的事件调度机制。

### 11.21.2 钩子类型

| 钩子 | 签名 | 触发时机 |
|------|------|----------|
| `PRE_TOOL_CALL` | `(tool_name, args) -> dict \| None` | 工具执行前，返回值覆盖 args |
| `POST_TOOL_CALL` | `(tool_name, args, result) -> Any` | 工具执行后，返回值覆盖 result |
| `PRE_LLM_CALL` | `(messages, tools) -> tuple \| None` | LLM 调用前，返回值覆盖 messages/tools |
| `POST_LLM_CALL` | `(response) -> dict \| None` | LLM 调用后，返回值覆盖 response |
| `ON_SESSION_START` | `(session_id) -> None` | 会话创建 |
| `ON_SESSION_END` | `(session_id) -> None` | 会话结束 |
| `TRANSFORM_OUTPUT` | `(content) -> str` | 最终输出文本转换 |

### 11.21.3 API

```python
from plugins.hooks import HookType, HookRegistry

registry = HookRegistry()

# 注册钩子
registry.register(
    HookType.PRE_TOOL_CALL,
    my_callback,
    plugin_name="my_plugin",
)

# 执行钩子链
result = registry.fire(
    HookType.PRE_TOOL_CALL,
    tool_name="file_read",
    args={"path": "/tmp/test.txt"},
)

# 移除钩子
registry.unregister(HookType.PRE_TOOL_CALL, "my_plugin")
```

### 11.21.4 run_agent.py 集成

```python
# PRE_TOOL_CALL / POST_TOOL_CALL
def execute_tool(self, tool_name: str, args: dict) -> Any:
    # pre
    self._hooks.fire(HookType.PRE_TOOL_CALL, tool_name=tool_name, args=args)
    # 执行
    result = self._tool_registry.execute(tool_name, **args)
    # post
    self._hooks.fire(HookType.POST_TOOL_CALL, tool_name=tool_name, args=args, result=result)
    return result

# PRE_LLM_CALL / POST_LLM_CALL
def call_llm(self, messages: list, tools: list) -> dict:
    # pre
    self._hooks.fire(HookType.PRE_LLM_CALL, messages=messages, tools=tools)
    response = self._client.chat.completions.create(messages=messages, tools=tools)
    # post
    self._hooks.fire(HookType.POST_LLM_CALL, response=response)
    return response
```

### 11.21.5 错误处理

钩子回调中的异常被捕获并记录，不中断 Agent 运行：

```python
try:
    callback(args)
except Exception:
    logger.warning("Hook %s failed: %s", name, exc)
```

---

## 11.22 记忆后端完整对比

支持 9 个记忆后端：

| 后端 | 类型 | 说明 | 配置 key |
|------|------|------|----------|
| LocalFile | 本地文件 | MEMORY.md / USER.md（默认） | `provider: local` |
| Honcho | 对话式建模 | 会话用户画像 | `provider: honcho` |
| Mem0 | 向量检索 | 语义记忆搜索 | `provider: mem0` |
| Supermemory | 全平台同步 | 跨设备记忆 | `provider: supermemory` |
| OpenViking | 开源后端 | REST API | `provider: openviking` |
| Byterover | 字节跳动 | REST API namespace | `provider: byterover` |
| Hindsight | 回溯式 | SDK 调用 | `provider: hindsight` |
| Holographic | 全息关联 | SDK 调用 | `provider: holographic` |
| RetainDB | SQLite | 持久化 DB | `provider: retaindb` |

### 11.22.1 RetainDB 详情

RetainDB 是 Zeloo 补充的记忆后端，使用 SQLite 持久化：

```python
from agent.memory_providers import RetainDBProvider

provider = RetainDBProvider(
    db_path="~/.Zeloo/retain.db",
    user_id="default",
    max_chars=8000,
)

provider.write("context", "User prefers concise responses")
content = provider.read("context")  # "User prefers concise responses"
```

表结构：

```sql
CREATE TABLE memories (
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, kind)
);
```

所有后端均支持无凭据时自动 fallback 到 LocalFileProvider，保证系统始终可用。

---

## 11.23 消息平台适配器完整列表

Zeloo 实现 18 个平台适配器（另有 CLI/TUI/API 内置）：

### 国际平台（13 个）

| 平台 | 类名 | 接入方式 | 协议特性 |
|------|------|----------|----------|
| Telegram | `TelegramAdapter` | Bot API | Webhook + Long Polling |
| Discord | `DiscordAdapter` | Bot API | Webhook |
| Slack | `SlackAdapter` | Bot API | Webhook + signing secret |
| WhatsApp | `WhatsAppAdapter` | Business API | Webhook + verify token |
| Signal | `SignalAdapter` | Bot API | Webhook |
| Microsoft Teams | `TeamsAdapter` | Bot Framework | OAuth2 + activity JSON |
| Matrix | `MatrixAdapter` | Client-Server API | Long polling /sync |
| Google Chat | `GoogleChatAdapter` | Bot API | JWT bearer auth |
| SMS (Twilio) | `SMSAdapter` | REST API | Basic Auth |
| IRC | `IRCAdapter` | IRC Protocol | TCP socket |
| LINE | `LINEAdapter` | Messaging API | HMAC-SHA256 + reply token |
| Mattermost | `MattermostAdapter` | Bot API | Bearer token |
| Home Assistant | `HomeAssistantAdapter` | Webhook | Bearer token |

### 国内平台（3 个）

| 平台 | 类名 | 接入方式 | 协议特性 |
|------|------|----------|----------|
| 飞书 | `FeishuAdapter` | Event Subscription + Open API | URL verification |
| 钉钉 | `DingTalkAdapter` | Custom Robot | HMAC-SHA256 + access token |
| 企微 | `WeComAdapter` | WeCom Open API | SHA1 signature |

### 通用适配器（3 个）

| 平台 | 类名 | 接入方式 | 协议特性 |
|------|------|----------|----------|
| QQ Bot | `QQBotAdapter` | QQ Bot API | HMAC-SHA256 + access token |
| Email | `EmailAdapter` | SMTP/IMAP | TLS + OAuth2 |
| Webhook Base | `WebhookBaseAdapter` | HTTP Webhook | 自定义签名 |

### 适配器开发规范

所有适配器统一实现以下接口：

```python
class PlatformAdapter(ABC):
    @abstractmethod
    def start(self, handler: Callable[[str, str, str], str]) -> None:
        """启动平台适配器，注册消息回调"""

    @abstractmethod
    def stop(self) -> None:
        """停止适配器，释放资源"""

    @abstractmethod
    def send_message(self, user_id: str, text: str) -> None:
        """发送消息到指定用户"""

    @abstractmethod
    def parse_incoming(self, body: bytes, headers: dict) -> tuple[str, str] | None:
        """解析传入消息，返回 (user_id, text) 或 None"""
```

适配器注册到 `gateway/platform_registry.py`，由 `gateway/run.py` 的 `_build_adapter()` 根据配置实例化。
