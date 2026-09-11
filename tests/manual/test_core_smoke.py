"""Smoke tests for zeloo_cli/core modules.

Can be run as a standalone script (``python test_core_smoke.py``) or
collected by pytest.  All test functions return ``None`` so pytest does not
emit ``PytestReturnNotNoneWarning``.  The ``main()`` runner treats a
successful run (no exception) as a pass.
"""

from __future__ import annotations

from zeloo_cli.core import (
    AuthMiddleware,
    Cache,
    CircuitBreaker,
    EventBus,
    FeatureFlagManager,
    FlagState,
    LifecycleManager,
    LifecyclePhase,
    LoggingMiddleware,
    MetricsCollector,
    MiddlewareChain,
    PluginManager,
    RateLimiter,
    RateLimitStrategy,
    RealtimeEngine,
    Scheduler,
    SecretManager,
    StateStore,
    TenantManager,
    TimingMiddleware,
    Tracer,
    TTLCache,
)


def test_event_bus() -> None:
    bus = EventBus()
    received: list = []
    bus.subscribe("test.topic", lambda e: received.append(e.data))
    bus.publish("test.topic", {"k": "v"}, synchronous=True)
    assert received == [{"k": "v"}], f"got {received}"


def test_ttl_cache() -> None:
    cache = TTLCache(default_ttl_seconds=60)
    cache.set("k", "v")
    assert cache.get("k") == "v"
    cache.delete("k")
    assert cache.get("k") is None


def test_cache() -> None:
    cache = Cache(max_size=100)
    cache.set("k", "v")
    assert cache.get("k") == "v"
    stats = cache.stats()
    assert stats["hits"] == 1
    cache.get_or_compute("computed", lambda: "result")
    assert cache.get("computed") == "result"


def test_rate_limiter() -> None:
    limiter = RateLimiter(
        capacity=5, strategy=RateLimitStrategy.TOKEN_BUCKET
    )
    results = [limiter.check().allowed for _ in range(7)]
    assert results[:5] == [True] * 5
    assert results[5:] == [False, False]


def test_circuit_breaker() -> None:
    cb = CircuitBreaker(name="test", failure_threshold=3)
    result = cb.call(lambda: "ok")
    assert result == "ok"
    assert cb.state.value == "closed"


def test_scheduler() -> None:
    scheduler = Scheduler()
    scheduler.schedule_interval("test", lambda: None, 60.0)
    assert len(scheduler.list_tasks()) == 1
    scheduler.cancel(scheduler.list_tasks()[0].task_id)
    assert len(scheduler.list_tasks()) == 0


def test_state_store() -> None:
    store = StateStore()
    store.set("k", "v1")
    assert store.get("k") == "v1"
    assert store.compare_and_swap("k", "v1", "v2") is True
    assert store.get("k") == "v2"
    assert store.compare_and_swap("k", "wrong", "v3") is False
    snap = store.snapshot()
    store.clear()
    store.restore(snap)
    assert store.get("k") == "v2"


def test_tracer() -> None:
    tracer = Tracer()
    with tracer.span("op1") as sp:
        sp.set_tag("env", "test")
        sp.add_event("started")
    assert len(tracer.get_recent_spans()) == 1


def test_metrics() -> None:
    metrics = MetricsCollector()
    metrics.counter("req", 1, ep="/api")
    metrics.counter("req", 1, ep="/api")
    assert metrics.get_counter("req", ep="/api") == 2
    metrics.gauge("temp", 25.5)
    assert metrics.get_gauge("temp") == 25.5
    for v in [10, 20, 30, 40, 50]:
        metrics.histogram("lat", v)
    stats = metrics.get_histogram_stats("lat")
    assert stats.count == 5
    assert stats.p50 == 30


def test_feature_flags() -> None:
    fm = FeatureFlagManager()
    fm.create_flag("feat", state=FlagState.ENABLED)
    assert fm.is_enabled("feat") is True
    fm.disable("feat")
    assert fm.is_enabled("feat") is False
    fm.set_percentage("feat", 100.0)
    assert fm.is_enabled("feat", "any_user") is True


def test_secret_manager() -> None:
    sm = SecretManager(encryption_key="testkey")
    sm.set("api", "secret123")
    assert sm.get("api") == "secret123"
    sm.rotate("api", "new_secret")
    assert sm.get("api") == "new_secret"
    assert sm.rotate("nonexistent", "x") is False


def test_tenant_manager() -> None:
    tm = TenantManager()
    t = tm.create_tenant("acme", config={"plan": "ent"})
    assert t.name == "acme"
    with tm.context(t.tenant_id) as ctx:
        assert ctx.tenant.name == "acme"
    assert len(tm.list_tenants()) == 1


def test_lifecycle_manager() -> None:
    lm = LifecycleManager()
    lm.on_starting(lambda: None, "logger")
    lm.on_stopping(lambda: None, "closer")
    assert lm.startup() is True
    assert lm.phase == LifecyclePhase.RUNNING
    assert lm.shutdown() is True
    assert lm.phase == LifecyclePhase.STOPPED


def test_plugin_manager() -> None:
    pm = PluginManager()
    assert len(pm.list_plugins()) == 0


def test_realtime_engine() -> None:
    engine = RealtimeEngine()
    received: list = []
    engine.subscribe("ch", lambda d: received.append(d))
    engine.publish("ch", {"msg": "hello"})
    assert len(received) == 1


def test_middleware() -> None:
    chain = MiddlewareChain()
    chain.add(LoggingMiddleware())
    chain.add(AuthMiddleware(required_token=""))
    chain.add(TimingMiddleware())
    ctx, resp = chain.execute(
        __import__("zeloo_cli.core.middleware", fromlist=["RequestContext"])
        .RequestContext(method="GET", path="/test"),
        lambda c: {"ok": True},
    )
    assert resp.status_code == 200
    assert "X-Powered-By" in resp.headers
    assert "X-Response-Time" in resp.headers


def main() -> None:
    tests = [
        ("EventBus", test_event_bus),
        ("TTLCache", test_ttl_cache),
        ("Cache", test_cache),
        ("RateLimiter", test_rate_limiter),
        ("CircuitBreaker", test_circuit_breaker),
        ("Scheduler", test_scheduler),
        ("StateStore", test_state_store),
        ("Tracer", test_tracer),
        ("MetricsCollector", test_metrics),
        ("FeatureFlagManager", test_feature_flags),
        ("SecretManager", test_secret_manager),
        ("TenantManager", test_tenant_manager),
        ("LifecycleManager", test_lifecycle_manager),
        ("PluginManager", test_plugin_manager),
        ("RealtimeEngine", test_realtime_engine),
        ("Middleware", test_middleware),
    ]
    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
            print(f"  [PASS] {name}")
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")

    print(f"\n{passed}/{len(tests)} tests passed, {failed} failed")
    if failed > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
