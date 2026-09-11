# 48. Perf Baseline 对比自动报警

## 48.1 概述

`zeloo_cli/perf/baseline.py` 提供一套**性能基线（baseline）+ 回归检测
（regression detection）**框架，让 CI 在每次跑 perf 测试时自动对比
已知良好版本的测量结果，并按严重程度分级报警：

* **WARNING** — 软告警，仅写日志；
* **ERROR** — 阻断 CI（`zeloo perf check` 退出码非零）；
* **CRITICAL** — 更强阻断并配醒目提示语。

模块定位：**轻量、可读、可在 PR 中 review 的 JSON 基线 + 自适应阈值**。
不引入 pytest-benchmark 的二进制 blob，不依赖 git 历史，避免团队
规模化后跨平台比较的复杂性。

## 48.2 为什么需要 baseline 对比

| 现状 | 问题 |
|------|------|
| 硬编码阈值（`elapsed < 2.0`） | 跨平台漂移大；macOS / Linux / WSL 噪声不一致 |
| 每次只看绝对值 | 无法识别"相对退化"（如 412ms → 600ms） |
| 靠人工盯日志 | 无人 review 时悄悄回归，无报警 |

baseline 对比解决三个问题：

1. **跨平台可比性**：基线存储包含 `linux-x86_64-cpython-3.12` 之类的
   host class，可按环境隔离基线；
2. **相对退化感知**：-10% 即触发 WARNING，-25% ERROR；
3. **机器可读的报警**：`RegressionReport.overall_ok` + 三档严重度。

## 48.3 核心数据模型

### 48.3.1 `BenchmarkMeasurement`

```python
@dataclass(frozen=True)
class BenchmarkMeasurement:
    name: str          # e.g. "system_prompt.cold_build_ms"
    value: float       # canonical value (median of samples)
    unit: str          # "ms" | "ratio" | "bytes" | "s" | ...
    samples: tuple[float, ...]  # raw samples (optional)
```

### 48.3.2 `BenchmarkSuite`

一次完整 perf 运行的快照，落到内存中供 detector 比对：

```python
@dataclass
class BenchmarkSuite:
    suite_name: str                    # e.g. "system_prompt"
    measurements: list[BenchmarkMeasurement]
    host_class: str = ""               # see capture_host_class()
    recorded_at: float = 0.0
```

### 48.3.3 `Baseline`

存储在磁盘上的"已知良好版本"，可随 PR 更新：

```python
@dataclass
class Baseline:
    suite_name: str
    measurements: dict[str, dict[str, Any]]  # {name: {value, unit, samples}}
    recorded_at: float
    host_class: str = ""
```

JSON 文件结构：

```json
{
    "suite_name": "system_prompt",
    "host_class": "linux-x86_64-3.12.3",
    "recorded_at": 1700000000.0,
    "measurements": {
        "cold_build_ms": {"value": 412.0, "unit": "ms", "samples": []},
        "warm_cache_hit_ratio": {"value": 0.85, "unit": "ratio", "samples": []}
    }
}
```

## 48.4 `BaselineRegistry` — 基线存取

存储位置：

* 默认 `~/.Zeloo/perf-baselines/`，可通过 `ZELOO_PERF_BASELINES` 环境变量覆盖。
* 单文件 per suite：`{dir}/{suite_name}.json`。
* 文件名清洗：禁用 `/` `\` `..`，空名 → `ValueError`。

API：

| 方法 | 行为 |
|------|------|
| `save(baseline)` | 原子写（`.partial` + `Path.replace`），返回路径 |
| `load(suite_name)` | 读回 `Baseline`，缺失抛 `FileNotFoundError` |
| `exists(suite_name)` | bool |
| `list_suites()` | 字母序返回所有 suite |
| `delete(suite_name)` | 删除（idempotent），返回 bool |

### 48.4.1 原子写

```python
tmp = path.with_suffix(path.suffix + ".partial")
tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
Path(tmp).replace(path)  # 跨平台原子 rename（Windows 沙箱兼容）
```

失败时 `.partial` 文件由 `replace()` 之前的 `except` 块清理 —
不会留下脏文件。

## 48.5 `RegressionDetector` — 回归检测

### 48.5.1 阈值表（默认）

```python
DEFAULT_THRESHOLDS = {"warning": 10.0, "error": 25.0, "critical": 50.0}
```

可通过构造参数覆盖：

```python
det = RegressionDetector(thresholds={"warning": 5.0, "error": 15.0, "critical": 30.0})
```

### 48.5.2 单位方向感知

| 单位集合 | 方向 |
|----------|------|
| `s`, `ms`, `us`, `bytes`, `count` ... | lower-is-better |
| `ratio`, `rate`, `pct`, `percent` | higher-is-better |
| 未知单位 | 默认 lower（保守） |

detector 根据 `unit` 自动判断方向，无需调用方操心。

### 48.5.3 分类规则

```
direction = "lower"（数字应该小）:
    delta >= 0  → NONE（不坏或更好）
    |delta| >= 50%  → CRITICAL
    |delta| >= 25%  → ERROR
    |delta| >= 10%  → WARNING
    其余          → NONE

