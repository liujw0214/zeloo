# 51. Off-Host Push — Snapshot / Segment 异地推送

## 51.1 概述

`zeloo_state/offhost.py` 定义 `OffHostPusher` 抽象 + 4 个实现（Local /
Null / S3 / OSS），让 `PITREngine.archive_segment()` 在本地写盘成功后
**异步**把 segment 推送到第二份存储：

* **LocalPusher**：第二块磁盘 / 第二个 mount point；
* **NullPusher**：tests / 显式禁用；
* **S3Pusher**：AWS S3 / MinIO / R2 / Backblaze B2（boto3，可选）；
* **OSSPusher**：Aliyun OSS（oss2，可选）。

本地 archive **仍然是 source of truth**；异地只是冗余拷贝，
单点故障（磁盘坏 / 误删 / ransomware / 机房失火）下还能恢复。

## 51.2 设计动机

| 故障 | 单副本风险 | Off-host 双副本 |
|------|----------|----------------|
| 磁盘损坏 | 永久丢失最后 N 小时 WAL | 异地副本可恢复 |
| 误操作 `rm -rf wal-archive` | 立即永久丢失 | 异地副本完好 |
| ransomware 加密 archive | 不可解密 / 不可恢复 | 异地副本（带版本）通常有冷备份 |
| 机房 / 机架失火 | 整机丢失 | 异地 + cold storage 安全 |
| 内部人员恶意删库 | 立即丢失 | 异地副本仍可审计 / 恢复 |

## 51.3 `OffHostPusher` 抽象

```python
class OffHostPusher(ABC):
    name: str = "abstract"

    @abstractmethod
    def push(self, local_path: Path, *, remote_key: str | None = None) -> PushResult

    def push_many(self, paths: list[Path], *, remote_prefix: str = "") -> list[PushResult]
```

返回值 `PushResult(source_path, remote_uri, duration_seconds, size_bytes)`
供 `metrics` / `observability` 模块汇总：每条异地 push 的延迟、字节数、
backend 类型都可以入 prometheus / otel。

`push_many` 的默认实现是顺序调用 `push`；子类可以重写为并行
（`concurrent.futures.ThreadPoolExecutor`）。

## 51.4 `LocalPusher`

```python
class LocalPusher(OffHostPusher):
    name = "local"
    def __init__(self, dest_dir: Path | str)
```

* `shutil.copy2` 保留 mtime / atime，便于审计；
* 自动 `mkdir -p`；
* 失败抛 `OffHostPushError`（底层 `OSError`）；
* 始终可用，无外部依赖；**测试只覆盖这个 backend**。

典型用法：

```python
pusher = LocalPusher("/mnt/secondary/wal-archive")
engine = PITREngine(db, cipher=cipher, pusher=pusher)
# 每个 archive_segment 自动 copy 到 /mnt/secondary/...
```

## 51.5 `NullPusher`

显式禁用的占位实现。把每次 push 调用记到 `self.pushed: list[Path]`
供 assertions 用，**线程安全**（`threading.Lock`）。测试场景和
"我希望先跑通本地 archive 但暂不接异地"的部署场景都用它。

## 51.6 `S3Pusher`

依赖可选 `boto3`：

```python
S3Pusher(
    bucket="my-backup-bucket",         # 或 OFFHOST_S3_BUCKET
    prefix="zeloo-state/",             # object-key 前缀
    endpoint_url="https://...",        # 可选：MinIO / R2 / B2
    region="us-east-1",                # 可选
    client=...,                        # 测试注入 stub
)
```

行为：

* **缺失 boto3**：构造时打印 warning，`push` 变成 no-op
  (`remote_uri = "s3://disabled"`)，**不抛错**——engine 不会因为
  缺 SDK 而崩。
* **缺 bucket**：同上 no-op。
* **运行时错误**（网络 / 5xx / throttle）：抛 `OffHostPushError`；
  engine 捕获并 log，本地 archive 保留。
* `boto3.Config(retries={"max_attempts": 3, "mode": "adaptive"})`
  让 SDK 内部自动重试瞬时错误。

认证：完全从 env 读取（`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` /
`AWS_SESSION_TOKEN` / `AWS_ENDPOINT_URL`），**不在 URL 或 query string
里携带凭证**。

## 51.7 `OSSPusher`

依赖可选 `oss2`，行为与 `S3Pusher` 平行：

```python
OSSPusher(
    bucket="my-oss-bucket",            # 或 OSS_BUCKET
    prefix="zeloo-state/",
    endpoint="https://oss-cn-hangzhou.aliyuncs.com",  # 或 OSS_ENDPOINT
    access_key_id="...",                # 或 OSS_ACCESS_KEY_ID
    access_key_secret="...",            # 或 OSS_ACCESS_KEY_SECRET
)
```

`put_object_from_file` 是单次 PUT；OSS 内部对 4xx / 5xx 自动重试由
SDK 控制。调用层抛错就抛 `OffHostPushError`，engine 不重试。

## 51.8 `build_default_pusher` 工厂

```python
build_default_pusher(
    *,
    local_dest: Path | None = None,
    prefer: str | None = None,
) -> OffHostPusher
```

解析顺序：

