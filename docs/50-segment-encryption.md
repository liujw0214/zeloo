# 50. Segment Encryption — Fernet At-Rest Protection

## 50.1 概述

`zeloo_state/crypto.py` 提供 `SegmentCipher`，把 Round 49 的明文 WAL segment
升级为 **Fernet（AES-128-CBC + HMAC-SHA256）认证加密**。segment 落到磁盘
之前先经过 cipher 包封，磁盘 / 异地 push / 异地备份通道看到的都只是
密文 + flag 字节 + 长度前缀。

## 50.2 设计动机

| 风险 | 加密前的暴露面 | 加密后的暴露面 |
|------|---------------|---------------|
| 离线磁盘被克隆 / 备份带走 | 完整 WAL payload（含业务数据） | 密文 + flag + 长度 |
| OSS / S3 bucket 配置错误导致公开 | 完整 WAL payload | 密文（无 key 不可解） |
| 异地同步中间人攻击 | 完整 WAL payload | 密文 + HMAC 防篡改 |
| 内部人员 dump archive 目录 | 完整 WAL payload | 必须先取得 master key |

业务场景里的关键数据（用户名 / token / 工单内容）通常都会进
WAL，**不加密就等同于把这些数据明文 push 到异地**，这是一道绝不能
省的合规 / 安全底线。

## 50.3 关键复用：与 credential_crypto 共用 master key

`SegmentCipher` **不引入新的密钥体系**，而是直接复用
`agent.credential_crypto.SecureCredentialStore` 的 master key 解析链：

1. `zeloo_MASTER_KEY` 环境变量（base64url-encoded Fernet key）
2. OS keyring（可选 `keyring` 包）
3. `~/.Zeloo/.master_key`（mode 0600，启动时自动生成）

> 一个 master key 同时保护 credentials.enc 与 wal-archive。
> 运维只需备份 **一个** 文件。

## 50.4 Segment 落盘格式

Round 49 的 segment 文件 = `[24B outer header][raw WAL payload]`。
Round 50 在 outer header 与 payload 之间插入 envelope：

```
┌─────────────────────────────────────────────────────────┐
│  Outer header (24 bytes, 与 Round 49 完全兼容)             │
│  ├─ magic "ZWAL" (4B)                                   │
│  ├─ version uint32 LE (4B, 当前 = 1)                    │
│  ├─ start_ts int64 LE (8B)                              │
│  └─ end_ts int64 LE (8B)                                │
├─────────────────────────────────────────────────────────┤
│  Cipher envelope (新增)                                   │
│  ├─ flags uint8 (0x01 = encrypted, 0x00 = plaintext)     │
│  ├─ [length uint32 BE (4B, 仅 encrypted 时存在)]         │
│  └─ ciphertext bytes (Fernet token, URL-safe b64)        │
└─────────────────────────────────────────────────────────┘
```

要点：

* **flag 字节是 Round 50 的关键**：0x01 加密 / 0x00 明文。
* **长度前缀为大端 uint32**：避免扫描整段找 ciphertext 边界；
  network-byte-order 让 wire format 一目了然。
* **Round 49 的旧 segment 没有 flag 字节**：`_decode_segment_payload`
  检测到首字节非 0x00 / 0x01 时，**回退到 legacy 明文路径**，保证
  升级过程不破坏既有 archive。

## 50.5 `SegmentCipher` API

```python
class SegmentCipher:
    def __init__(self, *, home: Path | None = None, auto_generate: bool = False)

    @property
    def is_available(self) -> bool      # cryptography 是否安装
    @property
    def is_ready(self) -> bool          # master key 已解析

    def ensure_key(self) -> bytes       # 强制解析 key（按需生成）
    def encrypt(self, plaintext: bytes) -> bytes
    def decrypt(self, envelope: bytes) -> bytes

    # 便捷方法：把 envelope 嵌进 24B header
    def encrypt_payload(self, plaintext: bytes, header: bytes) -> bytes
    def decrypt_payload(self, raw: bytes, header_size: int) -> bytes
    def is_encrypted_segment(self, raw: bytes, header_size: int) -> bool
```

`encrypt()` 输出格式：`b"\x01" + struct(">I", len) + Fernet(plaintext)`
`decrypt()` 验证 flag → 读 length → Fernet 解密。任何一步失败抛
`ValueError`，HMAC 校验失败抛 `ValueError("ciphertext tampered or wrong master key")`。

## 50.6 `PITREngine` 集成

`PITREngine.__init__` 新增两个 kwarg：

```python
PITREngine(
    db_path,
    *,
    archive_dir=None,
    snapshot_dir=None,
    cipher: SegmentCipher | None = None,   # ← Round 50
    pusher: OffHostPusher | None = None,   # ← Round 50（详见 §51）
    push_prefix: str = "wal/",
)
```