direction = "higher"（数字应该大）:
    delta <= 0  → NONE
    |delta| >= 50%  → CRITICAL
    ...
```

### 48.5.4 状态字段

每个 measurement 在 `regressions[name]` 里给出：

```json
{
    "status": "regression | improved | unchanged | within_noise | new | missing",
    "baseline_value": 412.0,
    "current_value": 540.0,
    "delta_pct": 31.07,
    "severity": "error",
    "unit": "ms",
    "direction": "lower"
}
```

* **regression** — 在错误方向上超过阈值；
* **improved** — 在正确方向上变化 ≥ 1%；
* **within_noise** — 在错误方向上但小于阈值；
* **new** — 当前 suite 有，baseline 没有（不算回归）；
* **missing** — baseline 有，当前 suite 没有（测试被删除）。

### 48.5.5 `overall_ok` 语义

```python
overall_ok = max_severity not in (ERROR, CRITICAL)
```

`WARNING` 仍算 `ok` —— 软告警，不阻断 CI。

## 48.6 `ignore` 列表

有些 measurement 在冷启动 CI runner 上不可重复（如 `import_time`），
需要在 CI 配置里排除：

```python
det = RegressionDetector(ignore=["import_*", "cold_start_ms"])
```

通配符 `*` 表示前缀匹配。

## 48.7 CLI 集成（计划）

> 待实现：增加 `zeloo perf check` 和 `zeloo perf baseline update` 子命令。

`zeloo perf check {suite_name}`：
1. 跑测试套件 → 得到 `BenchmarkSuite`
2. 加载 `BaselineRegistry` 中的同名基线
3. 跑 `RegressionDetector.compare()` → `RegressionReport`
4. 按 `overall_ok` 决定退出码
5. 把 report JSON 写到 `.Zeloo/perf-baselines/{suite}.report.json`

`zeloo perf baseline update {suite_name}`：
1. 跑测试套件
2. 把当前结果保存为新基线
3. 默认要求 `overall_ok == True` 才接受更新（带 `--force` 绕过）

## 48.8 测试覆盖

`tests/unit/test_perf_baseline.py` 覆盖：

* 注册表读写、原子 rename、路径清洗、列出 / 删除；
* measurement / suite / host 工具函数；
* detector 全部 4 档严重度 + 改善/变差方向；
* `ignore` 列表（具体名 + 前缀通配）；
* missing / new measurement 处理；
* 自定义阈值；
* 基线 = 0 的边界条件；
* 默认阈值常量 sanity。

合计 **22 个单元测试**。

## 48.9 失败模式矩阵

| 失败模式 | detector 行为 |
|---------|--------------|
| baseline 文件缺失 | `BaselineRegistry.load` 抛 `FileNotFoundError`，由 CLI 决定如何处理（一般是初始化空基线） |
| baseline JSON 损坏 | `json.JSONDecodeError`，CLI 应当 fall back 到硬阈值 |
| 当前 suite 缺 measurement | 标 `missing`，`severity = none` |
| baseline 缺 measurement | 标 `new`，`severity = none` |
| 单位缺失 / 拼写错误 | 视为 `lower-is-better`（保守） |
| 同一 measurement 在两边单位不一致 | 当前实现不强制一致；调用方负责规范单位 |
| baseline = 0 | delta_pct 强制 0（避免 div-by-zero） |

## 48.10 已知限制

* **跨次 run 不做统计聚合**：detector 比较单次 run vs baseline。
  多次 run 的中位数 / 方差稳定性留给上层 perf harness；
* **不支持基线漂移告警**：基线本身可能被刷"高"，导致 baseline 越来
  越松。建议每年或每次重大重构后从干净环境重新采集基线；
* **不持久化 report**：当前只输出到 stdout / 日志；如需历史趋势分析，
  可将 `RegressionReport` JSON 写入 `metrics` 表（见 `zeloo_cli/observability/`）。