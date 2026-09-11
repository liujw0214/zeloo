# 性能调优指南

本文档涵盖 Zeloo 框架的性能基准测试方法、调优参数与最佳实践。

---

## 目录

1. [性能基准](#1-性能基准)
2. [Token 与成本优化](#2-token-与成本优化)
3. [并发与吞吐量](#3-并发与吞吐量)
4. [缓存策略](#4-缓存策略)
5. [数据库调优](#5-数据库调优)
6. [LLM 延迟优化](#6-llm-延迟优化)
7. [内存优化](#7-内存优化)
8. [CI 性能回归](#8-ci-性能回归)

---

## 1. 性能基准

### 1.1 运行基准测试

```bash
# 运行性能回归测试
pytest tests/unit/test_performance.py -v

# 运行响应时间基准
pytest tests/ -k "perf" --benchmark-only

# 完整基准套件（包含大压力测试）
pytest tests/integration/test_long_session_stability.py -v
```

### 1.2 关键性能指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 冷启动时间 | < 2s | 首次加载时间 |
| 热请求延迟 | < 500ms | LLM API P50 延迟 |
| 95th 延迟 | < 2s | LLM API P95 |
| 吞吐量 | > 10 req/s | 并发请求/秒 |
| 内存占用 | < 200 MB | 空闲 Agent 内存 |
| 成本 | 可追踪 | 每次调用记录成本 |

### 1.3 基准测试示例

```python
import time
import tracemalloc
from agent.cost_tracker import CostTracker

tracemalloc.start()

# 模拟 100 次 LLM 调用
tracker = CostTracker()
for i in range(100):
    tracker.record("gpt-4o-mini", input_tokens=200, output_tokens=80, provider="openai")

current, peak = tracemalloc.get_traced_memory()
print(f"Memory: {peak / 1024 / 1024:.1f} MB")
print(f"Total cost: ${tracker.get_total_cost():.4f}")
```

---

## 2. Token 与成本优化

### 2.1 Prompt 压缩

使用 `PromptCompressor` 减少 token 消耗：

```python
from agent.prompt_optimizer import PromptCompressor

compressor = PromptCompressor()
result = compressor.compress(
    "Please in a very polite manner can you kindly provide me with "
    "a summary of the main key points of this document..."
)
# result.compressed_text  → 减少约 30-50% token
# result.compression_ratio → 0.5~0.7
```

### 2.2 Few-Shot 示例选择

使用 `ExampleSelector` 选取最相关示例，减少上下文 token：

```python
from agent.prompt_optimizer import ExampleSelector

selector = ExampleSelector()
selection = selector.select(query="Python debugging", top_k=3)
# 仅注入最相关的 3 个示例，而非全部
```

### 2.3 成本追踪与告警

```python
from agent.cost_tracker import CostTracker

tracker = CostTracker(
    warn_threshold_usd=1.0,
    abort_threshold_usd=10.0,
)

# 环境变量覆盖阈值
os.environ["zeloo_COST_WARN_THRESHOLD"] = "2.0"
os.environ["zeloo_COST_ABORT_THRESHOLD"] = "20.0"

tracker.record("gpt-4o", input_tokens=5000, output_tokens=2000)
print(tracker.format_cost("CNY"))  # 人民币格式化输出
```

---

## 3. 并发与吞吐量

### 3.1 Rate Limiter 配置

```python
from zeloo.core.limiter import RateLimiter

# 全局速率限制
limiter = RateLimiter(
    max_calls=60,        # 每分钟最多 60 次
    window_seconds=60,
    strategy="sliding", # sliding / fixed
)

# 每个 Provider 独立限制
for provider in providers:
    limiter.register(f"provider:{provider.name}", max_calls=30, window_seconds=60)
```

### 3.2 Circuit Breaker 配置

```python
from zeloo.core.circuit_breaker import CircuitBreaker

cb = CircuitBreaker(
    failure_threshold=5,   # 5 次失败后断开
    recovery_timeout=30,   # 30 秒后尝试恢复
    expected_exception=Exception,
)

# 使用
with cb:
    result = provider.call()
```

### 3.3 批量请求合并

```python
from zeloo.core.batching import BatchProcessor

processor = BatchProcessor(max_size=10, max_wait_ms=100)

async def process():
    for item in items:
        processor.add(item)
    results = await processor.flush()
```

---

## 4. 缓存策略

### 4.1 LLM 响应缓存

```python
from agent.cache import ResponseCache

cache = ResponseCache(ttl_seconds=3600)  # 1 小时 TTL

# 缓存命中时直接返回
cache_key = cache.make_key(model, messages)
if cached := cache.get(cache_key):
    return cached

response = await llm.complete(messages)
cache.set(cache_key, response)
return response
```

### 4.2 记忆压缩与合并

```python
from agent.memory_consolidator import MemoryConsolidator

consolidator = MemoryConsolidator(
    similarity_threshold=0.85,
    max_entries=1000,
    importance_decay_days=30.0,
)

# 定期合并记忆
entries, stats = consolidator.consolidate(current_entries)
print(f"Merged: {stats['merged']}, Expired: {stats['expired']}")
```

---

## 5. 数据库调优

### 5.1 SessionDB 配置

```python
from agent.session_db import SessionDB

db = SessionDB(
    path="~/.Zeloo/sessions.db",
    wal_mode=True,     # WAL 模式提升并发读性能
    cache_size=10000, # 页面缓存大小
)
```

### 5.2 查询优化

```python
# 使用索引加速查询
# SessionDB 默认在 session_id, created_at 上有索引

# 分页获取（避免一次加载全部）
messages = db.get_messages(session_id, limit=100, offset=0)

# 定期清理旧数据
db.prune_messages(older_than_days=30)
```

### 5.3 全文本搜索

```python
# SessionDB 支持 FTS5 全文本搜索
results = db.search_messages(
    session_id=None,  # 全局搜索
    query="Python debugging",
    limit=20,
)
```

---

## 6. LLM 延迟优化

### 6.1 流式输出

```python
# 使用流式输出减少感知延迟（首 token 时间更短）
stream = llm.stream(messages)
for chunk in stream:
    print(chunk, end="", flush=True)
```

### 6.2 模型选择

| 场景 | 推荐模型 | 延迟 | 成本 |
|------|----------|------|------|
| 快速响应 | gpt-4o-mini | < 500ms | 低 |
| 平衡 | gpt-4o | < 1s | 中 |
| 高质量 | claude-3-5-sonnet | < 1.5s | 高 |
| 本地部署 | Ollama llama3 | < 100ms | 零 |

### 6.3 并行 API 调用

```python
import asyncio

async def parallel_calls():
    tasks = [
        llm.acomplete(messages, model="gpt-4o-mini"),
        search.search("query 1"),
        search.search("query 2"),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results
```

---

## 7. 内存优化

### 7.1 大会话处理

```python
# 不要一次性加载所有消息
messages = db.get_messages(session_id, limit=100)
while True:
    batch = db.get_messages(session_id, limit=100, offset=len(messages))
    if not batch:
        break
    messages.extend(batch)
    process(batch)  # 分批处理
```

### 7.2 对象池复用

```python
from agent.pool import ObjectPool

pool = ObjectPool(
    factory=lambda: ExpensiveObject(),
    max_size=10,
)

obj = pool.acquire()
try:
    obj.do_work()
finally:
    pool.release(obj)
```

### 7.3 监控内存使用

```python
import psutil
import os

process = psutil.Process(os.getpid())
print(f"RSS: {process.memory_info().rss / 1024 / 1024:.1f} MB")
print(f"VMS: {process.memory_info().vms / 1024 / 1024:.1f} MB")
```

---

## 8. CI 性能回归

### 8.1 性能基准测试 CI

```yaml
# .github/workflows/perf-regression.yml
name: Performance Regression

on:
  push:
    branches: [main]
  schedule:
    - cron: "0 3 * * *"  # 每天 3 AM

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install uv
      - run: uv sync --frozen
      - name: Run benchmarks
        run: |
          uv run pytest tests/ \
            --benchmark-json=benchmark.json \
            --benchmark-compare
      - name: Upload benchmark
        uses: benchmark-action/github-action-benchmark@v1
        with:
          tool: 'pytest'
          output-file-path: benchmark.json
          github-token: ${{ secrets.GITHUB_TOKEN }}
          auto-push: true
          alert-threshold: '150%'
          comment-on-alert: true
```

### 8.2 内存泄漏检测

```python
# tests/performance/test_memory_leak.py
import gc
import tracemalloc
import pytest

def test_no_memory_leak_in_session_loop():
    """验证连续 1000 次会话循环后内存不增长。"""
    tracemalloc.start()
    snapshot1 = tracemalloc.take_snapshot()

    for _ in range(1000):
        session = create_session()
        session.process("hello")
        session.close()

    gc.collect()
    snapshot2 = tracemalloc.take_snapshot()

    top_stats = snapshot2.compare_to(snapshot1, 'lineno')
    total_growth = sum(stat.size_diff for stat in top_stats[:10])

    assert total_growth < 1024 * 1024, f"Memory grew by {total_growth / 1024 / 1024:.1f} MB"
```

---

## 性能检查清单

- [ ] 冷启动 < 2s
- [ ] LLM P95 延迟 < 2s
- [ ] Token 成本追踪开启
- [ ] Rate Limiter 配置
- [ ] Circuit Breaker 开启
- [ ] 响应缓存启用
- [ ] 内存使用 < 200MB
- [ ] 无内存泄漏（1000+ 次循环）
- [ ] CI 性能基准已配置