向后兼容：**不传 cipher 就走明文路径**，行为与 Round 49 完全一致。
现有 Round 49 测试不需要修改。

`archive_segment()` 行为变化：

```
cipher is None  →  payload = b"\x00" + raw_wal_bytes        (FLAG_PLAINTEXT)
cipher given    →  payload = cipher.encrypt(raw_wal_bytes)  (FLAG_ENCRYPTED + Fernet)
```

`_decode_segment_payload()` 优先按 flag 字节分发；旧 segment 无 flag
字节时按"首字节非 0x00 / 0x01 即视为 legacy"分支处理。

## 50.7 安全边界

| 边界 | 保证 |
|------|------|
| 磁盘 at-rest | Fernet AES-128-CBC + HMAC-SHA256，篡改可检测 |
| 异地 push | 推送的是密文 + flag + 长度；OSS / S3 端无法看到 plaintext |
| 密钥保管 | 单一 master key，0600 文件 + 可选 keyring |
| 备份链路 | 备份 archive dir 时，密文安全；备份 master key 时必须**另外**加密（KMS / 离线保险柜） |
| 错误暴露 | 解密失败抛 `ValueError`，绝不泄露明文 |

**威胁模型外的场景**：

* 物理内存 dump（process memory forensics）— Fernet key 在
  `_fernet_instance` 里，dump 内存即可拿到。这是几乎所有在进程
  内运行的加密方案都面临的局限，唯一的硬对策是 HSM / KMS。
* 同一台 host 上的 root 用户读 `~/.Zeloo/.master_key` — 需要
  host 级别的安全隔离（mac / SELinux）。

## 50.8 失败模式矩阵

| 场景 | 行为 |
|------|------|
| `cryptography` 未安装 | `is_available = False`，`encrypt` 抛 `RuntimeError` |
| master key 不存在且 `auto_generate=False` | `ensure_key` 抛 `RuntimeError` |
| master key 损坏（base64 解码失败） | 文件读取抛 `OSError`；fallthrough 到下一个 key 源 |
| segment 文件 flag 字节 = 0x01 但无 cipher 配置 | `restore` 拒绝，抛 `RuntimeError`（"configure cipher"） |
| segment 密文被改动（HMAC 失败） | `decrypt` 抛 `ValueError("ciphertext tampered")` |
| legacy Round 49 segment（无 flag 字节） | `_decode_segment_payload` 直接当作明文处理 |
| 进程中途挂掉，`.partial` 未清理 | 与 Round 49 同样：`.partial` 在 `archive_segment` 的 `finally` 块中被 unlink |

## 50.9 测试覆盖

`tests/unit/test_segment_crypto.py`：17 个测试

* `TestKeyResolution`（4）— 自动生成、env、malformed env、no-autogen；
* `TestEnvelopeRoundTrip`（9）— 加解密 round-trip、不同运行产不同密文、
  篡改 / 截断 / 空 / 未知 flag 拒绝、payload helper、is_encrypted
  检测、legacy plaintext 解码；
* `TestAvailability`（2）— `is_available` 与 cryptography 导入一致；
  无 cryptography 时 `ensure_key` 抛错；
* `TestKeyPersistence`（2）— 0600 文件、atomic overwrite。

`tests/unit/test_pitr_crypto_push.py::TestPITREngineCipher`（5）—

* 加密写入 → flag 字节验证；
* 无 cipher → 明文 flag 验证；
* 加密段在无 cipher engine 上读取被拒；
* Round 49 legacy segment 仍可还原；
* 完整加密 round-trip。

合计 22 个 cipher 相关单元测试。

## 50.10 已知限制 / 后续扩展

* **未实现密文压缩**：Fernet 内部已含 base64，但不影响磁盘大小。
  真实体积膨胀约 33%。如果空间紧张，可在 encrypt 前 zlib。
* **未实现 segment 级密钥**：所有 segment 共用一个 master key，
  符合"一个 KDF key 加密所有"的简单模型。若要做到"per-segment
  key"，需要把 key 嵌入 envelope，但那就违背了 at-rest 保护目的。
* **未与 WAL frame 校验和联动**：Fernet 自带 HMAC 覆盖密文整体，
  涵盖 outer header（24B plaintext）+ envelope，所以对 header 篡改
  也会被检测到（因为 header 之后的所有字节都在 HMAC 校验范围内）。
* **未来 KMS 集成**：Round 51+ 计划加 `KeyProvider` 抽象，允许
  从 AWS KMS / Vault / Aliyun KMS 取 key（数据加密密钥仍由 KMS 提供）。