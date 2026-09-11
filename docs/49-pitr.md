# 49. SQLite PITR — 基于 WAL 归档的任意时间点恢复

## 49.1 概述

`zeloo_state/pitr.py` 在 `BackupManager`（每小时 / 每天全量快照）之上，
提供**任意时间点恢复（Point-In-Time Recovery）**：

> 给定目标时间戳 T，恢复到 DB 在 T 时刻的状态。

实现思路：**snapshot + WAL segment 重放**。
备份间隔（粗粒度）+ WAL 归档间隔（细粒度）= 完整恢复窗口。

## 49.2 两层保护模型

```
         ┌────────────────────┐
         │  Live DB + WAL     │  every N min
         └────────┬───────────┘ ──archive_segment──▶ ┌────────────┐
                  │                                   │ wal-archive │
                  │ snapshot 1×/day                  │  segments   │
                  ▼                                   └────────────┘
         ┌────────────────────┐
         │   snapshots/       │
         │  YYYYMMDD-HHMM.sqlite
         └────────────────────┘
```

| 层 | 频率 | 用途 | 大小 |
|----|------|------|------|
| Snapshot | 每 1 小时 / 1 天 | 基础锚点 | 全 DB 大小 |
| WAL segment | 每 5 分钟 | 恢复窗口 | 增量（KB-MB） |

恢复过程：

1. 找 ≤ 目标时间 T 的最新 snapshot S；
2. 原子安装 S；
3. 找 `[S.recorded_at, T]` 区间内、按时间排序的 WAL segments；
4. 按序应用每个 segment（写 `*.db-wal`，删除 `*.db-shm`）。

## 49.3 存储格式

### 49.3.1 Segment 文件

文件名：`wal-{start_ts}-{end_ts}.bin`

| 字段 | 字节 | 类型 | 说明 |
|------|------|------|------|
| magic | 4 | `b"ZWAL"` | 段标识符 |
| version | 4 | uint32 LE | 当前 = 1 |
| start_ts | 8 | int64 LE | segment 窗口起点 |
| end_ts | 8 | int64 LE | segment 窗口终点 |
| payload | N | bytes | 原 `*.db-wal` 文件内容（不含 SQLite WAL header 之后的全部） |

总 header = 24 字节（`_HEADER_STRUCT.size`）。

### 49.3.2 为什么需要自定义 header

直接保存 `*.db-wal` 字节流也可以，但加入 header 的好处：

1. **强校验**：`magic` + `version` 让归档工具能立刻识别坏段；
2. **时间窗口**：恢复算法 `O(segments)` 内做窗口判定，无需 mtime 排序；
3. **可观测**：从文件名即可看出 PITR 覆盖范围；
4. **未来扩展**（schema_version / checksum / encryption 等）。

### 49.3.3 写入流程

```python
header = _header_bytes(start_ts, end_ts)
target = archive_dir / f"wal-{start_ts}-{end_ts}.bin"
target_partial = target.with_suffix(target.suffix + ".partial")
target_partial.write_bytes(header + wal_payload)
Path(target_partial).replace(target)  # 原子 rename
```

任何写入失败 → `.partial` 被删除，不污染 archive_dir。

## 49.4 `PITREngine` API

| 方法 | 行为 |
|------|------|
| `archive_segment(start_ts, end_ts)` | 抓取 live WAL → 写 segment，返回 `ArchiveResult` |
| `list_segments()` | 返回按 start_ts 排序的 `SegmentInfo` 列表 |
| `cleanup(max_age_seconds, keep_count)` | 按年龄 / 数量阈值删除 |
| `restore_to(target_ts, snapshot_path=None)` | 恢复到目标时刻 |
| `coverage_window()` | 返回 `(earliest_ts, latest_ts)`，供"能恢复到何时"展示 |

### 49.4.1 `archive_segment`

参数：

* `start_ts` — 默认 `end_ts - 300`（5 分钟窗口）；
* `end_ts` — 默认 `time.time()`。

行为：

* 如果 `*.db-wal` 不存在或只有 SQLite header（≤ 32 bytes），返回
  `None` —— 没有需要归档的内容；
* 否则写入 `{header}{raw_wal_payload}`；
* 估算 `page_count = (size - header - wal_header) / page_size`，
  4 KiB 估算（仅供日志使用，不参与校验）。

### 49.4.2 `restore_to`

算法：

1. 选 snapshot：调用 `_pick_snapshot(target_ts, snapshot_path=…)`：
   * 若 `snapshot_path` 显式给出，校验 mtime ≤ target_ts；
   * 否则扫描 `snapshot_dir/*.sqlite`，选 ≤ target_ts 中最新的；
2. `_install_snapshot(snap_path)`：原子安装（同 `BackupManager.restore`）：
   * 把 live DB / `-wal` / `-shm` 移到临时目录；
   * 拷贝 snapshot 到 `db_path`；
   * 失败时回滚；
3. `_segments_for_window(snap, target_ts)`：选出 `start_ts ≥ snap_ts` 且
   `end_ts ≤ target_ts` 的 segments；