1. `prefer` 显式值 → 直接选；
2. `OFFHOST_BACKEND` env（`local` / `s3` / `oss` / `null`）→ 选 env；
3. `local_dest` 非空 → `LocalPusher`；
4. `OFFHOST_S3_BUCKET` 已设 + boto3 可用 → `S3Pusher`；
5. `OSS_BUCKET` 已设 + oss2 可用 → `OSSPusher`；
6. 默认 → `NullPusher`（避免调用方判 None）。

`prefer="local"` 但没传 `local_dest` → 抛 `ValueError`，**绝不像 env 那样降级到 NullPusher**，避免"以为开了异地实际没开"的事故。

## 51.9 `PITREngine` 集成

```python
def __init__(
    self,
    db_path,
    *,
    archive_dir=None,
    snapshot_dir=None,
    cipher=None,
    pusher=None,                 # ← Round 50
    push_prefix="wal/",          # ← Round 50
)
```

`archive_segment()` 流程（增量）：

1. 抓 live WAL bytes；
2. cipher（若有）→ envelope = flag + 密文；
3. 写 `{header}{envelope}` 到 `archive_dir/wal-{start}-{end}.bin`
   （原子 rename + .partial 清理）；
4. **若配置 pusher**：调 `_push_offhost(target, segment_name)`；
5. 返回 `ArchiveResult`。

`_push_offhost` 是 best-effort：

```python
try:
    self._pusher.push(local_path, remote_key=f"{self._push_prefix}{segment_name}")
except Exception as exc:
    logger.warning("off-host push failed for %s: %s (local copy retained)",
                   segment_name, exc)
```

**不抛错，不重试**。理由：

* archive 是同步的 cron-like 任务，重试失败会拖慢整个循环；
* 本地副本完好，下次 schedule 自然覆盖；
* 真要异步重试可以另起后台线程（Round 51+ 计划）。

`push_prefix` 默认 `"wal/"`，可以把 snapshot 和 segment 分开：

```python
pusher = LocalPusher("/mnt/backup")
engine = PITREngine(db, pusher=pusher, push_prefix="wal/")    # wal/...
backup_mgr = BackupManager(db, pusher=pusher, push_prefix="snapshots/")  # snapshots/...
```

## 51.10 失败模式矩阵

| 场景 | engine 行为 |
|------|------------|
| `pusher is None` | 不调用 push，正常返回 `ArchiveResult` |
| pusher `push` 抛 `OffHostPushError` | log + 返回 `ArchiveResult`（本地已存档） |
| pusher 抛 `Exception`（其他） | 同上（被 `except Exception` 捕获） |
| pusher 临时不可用（连续 N 次） | 同上；运维侧可通过 `NullPusher.pushed` 之外的指标告警（Round 51+ 加 prom counter） |
| 推送到 OSS 但 bucket 不存在 | 4xx → `OffHostPushError` → log |
| 推送网络中断 | 5xx → boto3 自动重试 3 次 → 仍失败则 `OffHostPushError` → log |

**关键不变量**：engine 从不因异地失败而抛出异常。`PITREngine.archive_segment()`
的返回值保证本地 archive 存在；异地成功与否是 observability 的事。

## 51.11 安全考虑

| 项 | 保证 |
|----|------|
| 凭证传输 | 全部从 env 读取，不入 URL / 不入 log |
| 通道加密 | TLS-only endpoints；不允许 `http://` / `oss://` 内网明文 |
| 静态加密 | 推送的是 Round 50 §50 的 ciphertext（如果 cipher 已配置） |
| 凭证泄露 | 不会通过 pusher 上传到 bucket；CI 用 IAM role 代替 long-lived key |
| 审计 | `PushResult.duration_seconds` / `size_bytes` 暴露给 metrics，可检测异常 |

## 51.12 测试覆盖

`tests/unit/test_offhost.py`：24 个测试

* `TestLocalPusher`（7）— copy、mkdir、missing source、remote_key、
  mtime 保留、`OffHostPushError` 透传、`push_many`；
* `TestNullPusher`（3）— records、missing、thread-safety；
* `TestS3PusherDisabled`（1）— boto3 缺失；
* `TestOSSPusherDisabled`（3）— oss2 缺失 / env 全无 / env 部分；
* `TestS3PusherWithClient`（3）— 注入 stub client、remote_key、
  upload failure；
* `TestBuildDefaultPusher`（7）— 全 null / explicit local /
  prefer override / local 缺 dest / null 强制 / s3 env /
  oss env。

`tests/unit/test_pitr_crypto_push.py::TestPITREnginePusher`（4）—

* archive 触发 push；
* push 失败不破坏 archive；
* 无 pusher 不报错；
* LocalPusher 实际 copy（Windows 跳过）。

合计 28 个 off-host 相关单元测试。

## 51.13 已知限制 / 后续扩展

* **同步 push 阻塞 archive**：archive_segment() 是同步调用 push。
  Round 51+ 计划加 `push_async=True` 选项，把 push 扔到独立线程池。
* **不记录推送历史**：成功的 push 不入 metrics 表（只返回 `PushResult`）。
  Round 51+ 计划加 `OffHostPushLedger`（SQLite），记录每次 push
  的 URI / 时间戳 / size，便于审计与差异 push。
* **未实现 multipart upload**：大文件（>5GB for S3）需要 multipart；
  当前 segment 通常远小于该阈值，暂未实现。
* **未实现 incremental sync**：每次 push 都是完整文件，没有
  rsync-like 增量；OSS / S3 端 put_object_from_file / upload_file
  内部走的是覆盖语义，符合"全量 segment 不可变"假设。