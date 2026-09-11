"""Final verification of zeloo_cli/core exports."""

from zeloo_cli.core import __all__ as EXPORTS

print("=" * 60)
print("zeloo_cli/core 完整导出验证")
print("=" * 60)
print(f"总导出数量: {len(EXPORTS)}")
print("\n全部导出列表:")

# 按字母顺序排序
for i, name in enumerate(sorted(EXPORTS), 1):
    print(f"  {i:3d}. {name}")

# 按 Phase 分组
phase1 = {
    "EventBus", "Event", "Subscription",
    "Scheduler", "ScheduledTask",
    "Cache", "CacheEntry", "TTLCache",
    "RateLimiter", "RateLimitResult", "RateLimitStrategy",
    "CircuitBreaker", "CircuitBreakerOpen", "CircuitState", "CircuitStats",
    "Task", "TaskQueue", "TaskResult", "TaskStatus",
    "Middleware", "MiddlewareChain", "RequestContext", "ResponseContext",
    "LoggingMiddleware", "AuthMiddleware", "TimingMiddleware",
    "Tenant", "TenantContext", "TenantManager",
    "RealtimeEngine", "SubscriptionChannel",
}
phase2 = set(EXPORTS) - phase1
print(f"\nPhase 1 (基础架构): {len(phase1)} 个")
print(f"Phase 2 (可观测性 + 安全 + 扩展): {len(phase2)} 个")
print(f"Phase 1 + Phase 2 合计: {len(EXPORTS)} 个")
