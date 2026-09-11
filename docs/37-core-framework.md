# 37. Zeloo CLI 核心框架

> **zeloo_cli/core/** — 企业级应用运行时基础设施。
> 提供 16 个核心模块，覆盖事件驱动、调度、缓存、限流、断路器、任务队列、中间件、多租户、实时推送、可观测性、安全、生命周期、插件系统、状态存储等全部能力。

---

## 37.1 模块总览

| 类别 | 模块 | 导出类 | 用途 |
|------|------|--------|------|
| **事件驱动** | `event_bus.py` | `EventBus`/`Event`/`Subscription` | 发布订阅、异步派发 |
| **调度** | `scheduler.py` | `Scheduler`/`ScheduledTask` | 后台任务定时/周期/cron |
| **缓存** | `cache.py` | `Cache`/`TTLCache`/`CacheEntry` | LRU+TTL 缓存 |
| **限流** | `rate_limiter.py` | `RateLimiter`/`RateLimitStrategy` | 三种策略限流 |
| **弹性** | `circuit_breaker.py` | `CircuitBreaker`/`CircuitState` | 服务熔断保护 |
| **任务队列** | `task_queue.py` | `TaskQueue`/`Task`/`TaskStatus` | 异步任务队列 |
| **中间件** | `middleware.py` | `MiddlewareChain`/`LoggingMiddleware`/`AuthMiddleware`/`TimingMiddleware` | 请求中间件链 |
| **多租户** | `multi_tenant.py` | `TenantManager`/`Tenant`/`TenantContext` | 租户隔离 |
| **实时推送** | `realtime_engine.py` | `RealtimeEngine`/`SubscriptionChannel` | 频道订阅推送 |
| **追踪** | `tracing.py` | `Tracer`/`Span` | OpenTelemetry 兼容 |
| **指标** | `metrics.py` | `MetricsCollector`/`MetricPoint`/`HistogramStats` | Counter/Gauge/Histogram |
| **特性开关** | `feature_flags.py` | `FeatureFlagManager`/`FeatureFlag`/`FlagState` | 运行时开关/百分比发布 |
| **密钥** | `secrets.py` | `SecretManager`/`Secret` | 加密存储+轮换 |
| **生命周期** | `lifecycle.py` | `LifecycleManager`/`LifecyclePhase`/`LifecycleHook` | 应用状态机 |
| **插件** | `plugin_manager.py` | `PluginManager`/`PluginInfo`/`PluginState` | 动态加载+Hook |
| **状态存储** | `state_store.py` | `StateStore`/`StateEntry` | TTL+版本+CAS |

**总计**：**16 个模块**，**45 个公开类/枚举/函数**

---

## 37.2 快速开始

```python
from zeloo_cli.core import (
    EventBus, Cache, RateLimiter, CircuitBreaker,
    MetricsCollector, FeatureFlagManager, Tracer,
)

# 事件总线
bus = EventBus()

def on_user_login(event):
    print(f"User logged in: {event.data}")

bus.subscribe("user.login", on_user_login)
bus.publish("user.login", {"user_id": 123})

# 缓存
cache = Cache(max_size=1000, default_ttl_seconds=300)
cache.set("user:123", {"name": "Alice"})
user = cache.get("user:123")

# 限流
limiter = RateLimiter(capacity=10, strategy=RateLimitStrategy.TOKEN_BUCKET)
if limiter.check(user_id="alice").allowed:
    handle_request()

# 指标
metrics = MetricsCollector()
metrics.counter("api_requests", 1, endpoint="/users")
metrics.histogram("latency_ms", 123.4)
```

---

## 37.3 EventBus 事件总线

发布订阅模式，支持通配符和异步分发。

```python
from zeloo_cli.core import EventBus

bus = EventBus(max_workers=4)

# 订阅具体 topic
bus.subscribe("user.login", lambda e: print(e.data), async_mode=True)

# 订阅通配符
bus.subscribe("user.*", lambda e: print(f"User event: {e.topic}"))

# 发布事件
bus.publish("user.login", {"user_id": 123, "timestamp": time.time()})

# 同步等待
bus.publish("user.action", {"type": "click"}, synchronous=True)

# 历史回放
recent = bus.history(topic="user.login", limit=50)
```

**特性**：
- 通配符订阅（`*`, `prefix.*`, `*.suffix`）
- 同步/异步分发
- 事件过滤函数
- 历史回放（最近 1000 条）
- 线程安全的订阅管理

---

## 37.4 Cache 缓存层

LRU + TTL 双策略缓存。

```python
from zeloo_cli.core import Cache, TTLCache

# 简单 TTL 缓存（无淘汰）
ttl = TTLCache(default_ttl_seconds=300)
ttl.set("k", "v", ttl_seconds=60)

# LRU+TTL 缓存（含淘汰）
cache = Cache(max_size=1000, default_ttl_seconds=300)
cache.set("user:1", user_data)
val = cache.get("user:1", default=None)

# get_or_compute 自动缓存
result = cache.get_or_compute(
    "expensive_query",
    lambda: run_expensive_query(),
    ttl_seconds=600,
)

# 统计
print(cache.stats())
# {'size': 42, 'hits': 100, 'misses': 15, 'hit_rate': 0.87, ...}
```

**特性**：
- LRU 淘汰策略
- TTL 过期
- get_or_compute 自动缓存
- 命中率统计
- 线程安全

---

## 37.5 RateLimiter 限流器

三种策略：令牌桶、滑动窗口、固定窗口。

```python
from zeloo_cli.core import RateLimiter, RateLimitStrategy

# 令牌桶：允许突发
limiter = RateLimiter(
    capacity=100,
    refill_rate=10.0,  # 每秒补充 10 个
    strategy=RateLimitStrategy.TOKEN_BUCKET,
)

result = limiter.check("user_id", cost=1)
if result.allowed:
    return "OK"
else:
    return f"Rate limited, retry after {result.retry_after}s"

# 滑动窗口：精确控制
sliding = RateLimiter(
    capacity=100,
    window_seconds=60,
    strategy=RateLimitStrategy.SLIDING_WINDOW,
)
```

**特性**：
- 三种策略可选
- 多键隔离（每用户/每 IP 独立计数）
- 自动重试时间计算
- 固定/滑动/令牌桶

---

## 37.6 CircuitBreaker 断路器

保护下游服务，防止雪崩。

```python
from zeloo_cli.core import CircuitBreaker

breaker = CircuitBreaker(
    name="external_api",
    failure_threshold=5,
    recovery_timeout_seconds=30.0,
    success_threshold=2,
)

try:
    result = breaker.call(requests.get, "https://api.example.com/data")
except CircuitBreakerOpen:
    return "Service temporarily unavailable"

# 状态检查
if breaker.state == CircuitState.CLOSED:
    # 正常调用
    pass
elif breaker.state == CircuitState.OPEN:
    # 快速失败
    pass
```

**状态机**：
- `CLOSED` → 正常调用
- `OPEN` → 达到失败阈值后熔断
- `HALF_OPEN` → 超时后探测恢复

---

## 37.7 Scheduler 调度器

后台任务调度，支持间隔、cron、一次性。

```python
from zeloo_cli.core import Scheduler

scheduler = Scheduler()

# 每 60 秒运行一次
scheduler.schedule_interval("cleanup", cleanup_old_files, interval_seconds=60.0)

# Cron 表达式
scheduler.schedule_cron("daily_report", generate_report, cron_expr="0 9 * * *")

# 一次性延迟任务
scheduler.schedule_once("send_email", send_email, delay_seconds=3600)

scheduler.start()
```

**特性**：
- 间隔 / cron / 一次性任务
- 错误追踪 + 重试
- 任务统计（运行次数、最后错误）

---

## 37.8 TaskQueue 异步任务队列

带工作池的优先级任务队列。

```python
from zeloo_cli.core import TaskQueue

queue = TaskQueue(num_workers=4, max_queue_size=1000)

def process(data):
    return expensive_work(data)

task_id = queue.submit(
    process,
    "input_data",
    name="process_data",
    priority=5,
    max_retries=3,
    timeout=60.0,
)

result = queue.get_result(task_id, timeout=120)
print(f"Status: {result.status}, Result: {result.result}")
```

**特性**：
- 优先级队列
- 工作池并发
- 自动重试
- 超时控制
- 结果追踪

---

## 37.9 MiddlewareChain 中间件

请求/响应管道。

```python
from zeloo_cli.core import (
    MiddlewareChain, RequestContext, LoggingMiddleware,
    AuthMiddleware, TimingMiddleware,
)

chain = MiddlewareChain()
chain.add(LoggingMiddleware())
chain.add(AuthMiddleware(required_token="secret-token"))
chain.add(TimingMiddleware())

ctx = RequestContext(method="POST", path="/api/users")
ctx, response = chain.execute(ctx, lambda c: handle_request(c))

print(f"Status: {response.status_code}, Duration: {response.duration_ms}ms")
```

**内置中间件**：
- `LoggingMiddleware` — 请求日志
- `AuthMiddleware` — Bearer Token 认证
- `TimingMiddleware` — 响应时间

---

## 37.10 Multi-tenant 多租户

租户隔离和上下文管理。

```python
from zeloo_cli.core import TenantManager

tm = TenantManager()
acme = tm.create_tenant("acme", config={"plan": "enterprise"})

with tm.context(acme.tenant_id) as ctx:
    # 所有操作都在 acme 租户上下文中
    print(f"Current tenant: {ctx.tenant.name}")

# 切换租户
with tm.context(other_tenant_id) as ctx:
    print(f"Switched to: {ctx.tenant.name}")
```

---

## 37.11 RealtimeEngine 实时推送

频道订阅 + 异步推送。

```python
from zeloo_cli.core import RealtimeEngine

engine = RealtimeEngine()
engine.start()

def on_event(data):
    print(f"Received: {data}")

sub = engine.subscribe("notifications", callback=on_event)
engine.publish("notifications", {"msg": "Hello!"})

stats = engine.stats()
print(f"Channels: {stats['channels']}, Subscribers: {stats['total_subscribers']}")

engine.stop()
```

---

## 37.12 Tracer 分布式追踪

OpenTelemetry 兼容的 Span 追踪。

```python
from zeloo_cli.core import Tracer

tracer = Tracer(service_name="my-service")

with tracer.span("process_request", tags={"endpoint": "/api"}) as span:
    span.add_event("started")
    result = do_work()
    span.set_tag("result_size", len(result))
    span.record_error_if_failed()

# 查看追踪
for span in tracer.get_recent_spans(limit=10):
    print(f"{span.operation_name}: {span.duration_ms():.1f}ms")
```

---

## 37.13 MetricsCollector 指标收集

Counter / Gauge / Histogram。

```python
from zeloo_cli.core import MetricsCollector

metrics = MetricsCollector()

# Counter（单调递增）
metrics.counter("requests_total", 1, endpoint="/api")
metrics.counter("requests_total", 1, endpoint="/api")
assert metrics.get_counter("requests_total", endpoint="/api") == 2

# Gauge（瞬时值）
metrics.gauge("queue_size", 42)
metrics.gauge("cpu_usage", 0.78)

# Histogram（分布统计）
for ms in [10, 20, 30, 40, 100, 200]:
    metrics.histogram("latency_ms", ms)

stats = metrics.get_histogram_stats("latency_ms")
print(f"P50={stats.p50}, P95={stats.p95}, P99={stats.p99}")
```

---

## 37.14 FeatureFlagManager 特性开关

支持布尔、百分比、用户列表三种开关模式。

```python
from zeloo_cli.core import FeatureFlagManager, FlagState

fm = FeatureFlagManager()

# 简单开关
fm.create_flag("new_ui", state=FlagState.ENABLED)
if fm.is_enabled("new_ui"):
    render_new_ui()

# 灰度发布：50% 用户
fm.set_percentage("new_ui", 50.0)
if fm.is_enabled("new_ui", user_id="alice"):
    render_new_ui()

# 用户白名单
fm.create_flag(
    "beta_feature",
    state=FlagState.USER_LIST,
    allowed_users=["alice", "bob"],
)
```

---

## 37.15 SecretManager 密钥管理

XOR 加密 + 轮换 + 审计。

```python
from zeloo_cli.core import SecretManager

sm = SecretManager(encryption_key="my-secret-key")
sm.set("api_key", "sk-12345")
sm.set("db_pass", "password", expires_at=time.time() + 3600)

# 获取
key = sm.get("api_key")
password = sm.get("db_pass")  # None if expired

# 轮换
sm.rotate("api_key", "sk-67890")

# 审计
log = sm.audit_log(limit=10)
```

**特性**：
- XOR 加密（生产应使用 KMS/Vault）
- 自动过期
- 轮换追踪
- 访问审计
- 失败解密回退

---

## 37.16 LifecycleManager 生命周期

应用启动/关闭编排。

```python
from zeloo_cli.core import LifecycleManager, LifecyclePhase

lm = LifecycleManager()

def init_db():
    create_tables()

def init_logger():
    configure_logging()

def start_workers():
    spawn_background_workers()

def cleanup():
    close_connections()

lm.on_initializing(init_db, name="init_db", priority=10)
lm.on_starting(init_logger, name="init_logger", priority=20)
lm.on_starting(start_workers, name="start_workers", priority=100)
lm.on_stopping(cleanup, name="cleanup", priority=10)

lm.startup()  # 顺序执行所有 hook
# 应用运行中...
lm.shutdown()  # 顺序执行清理 hook
```

**生命周期阶段**：`CREATED → INITIALIZING → STARTING → RUNNING → STOPPING → STOPPED`

---

## 37.17 PluginManager 插件管理

动态加载 + 生命周期 + Hook 系统。

```python
# 加载文件中的插件
from zeloo_cli.core import PluginManager

pm = PluginManager()
plugin = pm.load_from_path(
    "/path/to/my_plugin.py",
    name="my_plugin",
)
pm.initialize("my_plugin")
pm.activate("my_plugin")

# 触发 Hook
results = pm.trigger_hook("on_message_received", message_data)

# 加载模块
pm.load_from_module("my_installed_plugin_module")

# 列出所有插件
for p in pm.list_plugins():
    print(f"{p.name} v{p.version}: {p.state.value}")
```

**插件约定**：
- 模块属性 `__version__`, `__description__`, `__author__`
- 可选函数：`initialize()`, `activate()`, `deactivate()`
- 可选函数：`register_hooks() -> Dict[str, Callable]`

---

## 37.18 StateStore 状态存储

键值存储，支持 TTL + 版本控制 + 原子 CAS。

```python
from zeloo_cli.core import StateStore

store = StateStore()

# 基本 CRUD
store.set("config:key", "value", ttl_seconds=3600)
val = store.get("config:key")

# 原子 CAS（Compare-And-Swap）
store.set("counter", 0)
while True:
    val, version = store.get_with_version("counter")
    if store.compare_and_swap(
        "counter", expected_value=val, new_value=val + 1,
        expected_version=version,
    ):
        break

# Snapshot / Restore
snap = store.snapshot()
store.clear()
store.restore(snap)

# 变更监听
def on_change(key, old, new):
    print(f"{key}: {old} → {new}")

store.add_change_listener(on_change)
store.set("counter", 1)  # triggers on_change
```

**特性**：
- TTL 过期
- 乐观并发控制（版本号）
- 原子 CAS 操作
- 快照/恢复
- 变更监听

---

## 37.19 集成示例

将所有模块组合成一个完整应用：

```python
from zeloo_cli.core import (
    LifecycleManager, EventBus, Cache, RateLimiter, CircuitBreaker,
    MetricsCollector, Tracer, FeatureFlagManager, SecretManager,
    StateStore, LoggerMiddleware, RealtimeEngine,
)

# 启动序列
lm = LifecycleManager()
bus = EventBus()
metrics = MetricsCollector()
tracer = Tracer(service_name="Zeloo-app")
flags = FeatureFlagManager()
secrets = SecretManager(encryption_key=os.environ["zeloo_SECRET_KEY"])
state = StateStore()
realtime = RealtimeEngine()
realtime.start()

# 注册启动钩子
lm.on_initializing(lambda: state.set("app.started_at", time.time()))
lm.on_starting(lambda: bus.publish("app.started"))
lm.on_starting(lambda: metrics.counter("app_starts"))

lm.startup()

# 业务调用
cache = Cache(max_size=10000)
rate_limiter = RateLimiter(capacity=100)
breaker = CircuitBreaker(name="api")

def handle_request(user_id: str, query: str):
    # 1. 限流
    if not rate_limiter.check(user_id).allowed:
        return {"error": "rate_limited"}

    # 2. 特性开关
    if flags.is_enabled("new_search", user_id):
        # 3. 追踪
        with tracer.span("new_search") as span:
            span.set_tag("user_id", user_id)
            # 4. 熔断保护
            result = breaker.call(search_with_new_algo, query)
    else:
        # 5. 缓存
        cache_key = f"search:{hash(query)}"
        result = cache.get(cache_key)
        if result is None:
            result = breaker.call(search_with_old_algo, query)
            cache.set(cache_key, result, ttl_seconds=3600)

    # 6. 指标
    metrics.counter("search_total", 1, user_id=user_id)
    metrics.histogram("search_latency_ms", time.time() - start)

    # 7. 实时推送
    realtime.publish("search.results", {"user_id": user_id, "query": query})

    return result

# 关闭序列
lm.shutdown()
realtime.stop()
```

---

## 37.20 总结

| 模块 | 类别 | 关键能力 |
|------|------|----------|
| **event_bus** | 事件 | 发布订阅 / 通配符 / 异步分发 |
| **scheduler** | 调度 | 间隔 / cron / 一次性 |
| **cache** | 缓存 | LRU + TTL + 统计 |
| **rate_limiter** | 限流 | 令牌桶 / 滑动 / 固定窗口 |
| **circuit_breaker** | 弹性 | 三态自动转换 |
| **task_queue** | 异步 | 优先级 + 工作池 + 重试 |
| **middleware** | 请求 | 管道 + 短路 |
| **multi_tenant** | 隔离 | 上下文 + 资源限制 |
| **realtime_engine** | 推送 | 频道 + 异步队列 |
| **tracing** | 可观测 | Span + Trace ID |
| **metrics** | 指标 | Counter/Gauge/Histogram |
| **feature_flags** | 开关 | 启用/百分比/白名单 |
| **secrets** | 安全 | 加密 + 轮换 + 审计 |
| **lifecycle** | 启动 | 6 阶段状态机 |
| **plugin_manager** | 扩展 | 动态加载 + Hook |
| **state_store** | 状态 | TTL + 版本 + CAS |

**zeloo_cli/core** 提供了一个完整的、生产级的运行时基础设施，与 Zeloo Agent 的 41 个 LLM Provider、39 个 Web Provider、65 个 MCP Server 完美配合！
