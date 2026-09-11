---
name: performance-tuning
description: 通过 profile → identify → optimize → measure 闭环定位并消除性能瓶颈，覆盖 CPU/内存/IO/数据库
platforms: [cli, tui, api]
toolsets: [file, terminal, code_execution]
---

# Performance Tuning

系统化的性能调优：先**测量**、再**定位**、再**优化**、最后**回归**。绝不在没有数据的情况下拍脑袋优化。

## Triggers（触发条件）

- "optimize performance" / "speed up" / "profile" / "performance issue"
- "性能调优" / "太慢了" / "卡顿" / "延迟高"

## 工作流程（PIOM 闭环）

```
Profile → Identify → Optimize → Measure
   ↑                              │
   └──────────── 回归不达标 ──────┘
```

### 1. Profile —— 测量基线

**不要凭感觉**。先采数据，定基线。

| 维度 | 工具 |
|---|---|
| CPU（Python） | `cProfile` / `py-spy dump` / `scalene` |
| CPU（Node） | `clinic flame` / `0x` / `--prof` |
| 内存 | `memory_profiler` / `tracemalloc` / `memray` |
| 数据库 | `EXPLAIN ANALYZE` / `pg_stat_statements` / 慢查询日志 |
| 网络 | `curl -w` / Wireshark / `tcpdump` |
| 端到端 | `locust` / `k6` / `wrk` |

输出基线报告：

```yaml
baseline:
  endpoint: POST /v1/search
  p50: 380ms
  p95: 1200ms
  p99: 2400ms
  qps: 120
  cpu: 65%
  memory: 1.2GB
```

### 2. Identify —— 定位瓶颈

二八法则：**20% 的代码占用 80% 的时间**。

- 火焰图找出 hot path
- DB 慢查询按 `total_time` 排序
- 内存增长区分：泄漏（持续涨）vs 峰值（一次性）
- 网络：DNS / TLS / 等待 / 上行 / 下行 分段计时

### 3. Optimize —— 优化手段

按**性价比**从高到低：

#### 算法与数据结构

- O(n²) → O(n log n)：双层循环换成 hash map
- 列表查找 → set / dict
- 排序前先 filter

#### 缓存

- 进程内 LRU（`functools.lru_cache`、`@cached`）
- 分布式缓存（Redis），注意**缓存穿透 / 击穿 / 雪崩**
- 缓存策略：Cache-Aside、Write-Through、Write-Behind

#### 并发

- CPU 密集：多进程 `multiprocessing` / `ProcessPoolExecutor`
- IO 密集：协程 `asyncio` / `aiohttp`
- 不要无脑加线程，注意 GIL（Python）和锁竞争

#### 数据库

- 加索引：先 `EXPLAIN`，确认走索引
- 改写 SQL：避免 `SELECT *`、避免 `IN (子查询)`、避免跨表大 JOIN
- 分页优化：cursor 替代 offset
- 批量：`executemany` / `COPY` 替代逐行
- 连接池：调优 `pool_size` / `max_overflow`

#### IO 与网络

- 合并小请求（`Promise.all` / `asyncio.gather`）
- HTTP keep-alive、HTTP/2
- 异步写日志
- 压缩（gzip / brotli）但只压文本

#### 内存

- 流式处理大文件（`for line in file`）
- `__slots__` 替代 dict（大量小对象）
- 生成器替代列表（一次性消费场景）
- 显式 `del` 大对象 + `gc.collect()` 仅在必要

#### 前端

- 首屏关键路径 inline
- 图片懒加载 + WebP / AVIF
- 代码分割、tree shaking
- 减少重排重排（读后写、写后读批处理）

### 4. Measure —— 回归验证

- 跑同一基准，对比基线
- 目标：p95 下降 ≥ 30% 才算"显著"
- 同时验证**没有引入回归**（其他指标变差）

## 工具集成

```python
# agent/cost_optimizer.py  —— 模型调用成本分析
# tools/code_execution_rpc.py —— 沙箱基准执行
# agent/token_aware_trimmer.py —— token 优化

from agent.cost_optimizer import estimate_cost, find_expensive_calls
from tools.code_execution_rpc import run_benchmark

def optimize_pipeline():
    expensive = find_expensive_calls(top_n=10)
    for call in expensive:
        alt = propose_alternative(call)
        run_benchmark(call, alt)  # 对比耗时与结果
```

## 报告模板

```markdown
## Performance Optimization Report

### Baseline
- p50 / p95 / p99
- QPS / CPU / Memory

### Findings
1. `users.py:118` —— N+1 查询，每次请求触发 24 次 SELECT
2. `cache.py:55` —— 未设置 TTL，键空间无限增长
3. `serialize.py:30` —— 同步 pickle 阻塞 event loop

### Changes
- 加 `prefetch_related` 消除 N+1
- 引入 LRU + TTL 上限
- 异步序列化

### After
- p50: 380ms → 95ms  (-75%)
- p95: 1200ms → 280ms (-77%)
- p99: 2400ms → 510ms (-79%)
- QPS: 120 → 480      (+300%)

### Risks
- 缓存一致性需观察 24h
- 异步化后日志顺序可能乱序
```

## 反模式

| 反模式 | 修正 |
|---|---|
| 没有 profile 就优化 | 先测量 |
| 优化冷路径 | 优先优化 hot path |
| 微基准脱离业务 | 端到端测试 |
| 优化可读性换性能 | 留注释、性能数字 |
| 全局加锁解决竞争 | 缩小锁粒度 |
| 缓存一切 | 评估命中率、TTL、一致性 |
| 用线程解决 IO 密集 | 用 asyncio |
| 忽略 N+1 | 用 prefetch / JOIN |
| 在生产"悄悄"调参数 | 走变更、走评审 |

## Examples

### 案例：消除 N+1

```python
# Before —— N+1
def get_orders_with_items(user_id):
    orders = db.query(Order).filter_by(user_id=user_id).all()
    for o in orders:
        o.items = db.query(OrderItem).filter_by(order_id=o.id).all()
    return orders

# After —— 一次 JOIN
def get_orders_with_items(user_id):
    return (
        db.query(Order)
        .options(selectinload(Order.items))
        .filter_by(user_id=user_id)
        .all()
    )
```

效果：N+1 → 1 次查询；p95 从 800ms 降到 60ms。

## 验证

- 性能指标达到目标
- 正确性测试全部通过
- 内存峰值在限额内
- 长时间压测无泄漏、无 OOM
- 灰度上线、监控核心指标 24h
