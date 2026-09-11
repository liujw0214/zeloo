"""Zeloo CLI core framework — enterprise building blocks.

Phase 1 (基础架构):
- event_bus: Publish/subscribe event system
- scheduler: Background task scheduler
- cache: LRU + TTL cache
- rate_limiter: Token bucket / sliding window rate limiting
- circuit_breaker: Resilient service call protection
- task_queue: Async task queue with worker pool
- middleware: Request/response middleware pipeline
- multi_tenant: Tenant isolation and routing
- realtime_engine: WebSocket/SSE realtime push

Phase 2 (可观测性 + 安全 + 扩展):
- tracing: OpenTelemetry-compatible distributed tracing
- metrics: Counters, gauges, histograms
- feature_flags: Runtime feature toggles and A/B testing
- secrets: Encrypted credential storage with rotation
- lifecycle: Application startup/shutdown orchestration
- plugin_manager: Dynamic plugin loading
- state_store: Key-value state with TTL and atomic ops
"""

from __future__ import annotations

from zeloo_cli.core.cache import Cache, CacheEntry, TTLCache
from zeloo_cli.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitState,
    CircuitStats,
)
from zeloo_cli.core.event_bus import Event, EventBus, Subscription
from zeloo_cli.core.feature_flags import (
    FeatureFlag,
    FeatureFlagManager,
    FlagState,
)
from zeloo_cli.core.lifecycle import (
    LifecycleHook,
    LifecycleManager,
    LifecyclePhase,
)
from zeloo_cli.core.metrics import (
    HistogramStats,
    MetricPoint,
    MetricsCollector,
)
from zeloo_cli.core.middleware import (
    AuthMiddleware,
    LoggingMiddleware,
    Middleware,
    MiddlewareChain,
    RequestContext,
    ResponseContext,
    TimingMiddleware,
)
from zeloo_cli.core.multi_tenant import (
    Tenant,
    TenantContext,
    TenantManager,
)
from zeloo_cli.core.plugin_manager import (
    PluginInfo,
    PluginManager,
    PluginState,
)
from zeloo_cli.core.rate_limiter import (
    RateLimiter,
    RateLimitResult,
    RateLimitStrategy,
)
from zeloo_cli.core.realtime_engine import (
    RealtimeEngine,
    SubscriptionChannel,
)
from zeloo_cli.core.scheduler import (
    ScheduledTask,
    Scheduler,
)
from zeloo_cli.core.secrets import Secret, SecretManager
from zeloo_cli.core.state_store import StateEntry, StateStore
from zeloo_cli.core.task_queue import (
    Task,
    TaskQueue,
    TaskResult,
    TaskStatus,
)
from zeloo_cli.core.tracing import Span, Tracer

__all__ = [
    # Phase 1
    "EventBus",
    "Event",
    "Subscription",
    "Scheduler",
    "ScheduledTask",
    "Cache",
    "CacheEntry",
    "TTLCache",
    "RateLimiter",
    "RateLimitResult",
    "RateLimitStrategy",
    "CircuitBreaker",
    "CircuitBreakerOpen",
    "CircuitState",
    "CircuitStats",
    "Task",
    "TaskQueue",
    "TaskResult",
    "TaskStatus",
    "Middleware",
    "MiddlewareChain",
    "RequestContext",
    "ResponseContext",
    "LoggingMiddleware",
    "AuthMiddleware",
    "TimingMiddleware",
    "Tenant",
    "TenantContext",
    "TenantManager",
    "RealtimeEngine",
    "SubscriptionChannel",
    # Phase 2
    "Span",
    "Tracer",
    "MetricsCollector",
    "MetricPoint",
    "HistogramStats",
    "FeatureFlag",
    "FeatureFlagManager",
    "FlagState",
    "Secret",
    "SecretManager",
    "LifecycleManager",
    "LifecyclePhase",
    "LifecycleHook",
    "PluginManager",
    "PluginInfo",
    "PluginState",
    "StateStore",
    "StateEntry",
]