4. 对每个 segment 调 `_apply_segment`：写 `*.db-wal` = 删 `*.db-shm`。
   下次 DB 打开时 SQLite 自动 replay。

返回 `RestoreResult` 包含：snapshot 路径、应用的 segments、耗时。

### 49.4.3 `cleanup`

按双条件清理：

* `max_age_seconds`：segment.end_ts 早于该阈值 → 候选删除；
* `keep_count`：无论如何至少保留最新的 N 个。

优先保留最新的（不破坏恢复窗口）。

## 49.5 调度建议

### 49.5.1 归档调度

```python
# 每 5 分钟触发一次
while True:
    result = engine.archive_segment()
    sleep(300)
```

* 建议 `start_ts = previous_end_ts`（无缝窗口）；
* 若 segment 内容为空，下一轮直接跳过。

### 49.5.2 保留策略

| 参数 | 推荐 | 含义 |
|------|------|------|
| `keep_count` | 288 (= 24h × 60min / 5min) | 至少保留一天窗口 |
| `max_age_seconds` | 7 × 86400 = 604800 | 一周后丢弃 |

恢复窗口：**至少 1 天**（因为 keep_count 起作用）。

### 49.5.3 与 Snapshot 配合

| Snapshot 频率 | WAL 频率 | 恢复窗口 | 成本 |
|---------------|----------|----------|------|
| 1 × /day | 1 × /5min | 24h+ | 低 |
| 1 × /hour | 1 × /5min | 1h 增量 | 中 |
| 1 × /hour | 1 × /min | 1h 增量 | 较高 |

推荐：1 × /hour snapshot + 1 × /5min WAL。

## 49.6 失败模式矩阵

| 失败 | 检测点 | 行为 |
|------|--------|------|
| snapshot 文件丢失 / 损坏 | `restore_to` 时 `_install_snapshot` 跑 `integrity_check` | `RuntimeError` 抛出 |
| segment 文件缺失 | `_segments_for_window` 静默跳过 | 恢复到 snapshot 时间点 |
| segment header 损坏 | `_parse_header` 抛 `ValueError` | `list_segments` 跳过该文件、warning 日志 |
| snapshot 时间晚于 target | `_pick_snapshot` 检查 | `ValueError("newer")` |
| WAL payload 不完整 | 仅依赖 SQLite 自己 replay | 下次打开失败 → 由 `BackupManager.verify` 重试 |
| 磁盘空间耗尽 | `archive_segment` 写失败 | 抛异常，`.partial` 被清掉 |
| archive_dir 与 snapshot_dir 冲突 | 默认不同子目录 | 不冲突 |

## 49.7 安全考虑

* **明文 WAL 落盘**：当前 segment 文件未加密。如果 snapshot 推到
  异地存储（OSS / S3），WAL segment 也应当走相同通道加密。R49
  未实现 on-segment 加密；Round 50 计划用 `Fernet` 加密 segment payload
  （与 `credential_crypto` 复用密钥栈）。
* **目标时间戳可信**：restore_to 接受任意 timestamp，不校验"用户能否
  还原到 1970"。上层 CLI / API 应当做权限控制。
* **原子 rename 失败**：极端情况下（如只读 fs）`Path.replace` 会
  抛 `OSError`，调用方决定重试 / 报错。

## 49.8 测试覆盖

`tests/unit/test_pitr.py` 覆盖：

* **header round-trip**（4 测试）：magic / version / 长度校验；
* **archive algorithm**（7 测试）：列出、排序、损坏段跳过、
  cleanup（年龄 + count）、coverage_window、空 WAL 跳过；
* **archive end-to-end**（3 测试，Windows 跳过）：写 segment、
  部分写失败清理、可重新解析 header；
* **restore end-to-end**（6 测试，Windows 跳过）：选最新 snapshot、
  显式 snapshot、拒绝未来 snapshot、无 snapshot 报错、
  应用匹配 segment、跳过窗口外 segment。

合计 **20 个测试**（Windows 下 11 个算法测试运行 + 9 个跳过）。

## 49.9 已知限制

* **不解析 WAL frames**：直接把 SQLite 的 WAL payload 复制到
  `*.db-wal`，靠 SQLite 自己 replay。这意味着：
  * segment 必须用对应 schema 的 snapshot 才能正确 replay；
  * 不支持跨 schema_version 恢复。
* **PITR 不是高可用**：只是数据保护，恢复需要停机（虽然时间很短）。
* **WAL 帧解析能力缺失**：未来想做"前向 replay 验证"（在归档前先
  replay snapshot + segment 来确认能恢复到目标），需要解析 WAL
  frames。当前实现依赖 SQLite 自己的 replay。

## 49.10 未来扩展（Round 50+）

1. **Segment 加密** — 用 `credential_crypto` 中的 Fernet key 加密 payload；
2. **异地 push** — segment 写完后异步推到 OSS / S3；
3. **PITR 演练 cron** — 每天在 staging 跑一次"恢复到 24h 前 → 校验
   数据一致性 → 删除"，验证真实可用性；
4. **时间线查询 API** — `GET /state/timeline?from=...&to=...` 返回
   可恢复的时间点序列。