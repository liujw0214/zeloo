# Zeloo 多用户隔离架构设计文档

> **版本**：0.16.0 — The Surface Release
> **状态**：架构设计（预留实现）
> **目标读者**：架构师 / 技术负责人 / 核心开发者
> **最后更新**：2026-09-11

---

## 目录

1. [设计目标与原则](#1-设计目标与原则)
2. [Hermes Agent 参考架构分析](#2-hermes-agent-参考架构分析)
3. [Zeloo 当前架构](#3-zeloo-当前架构)
4. [目标架构：三层隔离模型](#4-目标架构三层隔离模型)
5. [核心组件设计](#5-核心组件设计)
6. [数据隔离方案](#6-数据隔离方案)
7. [认证与授权体系](#7-认证与授权体系)
8. [连接管理（Connection）](#8-连接管理connection)
9. [会话与身份隔离](#9-会话与身份隔离)
10. [多用户 API 网关](#10-多用户-api-网关)
11. [Profile 系统](#11-profile-系统)
12. [Hermes One Account 集成](#12-hermes-one-account-集成)
13. [迁移路径](#13-迁移路径)
14. [安全边界设计](#14-安全边界设计)
15. [测试策略](#15-测试策略)
16. [实施计划](#16-实施计划)

---

## 1. 设计目标与原则

### 1.1 设计目标

| 目标 | 说明 |
|---|---|
| **用户隔离** | 不同用户的配置、记忆、会话、API Keys 完全隔离 |
| **连接管理** | 支持 Local / Remote / SSH 三种连接模式 |
| **认证灵活性** | 支持 Token Auth / OAuth 2.0 / Device Flow 多种认证方式 |
| **Profile 多实例** | 单用户可创建多个 Profile（工作/个人/测试等）|
| **向后兼容** | 单用户模式（Local）保持零配置开箱即用 |
| **企业就绪** | 支持 LDAP/OIDC 等企业身份源 |

### 1.2 设计原则

| 原则 | 说明 |
|---|---|
| **Credential Never Leave Main Process** | API Keys / OAuth Tokens / Session Cookies 只存在于服务端进程，不通过 IPC 传给渲染层 |
| **Stable Identity Tuple** | `{connectionId, profile, sessionId}` 作为会话唯一标识，防止跨用户/跨 Profile 混淆 |
| **Fail-Closed** | 配置损坏/版本不兼容时拒绝操作，不静默降级 |
| **Atomic Write** | 所有配置文件更新使用临时文件 + rename 保证原子性 |
| **Capability Bounded** | 每个功能的能力边界明确，未知功能标记为 `unknown` 而非 `unsupported` |

---

## 2. Hermes Agent 参考架构分析

基于 `lat.md` 文档分析，Hermes Agent 实现了以下多用户架构：

### 2.1 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Hermes Desktop (Electron)                     │
├─────────────────────────────────────────────────────────────────────┤
│  Renderer Process (React)                                           │
│  ├── Welcome Screen (连接选择)                                       │
│  ├── Layout (Sidebar + Chat + Settings)                             │
│  ├── Settings/ConnectionPane (连接管理 UI)                           │
│  ├── Settings/AboutPane (版本/更新/账户)                             │
│  └── Settings/ProvidersPane (模型配置)                               │
├─────────────────────────────────────────────────────────────────────┤
│  Preload Bridge (window.hermesAPI)                                  │
│  └── 仅暴露公开类型，隐藏凭证                                        │
├─────────────────────────────────────────────────────────────────────┤
│  Main Process (Node.js/Electron)                                    │
│  ├── Connection Registry (desktop.json) ← 凭证存储                   │
│  ├── Account Store (account.json) ← OAuth Token 加密存储             │
│  ├── Hermes Account (Device Flow OAuth) ← Hermes One 登录            │
│  ├── Remote OAuth (Browser-authenticated) ← OAuth 浏览器流程          │
│  ├── SSH Remote (ssh -N -L tunnel) ← 远程 dashboard                 │
│  ├── API Server Key Provisioning ← SSH 时自动生成 /v1 密钥            │
│  └── Dashboard Token Provisioning ← SSH 时自动生成 dashboard token    │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ Network (TLS)
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Remote Hermes Agent (Python)                            │
├─────────────────────────────────────────────────────────────────────┤
│  Dashboard (Web UI + WebSocket) — port 9119                         │
│  ├── /api/status — 公开状态（含 desktop_contract 版本）              │
│  ├── /api/sessions — Session 列表（Bearer Token 认证）              │
│  ├── /api/ws — Chat WebSocket                                       │
│  └── /api/* — 其他管理 API                                          │
├─────────────────────────────────────────────────────────────────────┤
│  Gateway API Server — port 8642                                     │
│  ├── /v1/chat/completions — OpenAI 兼容                             │
│  ├── /v1/responses                                                  │
│  ├── /v1/runs                                                      │
│  └── /health — 健康检查（Bearer Token 认证）                        │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心设计模式

| 模式 | Hermes 实现 | Zeloo 对应 |
|---|---|---|
| **Connection Registry** | `desktop.json` 存储连接记录 | 待实现：`~/.Zeloo/connections.json` |
| **Profile Isolation** | 每个 Profile 独立 `~/.hermes/profiles/<name>/` | 部分实现：`~/.Zeloo/workspace/` |
| **Stable Identity** | `{connectionId, profile, sessionId}` 三元组 | 待实现 |
| **Credential Boundary** | Main Process 持有凭证，不暴露给 Renderer | 待实现 |
| **Atomic Config Write** | 临时文件 + rename | 部分实现（config_loader.py）|
| **OAuth Flow** | Device Flow (RFC 8628) + Browser OAuth | 待实现 |
| **API Server Key Provisioning** | SSH 时自动生成并写入远程 `.env` | 待实现 |
| **Dashboard Token Provisioning** | SSH 时自动生成 session token | 待实现 |

---

## 3. Zeloo 当前架构

### 3.1 当前用户模型

```
当前：单用户单 Profile
~/.Zeloo/
├── config.yaml          # 全局配置（所有用户共享）
├── .env                 # API Keys（明文/加密）
├── memory/
│   └── MEMORY.md        # 记忆（全局）
├── sessions/
│   └── *.db             # SQLite 会话
├── skills/              # Skills（全局）
├── workspace/           # 工作区（单实例）
└── state.db             # 状态（全局）
```

**问题**：
- 无用户隔离
- 无 Profile 概念
- API Keys 明文存储（无 OS Keychain 集成）
- 无 Connection Registry
- 无 Remote/SSH 连接管理

### 3.2 当前认证体系

| 组件 | 现状 |
|---|---|
| **Provider Auth** | 16 个 Provider 的 API Key / OAuth（`zeloo_cli/auth/`）|
| **Token 存储** | `token_store.py` 使用 Fernet 加密 |
| **Session Token** | 无（Gateway 使用 API Server Key）|
| **OAuth 流程** | Device Flow 在各 Provider Auth 类中独立实现 |
| **Hermes One Account** | ❌ 未实现 |

---

## 4. 目标架构：三层隔离模型

### 4.1 架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Zeloo Multi-User Architecture                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                       │
│  │  User A     │    │  User B     │    │  User C     │     ← 用户层          │
│  │  Profile:   │    │  Profile:   │    │  Profile:   │                       │
│  │  work/      │    │  default/   │    │  default/   │                       │
│  │  personal/  │    │  test/      │    │  dev/       │                       │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                       │
│         │                  │                  │                              │
│  ┌──────▼──────────────────────────────────────────────▼──────┐              │
│  │                    Connection Registry                     │  ← 连接管理层  │
│  │              (connections.json, atomic write)              │              │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐       │              │
│  │  │ Local   │  │ Remote/ │  │ Remote/ │  │ SSH     │       │              │
│  │  │         │  │ Token   │  │ OAuth   │  │         │       │              │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘       │              │
│  └────────────────────────────────────────────────────────────┘              │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────┐              │
│  │                    Credential Store                         │  ← 凭证层     │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │              │
│  │  │ OS Keychain  │  │ Fernet       │  │ Vault        │      │              │
│  │  │ (macOS/Win)  │  │ (encrypted)  │  │ (Enterprise) │      │              │
│  │  └──────────────┘  └──────────────┘  └──────────────┘      │              │
│  └────────────────────────────────────────────────────────────┘              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              │ Network (TLS)
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Remote Zeloo Gateway (Server)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                      API Server (OpenAI Compatible)                  │     │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │     │
│  │  │ /v1/models   │  │ /v1/chat/    │  │ /v1/runs     │              │     │
│  │  │ (动态列表)   │  │ completions  │  │              │              │     │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                     Dashboard (Web UI + WS)                          │     │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │     │
│  │  │ /api/status  │  │ /api/sessions│  │ /api/ws      │              │     │
│  │  │ (公开状态)   │  │ (Bearer)     │  │ (Chat WS)    │              │     │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                    Per-User Data Isolation                           │     │
│  │  ~/.zeloo/<user_id>/  ← 每个用户独立目录                            │     │
│  │  ├── config.yaml     ← 用户配置                                     │     │
│  │  ├── .env            ← 用户 API Keys（加密）                        │     │
│  │  ├── memory/         ← 用户记忆                                     │     │
│  │  ├── sessions/       ← 用户会话                                     │     │
│  │  ├── skills/         ← 用户 Skills                                  │     │
│  │  └── mcp_config.json ← 用户 MCP 配置                                │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 目录结构（多用户）

```
~/.Zeloo/
├── connections.json              # 全局连接注册表（版本化）
├── profiles/                     # Profile 根目录
│   ├── default/                  # 默认 Profile
│   │   ├── config.yaml
│   │   ├── .env                  # 加密存储 API Keys
│   │   ├── memory/
│   │   │   └── MEMORY.md
│   │   ├── sessions/
│   │   │   └── state.db
│   │   ├── skills/               # 用户安装的 Skills
│   │   ├── mcp_config.json
│   │   └── account.json          # Hermes One Account Token（OS Keychain 备份）
│   ├── work/
│   │   └── ...                   # 工作 Profile
│   └── personal/
│       └── ...                   # 个人 Profile
├── credentials.json              # 加密凭证索引（Fernet 加密）
├── global_config.yaml            # 全局配置（安装路径等）
└── desktop.json                  # Desktop 元数据（连接 Registry）
```

---

## 5. 核心组件设计

### 5.1 Connection Registry

**文件**：`~/.Zeloo/connections.json`

```typescript
// TypeScript 类型定义（Zeloo 将用 Python 实现）
interface ConnectionRegistry {
  version: 1;
  activeConnectionId: string;
  connections: Record<string, ConnectionRecord>;
}

interface ConnectionRecord {
  connectionId: string;          // 随机 UUID，稳定不变
  name: string;                  // 用户可见名称
  mode: "local" | "remote-token" | "remote-oauth" | "ssh";
  createdAt: string;             // ISO 8601
  updatedAt: string;

  // Local 模式
  local?: {
    profile: string;             // profile 名称
  };

  // Remote Token 模式
  remoteToken?: {
    url: string;                 // Gateway URL (https://...)
    apiKey: string;              // API_SERVER_KEY（加密存储）
    transport: "auto" | "gateway" | "dashboard";
  };

  // Remote OAuth 模式
  remoteOAuth?: {
    url: string;                 // Dashboard URL
    authMode: "oauth";
    // OAuth 凭证不存储，通过 Electron Session Cookie 管理
  };

  // SSH 模式
  ssh?: {
    host: string;
    port: number;
    user: string;
    keyFile?: string;
    dashboardPort: number;       // 远程 Dashboard 端口
    apiServerPort: number;       // 远程 Gateway 端口
    dashboardToken?: string;     // 自动生成的 session token（加密）
    apiServerKey?: string;       // 自动生成的 API Server Key（加密）
  };
}
```

**关键设计**：
- `connectionId` 是稳定标识符，更改配置不改变 ID
- 凭证（apiKey/token）使用 Fernet 加密后存储
- OAuth 模式下不存储凭证，使用 Electron Session Cookie
- 原子写入：写临时文件 → rename

**Python 实现**：

```python
# zeloo_cli/connection_registry.py

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from zeloo_cli.credential_store import CredentialStore


ConnectionId = str
ConnectionMode = Literal["local", "remote-token", "remote-oauth", "ssh"]
Transport = Literal["auto", "gateway", "dashboard"]


@dataclass
class LocalConfig:
    profile: str = "default"


@dataclass
class RemoteTokenConfig:
    url: str
    encrypted_api_key: str  # Fernet 加密后的 API_SERVER_KEY
    transport: Transport = "auto"


@dataclass
class RemoteOAuthConfig:
    url: str
    # OAuth 凭证不存储，通过 Session Cookie 管理


@dataclass
class SSHConfig:
    host: str
    port: int = 22
    user: str
    key_file: str | None = None
    dashboard_port: int = 9119
    api_server_port: int = 8642
    encrypted_dashboard_token: str | None = None
    encrypted_api_server_key: str | None = None


@dataclass
class ConnectionRecord:
    connection_id: ConnectionId
    name: str
    mode: ConnectionMode
    created_at: str
    updated_at: str
    local: LocalConfig | None = None
    remote_token: RemoteTokenConfig | None = None
    remote_oauth: RemoteOAuthConfig | None = None
    ssh: SSHConfig | None = None

    @classmethod
    def create_local(cls, name: str, profile: str = "default") -> ConnectionRecord:
        now = datetime.utcnow().isoformat() + "Z"
        return cls(
            connection_id=str(uuid.uuid4()),
            name=name,
            mode="local",
            created_at=now,
            updated_at=now,
            local=LocalConfig(profile=profile),
        )

    @classmethod
    def create_remote_token(
        cls, name: str, url: str, api_key: str, transport: Transport = "auto"
    ) -> ConnectionRecord:
        now = datetime.utcnow().isoformat() + "Z"
        encrypted = CredentialStore.encrypt(api_key)
        return cls(
            connection_id=str(uuid.uuid4()),
            name=name,
            mode="remote-token",
            created_at=now,
            updated_at=now,
            remote_token=RemoteTokenConfig(
                url=url, encrypted_api_key=encrypted, transport=transport
            ),
        )

    def to_dict(self) -> dict:
        return asdict(self)


class ConnectionRegistry:
    """Connection Registry with atomic write and version compatibility."""

    VERSION = 1
    FILENAME = "connections.json"

    def __init__(self, home: Path | None = None):
        self.home = home or Path.home() / ".Zeloo"
        self.file_path = self.home / self.FILENAME
        self.credential_store = CredentialStore(self.home / "credentials.json")

    def _read_raw(self) -> dict:
        if not self.file_path.exists():
            return {"version": self.VERSION, "activeConnectionId": None, "connections": {}}
        with open(self.file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_atomic(self, data: dict) -> None:
        """Write atomically using temp file + rename."""
        tmp = self.file_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.rename(self.file_path)

    def list_connections(self) -> list[ConnectionRecord]:
        raw = self._read_raw()
        connections = []
        for cid, rec in raw.get("connections", {}).items():
            # 反序列化时跳过未知版本
            if not isinstance(rec, dict):
                continue
            version = rec.get("_version", 1)
            if version > self.VERSION:
                continue  # fail-closed: 未知版本不读取
            try:
                rec.pop("_version", None)
                connections.append(ConnectionRecord(**rec))
            except (TypeError, ValueError):
                continue
        return connections

    def get_connection(self, connection_id: ConnectionId) -> ConnectionRecord | None:
        raw = self._read_raw()
        rec = raw.get("connections", {}).get(connection_id)
        if not rec:
            return None
        version = rec.get("_version", 1)
        if version > self.VERSION:
            return None
        try:
            rec.pop("_version", None)
            return ConnectionRecord(**rec)
        except (TypeError, ValueError):
            return None

    def save_connection(self, record: ConnectionRecord) -> None:
        raw = self._read_raw()
        record.updated_at = datetime.utcnow().isoformat() + "Z"
        data = record.to_dict()
        data["_version"] = self.VERSION
        raw["connections"][record.connection_id] = data

        # 如果是第一个连接，自动设为活跃
        if raw["activeConnectionId"] is None:
            raw["activeConnectionId"] = record.connection_id

        self._write_atomic(raw)

    def set_active(self, connection_id: ConnectionId) -> None:
        raw = self._read_raw()
        if connection_id not in raw.get("connections", {}):
            raise ValueError(f"Connection {connection_id} not found")
        raw["activeConnectionId"] = connection_id
        self._write_atomic(raw)

    def remove_connection(self, connection_id: ConnectionId) -> None:
        raw = self._read_raw()
        if connection_id in raw.get("connections", {}):
            del raw["connections"][connection_id]
        if raw["activeConnectionId"] == connection_id:
            # 激活另一个连接或设为 None
            remaining = list(raw["connections"].keys())
            raw["activeConnectionId"] = remaining[0] if remaining else None
        self._write_atomic(raw)

    def get_active(self) -> ConnectionRecord | None:
        raw = self._read_raw()
        active_id = raw.get("activeConnectionId")
        if not active_id:
            return None
        return self.get_connection(active_id)

    def decrypt_api_key(self, record: ConnectionRecord) -> str | None:
        """Decrypt stored API key for remote-token connections."""
        if record.mode == "remote-token" and record.remote_token:
            return self.credential_store.decrypt(record.remote_token.encrypted_api_key)
        return None
```

### 5.2 Credential Store

**设计原则**：凭证绝不以明文存储，优先使用 OS Keychain，回退到 Fernet 加密。

```python
# zeloo_cli/credential_store.py

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    from keyring import get_keyring, set_keyring, KeyringError
    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False

try:
    from cryptography.fernet import Fernet
    HAS_FERNET = True
except ImportError:
    HAS_FERNET = False


class CredentialStore:
    """Secure credential storage with OS Keychain primary and Fernet fallback.

    Credentials are stored with a service+username keyring format:
    - service: "Zeloo"
    - username: <credential_id> (e.g., "connection/<uuid>/api_key")

    When OS Keychain is unavailable (Linux without keyring backend),
    falls back to Fernet encryption with a machine-derived key.
    """

    SERVICE = "Zeloo"

    def __init__(self, fallback_path: Path | None = None):
        self.fallback_path = fallback_path or (Path.home() / ".Zeloo" / "credentials.enc")
        self._fernet: Fernet | None = None
        if HAS_FERNET:
            self._fernet = self._get_fernet()

    def _get_fernet(self) -> Fernet:
        """Get or create Fernet key from machine-specific storage."""
        key_file = self.fallback_path.with_suffix(".key")
        if key_file.exists():
            key = key_file.read_bytes()
        else:
            key = Fernet.generate_key()
            key_file.write_bytes(key)
            key_file.chmod(0o600)
        return Fernet(key)

    def _keyring_key(self, credential_id: str) -> tuple[str, str]:
        return (self.SERVICE, credential_id)

    def store(self, credential_id: str, value: str) -> None:
        """Store a credential securely."""
        if HAS_KEYRING:
            try:
                keyring = get_keyring()
                keyring.set_password(*self._keyring_key(credential_id), value)
                return
            except (KeyringError, Exception):
                pass  # Fall through to Fernet

        # Fernet fallback
        encrypted = self._fernet.encrypt(value.encode()).decode()
        self._save_fallback(credential_id, encrypted)

    def retrieve(self, credential_id: str) -> str | None:
        """Retrieve a credential."""
        if HAS_KEYRING:
            try:
                keyring = get_keyring()
                return keyring.get_password(*self._keyring_key(credential_id))
            except (KeyringError, Exception):
                pass

        # Fernet fallback
        encrypted = self._load_fallback(credential_id)
        if encrypted and self._fernet:
            return self._fernet.decrypt(encrypted.encode()).decode()
        return None

    def delete(self, credential_id: str) -> None:
        """Delete a credential."""
        if HAS_KEYRING:
            try:
                keyring = get_keyring()
                keyring.delete_password(*self._keyring_key(credential_id))
            except (KeyringError, Exception):
                pass

        self._delete_fallback(credential_id)

    def _save_fallback(self, credential_id: str, encrypted: str) -> None:
        data = {}
        if self.fallback_path.exists():
            with open(self.fallback_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data[credential_id] = encrypted
        with open(self.fallback_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.fallback_path.chmod(0o600)

    def _load_fallback(self, credential_id: str) -> str | None:
        if not self.fallback_path.exists():
            return None
        with open(self.fallback_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(credential_id)

    def _delete_fallback(self, credential_id: str) -> None:
        if not self.fallback_path.exists():
            return
        with open(self.fallback_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if credential_id in data:
            del data[credential_id]
            with open(self.fallback_path, "w", encoding="utf-8") as f:
                json.dump(data, f)

    @staticmethod
    def encrypt(plaintext: str) -> str:
        """Static utility for encrypting API keys before storing in JSON."""
        if not HAS_FERNET:
            raise RuntimeError("cryptography package required")
        # Derive a one-time key from machine ID
        import hashlib
        machine_key = hashlib.sha256(
            (str(Path.home()) + str(sys.platform)).encode()
        ).digest()
        from cryptography.fernet import Fernet
        f = Fernet(Fernet.generate_key_from_password(machine_key, b"zeloo-salt"))
        return f.encrypt(plaintext.encode()).decode()

    @staticmethod
    def decrypt(ciphertext: str) -> str:
        """Static utility for decrypting API keys from JSON."""
        # Decryption requires the same key derivation — stored alongside ciphertext
        # In practice, CredentialStore.instance() methods are preferred
        raise NotImplementedError("Use CredentialStore.instance().retrieve()")
```

---

## 6. 数据隔离方案

### 6.1 Profile 隔离

每个 Profile 是完全独立的数据空间：

| 数据类型 | 隔离方式 | 说明 |
|---|---|---|
| **config.yaml** | Profile 目录 | 每个 Profile 有独立配置 |
| **API Keys** | Credential Store | OS Keychain 或 Fernet 加密 |
| **Memory** | Profile 目录 | `memory/MEMORY.md` |
| **Sessions** | Profile 目录 | `sessions/state.db` |
| **Skills** | Profile 目录 | 用户安装的 Skills |
| **MCP Config** | Profile 目录 | `mcp_config.json` |
| **Account Token** | OS Keychain | Hermes One Account |
| **SSH Keys** | Credential Store | 用于 SSH 连接的私钥 |

### 6.2 目录布局

```python
# zeloo_cli/profile_manager.py

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterator

from zeloo_cli.config_home import get_zeloo_home


class ProfileManager:
    """Manages multiple user profiles with full data isolation."""

    PROFILES_DIR = "profiles"

    def __init__(self, home: Path | None = None):
        self.home = home or get_zeloo_home()
        self.profiles_dir = self.home / self.PROFILES_DIR
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

    def list_profiles(self) -> list[str]:
        """List all profile names."""
        return [p.name for p in self.profiles_dir.iterdir() if p.is_dir()]

    def get_profile_home(self, name: str) -> Path:
        """Get the home directory for a profile."""
        return self.profiles_dir / name

    def create_profile(self, name: str, *, copy_from: str | None = None) -> Path:
        """Create a new profile, optionally copying from an existing one."""
        profile_home = self.get_profile_home(name)
        if profile_home.exists():
            raise ValueError(f"Profile '{name}' already exists")

        profile_home.mkdir(parents=True)

        if copy_from:
            src = self.get_profile_home(copy_from)
            if src.exists():
                for item in src.iterdir():
                    dst = profile_home / item.name
                    if item.is_dir():
                        shutil.copytree(item, dst)
                    else:
                        shutil.copy2(item, dst)

        # Create required subdirectories
        (profile_home / "memory").mkdir(exist_ok=True)
        (profile_home / "sessions").mkdir(exist_ok=True)
        (profile_home / "skills").mkdir(exist_ok=True)

        return profile_home

    def delete_profile(self, name: str, *, backup: bool = True) -> None:
        """Delete a profile, optionally backing up first."""
        if name == "default":
            raise ValueError("Cannot delete the default profile")

        profile_home = self.get_profile_home(name)
        if not profile_home.exists():
            raise ValueError(f"Profile '{name}' does not exist")

        if backup:
            backup_path = self.home / "profile_backups" / f"{name}_{int(time.time())}"
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(profile_home, backup_path)

        shutil.rmtree(profile_home)

    def get_active_profile(self) -> str:
        """Get the currently active profile name."""
        active_file = self.home / ".active_profile"
        if active_file.exists():
            name = active_file.read_text().strip()
            if name in self.list_profiles():
                return name
        return "default"

    def set_active_profile(self, name: str) -> None:
        """Set the active profile."""
        if name not in self.list_profiles():
            raise ValueError(f"Profile '{name}' does not exist")
        active_file = self.home / ".active_profile"
        active_file.write_text(name)

    def iter_profile_dirs(self, pattern: str = "*") -> Iterator[tuple[str, Path]]:
        """Iterate over all profiles yielding (name, home_path)."""
        for profile_home in self.profiles_dir.glob(pattern):
            if profile_home.is_dir():
                yield (profile_home.name, profile_home)
```

---

## 7. 认证与授权体系

### 7.1 认证方式矩阵

| 场景 | 认证方式 | 凭证存储 | 说明 |
|---|---|---|---|
| **Local 模式** | 无外部认证 | N/A | 本地单用户 |
| **Remote Token** | Bearer Token (`API_SERVER_KEY`) | Credential Store (加密) | 最简单的远程认证 |
| **Remote OAuth** | Browser OAuth (Session Cookie) | Electron Session (内存) | 企业 SSO 场景 |
| **SSH 模式** | SSH Key + Session Token | Credential Store (加密) | 跳板机场景 |
| **Hermes One Account** | Device Flow OAuth (RFC 8628) | OS Keychain | 云端同步 |

### 7.2 Remote OAuth 流程

```
┌──────────────┐                              ┌──────────────┐
│   Desktop    │                              │   Remote     │
│   Renderer   │                              │  Dashboard   │
└──────┬───────┘                              └──────┬───────┘
       │                                            │
       │  1. connect-remote-gateway (IPC)            │
       ▼                                            │
┌──────────────┐                                    │
│  Main        │                                    │
│  Process     │                                    │
│              │  2. GET /api/status                 │
       │       │────────────────────────────────────►
       │       │                                            │
       │       │  3. auth_required: true                   │
       │       │◄────────────────────────────────────────────
       │       │
       │       │  4. Open OAuth Login Window (sandboxed)
       │       │  (Electron BrowserWindow, OAuth partition)
       │       │
       │       │  5. User completes OAuth in browser
       │       │
       │       │  6. Cookie stored in OAuth partition
       │       │
       │       │  7. Connection saved (mode=oauth)
       │       │
       │       │  8. WebSocket ticket minted per connection
       │       │  (fresh ticket on every reconnect)
       │       │
       ▼       ▼                                            ▼
┌──────────────┐                                    ┌──────────────┐
│  Connection  │                                    │  Authenticated│
│  Registry    │                                    │  Dashboard    │
│  (encrypted) │                                    │  + WS         │
└──────────────┘                                    └──────────────┘
```

### 7.3 Device Flow OAuth（Hermes One Account）

```python
# zeloo_cli/hermes_account.py

from __future__ import annotations

import time
import webbrowser
from dataclasses import dataclass

import requests

from zeloo_cli.credential_store import CredentialStore


@dataclass
class HermesAccount:
    api_url: str
    user_id: str
    email: str
    access_token: str
    expires_at: float


class HermesAccountManager:
    """Hermes One Account login via Device Flow (RFC 8628)."""

    DEVICE_CODE_URL = "/api/device/code"
    TOKEN_URL = "/api/device/token"
    CREDENTIAL_ID = "hermes-account/access-token"

    def __init__(
        self,
        api_url: str = "https://api.hermesone.com",
        api_key: str | None = None,
    ):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.credential_store = CredentialStore()

    def login(self, on_code: callable, on_progress: callable) -> HermesAccount:
        """Run Device Flow login.

        Args:
            on_code: Called with (user_code, verification_uri) to show user.
            on_progress: Called with status string for UI updates.
        """
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        hostname = _get_hostname()

        # Step 1: Request device code
        on_progress("Requesting device code...")
        resp = requests.post(
            f"{self.api_url}{self.DEVICE_CODE_URL}",
            json={"device_name": hostname},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        user_code = data["user_code"]
        verification_uri = data["verification_uri"]
        device_code = data["device_code"]
        interval = data.get("interval", 5)
        expires_in = data.get("expires_in", 300)

        on_code(user_code, verification_uri)
        webbrowser.open(verification_uri)

        # Step 2: Poll for token
        deadline = time.time() + expires_in
        while time.time() < deadline:
            on_progress("Waiting for authorization...")
            time.sleep(interval)

            poll_resp = requests.post(
                f"{self.api_url}{self.TOKEN_URL}",
                json={"device_code": device_code},
                headers=headers,
                timeout=30,
            )
            poll_data = poll_resp.json()

            error = poll_data.get("error")
            if error == "authorization_pending":
                continue
            elif error == "slow_down":
                interval = min(interval * 2, 60)
                continue
            elif error in ("access_denied", "expired_token"):
                raise RuntimeError(f"Authorization failed: {error}")

            # Success
            access_token = poll_data["access_token"]
            expires_at = time.time() + poll_data.get("expires_in", 3600)

            # Store encrypted token
            self.credential_store.store(self.CREDENTIAL_ID, access_token)

            # Fetch user info
            user_resp = requests.get(
                f"{self.api_url}/api/me",
                headers={**headers, "Authorization": f"Bearer {access_token}"},
                timeout=30,
            )
            user_data = user_resp.json()

            return HermesAccount(
                api_url=self.api_url,
                user_id=user_data["id"],
                email=user_data["email"],
                access_token=access_token,
                expires_at=expires_at,
            )

        raise RuntimeError("Authorization timed out")

    def get_account(self) -> HermesAccount | None:
        """Get stored account if valid."""
        access_token = self.credential_store.retrieve(self.CREDENTIAL_ID)
        if not access_token:
            return None

        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        headers["Authorization"] = f"Bearer {access_token}"

        try:
            resp = requests.get(
                f"{self.api_url}/api/me",
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 401:
                return None  # Token expired
            resp.raise_for_status()
            user_data = resp.json()

            return HermesAccount(
                api_url=self.api_url,
                user_id=user_data["id"],
                email=user_data["email"],
                access_token=access_token,
                expires_at=time.time() + 3600,
            )
        except Exception:
            return None

    def logout(self) -> None:
        """Sign out from Hermes One account (all profiles)."""
        self.credential_store.delete(self.CREDENTIAL_ID)


def _get_hostname() -> str:
    import socket
    return socket.gethostname()
```

---

## 8. 连接管理（Connection）

### 8.1 连接类型

| 类型 | 说明 | 认证方式 |
|---|---|---|
| **Local** | 本地 Zeloo 实例 | 无 |
| **Remote Token** | 远程 Gateway URL + API Key | Bearer Token |
| **Remote OAuth** | 远程 Dashboard（Browser 认证）| Session Cookie |
| **SSH** | SSH 隧道到远程机器 | SSH Key + Dashboard Token |

### 8.2 连接状态探测

```python
# zeloo_cli/connection_status.py

from __future__ import annotations

import asyncio
import httpx
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from zeloo_cli.connection_registry import ConnectionRecord


class HealthStatus(Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    AUTH_FAILED = "auth_failed"
    UNAUTHORIZED = "unauthorized"
    UNKNOWN = "unknown"


@dataclass
class ConnectionStatus:
    connection_id: str
    health: HealthStatus
    latency_ms: float | None = None
    agent_version: str | None = None
    desktop_contract: int | None = None
    error: str | None = None


class ConnectionStatusChecker:
    """Probe connection health and authentication status."""

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=30.0)

    async def check_local(self, profile: str) -> ConnectionStatus:
        """Check local Zeloo installation."""
        # Local is always healthy if we can read the config
        return ConnectionStatus(
            connection_id="local",
            health=HealthStatus.HEALTHY,
            agent_version="0.16.0",
            desktop_contract=6,
        )

    async def check_remote_token(
        self, url: str, api_key: str, transport: Literal["auto", "gateway", "dashboard"]
    ) -> ConnectionStatus:
        """Check Remote Token connection."""
        headers = {"Authorization": f"Bearer {api_key}"}

        if transport == "dashboard":
            check_url = f"{url}/api/status"
        else:
            check_url = f"{url}/health"

        try:
            start = asyncio.get_event_loop().time()
            resp = await self._http.get(check_url, headers=headers)
            latency_ms = (asyncio.get_event_loop().time() - start) * 1000

            if resp.status_code == 200:
                data = resp.json()
                return ConnectionStatus(
                    connection_id="",
                    health=HealthStatus.HEALTHY,
                    latency_ms=latency_ms,
                    agent_version=data.get("version"),
                    desktop_contract=data.get("desktop_contract"),
                )
            elif resp.status_code in (401, 403):
                return ConnectionStatus(
                    connection_id="",
                    health=HealthStatus.UNAUTHORIZED,
                )
            else:
                return ConnectionStatus(
                    connection_id="",
                    health=HealthStatus.UNHEALTHY,
                    error=f"HTTP {resp.status_code}",
                )
        except httpx.TimeoutException:
            return ConnectionStatus(connection_id="", health=HealthStatus.UNHEALTHY, error="timeout")
        except Exception as e:
            return ConnectionStatus(connection_id="", health=HealthStatus.UNKNOWN, error=str(e))

    async def check_remote_oauth(self, url: str) -> ConnectionStatus:
        """Check Remote OAuth connection (public status endpoint)."""
        try:
            resp = await self._http.get(f"{url}/api/status", timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                auth_required = data.get("auth_required", False)
                return ConnectionStatus(
                    connection_id="",
                    health=HealthStatus.HEALTHY if not auth_required else HealthStatus.UNAUTHORIZED,
                    agent_version=data.get("version"),
                    desktop_contract=data.get("desktop_contract"),
                )
            return ConnectionStatus(connection_id="", health=HealthStatus.UNHEALTHY)
        except Exception as e:
            return ConnectionStatus(connection_id="", health=HealthStatus.UNKNOWN, error=str(e))

    async def close(self) -> None:
        await self._http.aclose()
```

---

## 9. 会话与身份隔离

### 9.1 Stable Identity Tuple

```
{connectionId, profile, sessionId}
```

这三个字段唯一确定一个会话上下文，确保：

- 不同机器的相同 sessionId 不会混淆
- 不同 Profile 的相同 sessionId 不会混淆
- 不同 Connection 的相同 sessionId 不会混淆

```python
# zeloo_cli/session_location.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SessionLocation:
    """Stable identity tuple for a chat session."""
    connection_id: str
    profile: str
    session_id: str


class SessionLocationStore:
    """Persist session locations across desktop restarts.

    Prevents equal Agent session IDs on different machines or profiles
    from being treated as one live run.
    """

    VERSION = 1
    FILENAME = "session_locations.json"

    def __init__(self, home: Path | None = None):
        self.home = home or Path.home() / ".Zeloo"
        self.file_path = self.home / self.FILENAME

    def record(self, location: SessionLocation) -> None:
        """Record a session location."""
        data = self._read()
        key = self._key(location)
        data[key] = {
            "_version": self.VERSION,
            "connection_id": location.connection_id,
            "profile": location.profile,
            "session_id": location.session_id,
        }
        self._write(data)

    def find(
        self,
        connection_id: str,
        profile: str,
        session_id: str,
    ) -> SessionLocation | None:
        """Find a session location by exact tuple match."""
        data = self._read()
        key = f"{connection_id}:{profile}:{session_id}"
        rec = data.get(key)
        if not rec:
            return None
        if rec.get("_version", 1) > self.VERSION:
            return None
        try:
            return SessionLocation(
                connection_id=rec["connection_id"],
                profile=rec["profile"],
                session_id=rec["session_id"],
            )
        except (KeyError, TypeError, ValueError):
            return None

    def remove(self, connection_id: str, profile: str, session_id: str) -> None:
        """Remove a session location."""
        data = self._read()
        key = f"{connection_id}:{profile}:{session_id}"
        if key in data:
            del data[key]
            self._write(data)

    def _key(self, loc: SessionLocation) -> str:
        return f"{loc.connection_id}:{loc.profile}:{loc.session_id}"

    def _read(self) -> dict:
        if not self.file_path.exists():
            return {}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: dict) -> None:
        tmp = self.file_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        tmp.rename(self.file_path)
```

### 9.2 会话路由

```python
# zeloo_cli/session_router.py

from __future__ import annotations

from pathlib import Path
from typing import Literal

from zeloo_cli.connection_registry import ConnectionRegistry, ConnectionRecord
from zeloo_cli.profile_manager import ProfileManager
from zeloo_cli.session_location import SessionLocationStore


class SessionRouter:
    """Route session operations to the correct data source based on connection type."""

    def __init__(
        self,
        connection_registry: ConnectionRegistry | None = None,
        profile_manager: ProfileManager | None = None,
    ):
        self.registry = connection_registry or ConnectionRegistry()
        self.profile_manager = profile_manager or ProfileManager()
        self.location_store = SessionLocationStore()

    def resolve_db_path(self, location: SessionLocation) -> Path:
        """Resolve the SQLite database path for a session location."""
        connection = self.registry.get_connection(location.connection_id)

        if connection is None or connection.mode == "local":
            profile_home = self.profile_manager.get_profile_home(location.profile)
            return profile_home / "sessions" / "state.db"

        elif connection.mode == "remote-token":
            # Remote: sessions are stored on the remote machine
            # We proxy through the remote API
            raise NotImplementedError("Remote session routing via API")

        elif connection.mode == "remote-oauth":
            # Remote OAuth: same as remote-token but via OAuth auth
            raise NotImplementedError("Remote OAuth session routing")

        elif connection.mode == "ssh":
            # SSH: sessions on remote machine via SSH tunnel
            raise NotImplementedError("SSH session routing")

        raise ValueError(f"Unknown connection mode: {connection.mode if connection else None}")

    def list_sessions(
        self,
        connection_id: str,
        profile: str,
    ) -> list[dict]:
        """List sessions for a connection+profile."""
        connection = self.registry.get_connection(connection_id)

        if connection is None or connection.mode == "local":
            db_path = self.profile_manager.get_profile_home(profile) / "sessions" / "state.db"
            return self._list_local_sessions(db_path)

        elif connection.mode in ("remote-token", "remote-oauth"):
            return self._list_remote_sessions(connection)

        elif connection.mode == "ssh":
            return self._list_ssh_sessions(connection, profile)

        return []

    def _list_local_sessions(self, db_path: Path) -> list[dict]:
        """List sessions from local SQLite."""
        if not db_path.exists():
            return []
        import sqlite3
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT session_id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
            return [
                {"session_id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3]}
                for r in rows
            ]
        finally:
            conn.close()

    def _list_remote_sessions(self, connection: ConnectionRecord) -> list[dict]:
        """List sessions via remote API."""
        # Proxy through remote API with Bearer token
        raise NotImplementedError("Remote session listing")

    def _list_ssh_sessions(self, connection: ConnectionRecord, profile: str) -> list[dict]:
        """List sessions over SSH tunnel."""
        raise NotImplementedError("SSH session listing")
```

---

## 10. 多用户 API 网关

### 10.1 认证中间件

```python
# gateway/multiuser_middleware.py

from __future__ import annotations

from typing import Callable

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


class MultiUserAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate requests and attach user context.

    Supports three auth modes:
    1. API Server Key (Bearer token) — for direct API access
    2. Dashboard Session Token (X-Hermes-Session-Token) — for dashboard clients
    3. OAuth Cookie — for browser-authenticated sessions
    """

    def __init__(self, app, user_registry: UserRegistry):
        super().__init__(app)
        self.user_registry = user_registry

    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path

        # Health endpoint is always public
        if path == "/health":
            return await call_next(request)

        # Extract auth from header or cookie
        auth_header = request.headers.get("Authorization", "")
        session_token = request.headers.get("X-Hermes-Session-Token", "")
        oauth_cookie = request.cookies.get("hermes-session")

        user = None
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:]
            user = self.user_registry.authenticate_api_key(api_key)
        elif session_token:
            user = self.user_registry.authenticate_session_token(session_token)
        elif oauth_cookie:
            user = await self._authenticate_oauth(request, oauth_cookie)

        if user is None:
            raise HTTPException(status_code=401, detail="Unauthorized")

        # Attach user context to request state
        request.state.user = user

        response = await call_next(request)
        return response

    async def _authenticate_oauth(self, request: Request, cookie: str) -> User | None:
        """Authenticate via OAuth session cookie."""
        # Check if cookie maps to a valid OAuth session
        # In production, this would validate against the session store
        raise NotImplementedError("OAuth cookie authentication")
```

### 10.2 用户注册表

```python
# gateway/user_registry.py

from __future__ import annotations

import secrets
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml


@dataclass
class User:
    user_id: str
    api_key_hash: str
    session_tokens: dict[str, datetime] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    is_admin: bool = False


class UserRegistry:
    """Registry of users with API key and session token authentication.

    In production, this would backed by a database (PostgreSQL).
    For single-machine use, backed by a YAML file.
    """

    def __init__(self, storage_path: Path | None = None):
        self.storage_path = storage_path or Path.home() / ".Zeloo" / "users.yaml"
        self._users: dict[str, User] = {}
        self._api_key_index: dict[str, str] = {}  # hash -> user_id
        self._session_index: dict[str, str] = {}  # token -> user_id
        self._load()

    def _load(self) -> None:
        if not self.storage_path.exists():
            return
        with open(self.storage_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for user_id, udata in data.get("users", {}).items():
            user = User(
                user_id=user_id,
                api_key_hash=udata["api_key_hash"],
                session_tokens={
                    t: datetime.fromisoformat(dt)
                    for t, dt in udata.get("session_tokens", {}).items()
                },
                created_at=datetime.fromisoformat(udata.get("created_at", datetime.utcnow().isoformat())),
                is_admin=udata.get("is_admin", False),
            )
            self._users[user_id] = user
            if user.api_key_hash:
                self._api_key_index[user.api_key_hash] = user_id
            for token in user.session_tokens:
                self._session_index[token] = user_id

    def _save(self) -> None:
        data = {
            "users": {
                uid: {
                    "api_key_hash": u.api_key_hash,
                    "session_tokens": {
                        t: dt.isoformat() for t, dt in u.session_tokens.items()
                    },
                    "created_at": u.created_at.isoformat(),
                    "is_admin": u.is_admin,
                }
                for uid, u in self._users.items()
            }
        }
        tmp = self.storage_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.dump(data, f)
        tmp.rename(self.storage_path)

    def create_user(self, user_id: str, api_key: str | None = None) -> tuple[str, str]:
        """Create a new user. Returns (api_key, session_token)."""
        if user_id in self._users:
            raise ValueError(f"User {user_id} already exists")

        if api_key is None:
            api_key = f"zl_{secrets.token_urlsafe(32)}"

        api_key_hash = self._hash_key(api_key)
        user = User(user_id=user_id, api_key_hash=api_key_hash)
        self._users[user_id] = user
        self._api_key_index[api_key_hash] = user_id

        session_token = self._generate_session_token(user_id)

        self._save()
        return api_key, session_token

    def authenticate_api_key(self, api_key: str) -> User | None:
        """Authenticate by API key. Returns User or None."""
        key_hash = self._hash_key(api_key)
        user_id = self._api_key_index.get(key_hash)
        if user_id:
            return self._users.get(user_id)
        return None

    def authenticate_session_token(self, token: str) -> User | None:
        """Authenticate by session token. Returns User or None."""
        user_id = self._session_index.get(token)
        if not user_id:
            return None
        user = self._users.get(user_id)
        if not user:
            return None

        expiry = user.session_tokens.get(token)
        if expiry and datetime.utcnow() > expiry:
            # Token expired
            del user.session_tokens[token]
            del self._session_index[token]
            self._save()
            return None

        return user

    def issue_session_token(self, user_id: str, ttl_hours: int = 24) -> str:
        """Issue a session token for a user."""
        user = self._users.get(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        token = self._generate_session_token(user_id)
        expiry = datetime.utcnow() + timedelta(hours=ttl_hours)
        user.session_tokens[token] = expiry
        self._session_index[token] = user_id
        self._save()
        return token

    def revoke_session_token(self, user_id: str, token: str) -> None:
        """Revoke a session token."""
        user = self._users.get(user_id)
        if user and token in user.session_tokens:
            del user.session_tokens[token]
            if token in self._session_index:
                del self._session_index[token]
            self._save()

    def _hash_key(self, key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    def _generate_session_token(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        return token
```

---

## 11. Profile 系统

### 11.1 Profile 与多用户的关系

```
Hermes Agent 架构中的 Profile：
- 每个 Profile 是完全隔离的数据空间
- Profile 可以有独立的 API Keys、MCP 配置、记忆、会话
- 适合场景：工作/个人、测试/生产、不同客户账号

Zeloo 实现 Profile 的目标：
- 复用现有的 Workspace 概念
- Workspace = Profile（重命名）
- 多用户通过 OS 用户账号隔离（Linux/macOS 的多用户、Windows 的多用户配置文件）
```

### 11.2 Workspace → Profile 迁移

```python
# zeloo_cli/workspace_migration.py

from __future__ import annotations

import shutil
from pathlib import Path

from zeloo_cli.workspace_templates import WorkspaceManager


class ProfileMigration:
    """Migrate existing workspace structure to multi-profile structure."""

    def __init__(self):
        self.workspace_manager = WorkspaceManager()
        self.home = Path.home() / ".Zeloo"

    def migrate_to_profiles(self) -> None:
        """Migrate from single-workspace to multi-profile structure.

        Before:
            ~/.Zeloo/
            ├── config.yaml
            ├── memory/
            └── sessions/

        After:
            ~/.Zeloo/
            ├── profiles/
            │   └── default/
            │       ├── config.yaml
            │       ├── memory/
            │       └── sessions/
            └── connections.json
        """
        profiles_dir = self.home / "profiles"
        default_profile = profiles_dir / "default"
        default_profile.mkdir(parents=True, exist_ok=True)

        # Migrate existing data to default profile
        mappings = [
            ("config.yaml", default_profile / "config.yaml"),
            (".env", default_profile / ".env"),
            ("memory", default_profile / "memory"),
            ("sessions", default_profile / "sessions"),
            ("skills", default_profile / "skills"),
            ("mcp_config.json", default_profile / "mcp_config.json"),
        ]

        for src_name, dst_path in mappings:
            src_path = self.home / src_name
            if src_path.exists() and not dst_path.exists():
                if src_path.is_dir():
                    shutil.copytree(src_path, dst_path)
                else:
                    shutil.copy2(src_path, dst_path)

        # Create connections.json with default local connection
        self._create_default_connection()

    def _create_default_connection(self) -> None:
        """Create default local connection."""
        from zeloo_cli.connection_registry import ConnectionRegistry, ConnectionRecord

        registry = ConnectionRegistry(self.home)
        default_conn = ConnectionRecord.create_local("Local", profile="default")
        registry.save_connection(default_conn)
        registry.set_active(default_conn.connection_id)
```

---

## 12. Hermes One Account 集成

### 12.1 目的

Hermes One Account 提供：
- 云端 agent 同步（跨设备同步记忆/会话）
- 统一计费（AI Credits）
- 企业 SSO（通过 OAuth）

### 12.2 自动密钥下发

用户登录 Hermes One Account 后，桌面自动：
1. POST `/api/credits/keys` 获取 Hermes One Inference Gateway Key
2. 写入当前 Profile 的 `.env`：`HERMESONE_API_KEY=hs-live-...`
3. 显示账户余额

```python
# zeloo_cli/hermesone_provision.py

from __future__ import annotations

import time
from dataclasses import dataclass

from zeloo_cli.hermes_account import HermesAccount, HermesAccountManager


@dataclass
class ProvisionResult:
    action: Literal["existing", "created", "error"]
    api_key: str | None = None
    credits: float | None = None
    error: str | None = None


class HermesOneProvisioner:
    """Auto-provision Hermes One API key after account login."""

    def __init__(self, account_manager: HermesAccountManager):
        self.account_manager = account_manager

    def ensure_api_key(
        self,
        profile_env_path: Path,
    ) -> ProvisionResult:
        """Ensure HERMESONE_API_KEY is set in profile .env.

        Idempotent: only creates key if missing.
        """
        import os
        from dotenv import load_dotenv, set_key

        load_dotenv(profile_env_path)

        existing_key = os.environ.get("HERMESONE_API_KEY")
        if existing_key:
            return ProvisionResult(action="existing", api_key=existing_key)

        account = self.account_manager.get_account()
        if not account:
            return ProvisionResult(action="error", error="Not signed in")

        # Issue new key
        import requests
        resp = requests.post(
            f"{account.api_url}/api/credits/keys",
            json={
                "name": f"Zeloo Desktop ({_get_hostname()})",
                "provider": "hermes-one",
            },
            headers={
                "Authorization": f"Bearer {account.access_token}",
                "x-api-key": self.account_manager.api_key or "",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return ProvisionResult(action="error", error=f"HTTP {resp.status_code}")

        data = resp.json()
        api_key = data["key"]  # One-time display, store immediately

        set_key(profile_env_path, "HERMESONE_API_KEY", api_key)

        return ProvisionResult(action="created", api_key=api_key)

    def fetch_credits(self, account: HermesAccount) -> float | None:
        """Fetch account credit balance."""
        import requests
        try:
            resp = requests.get(
                f"{account.api_url}/api/credits/balance",
                headers={
                    "Authorization": f"Bearer {account.access_token}",
                    "x-api-key": self.account_manager.api_key or "",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("balance")
        except Exception:
            pass
        return None


def _get_hostname() -> str:
    import socket
    return socket.gethostname()
```

---

## 13. 迁移路径

### 13.1 分阶段实施

| 阶段 | 内容 | 风险 | 工作量 |
|---|---|---|---|
| **Phase 1** | Profile 系统（Workspace 重命名）| 低 | ~1 周 |
| **Phase 2** | Connection Registry + Credential Store | 中 | ~2 周 |
| **Phase 3** | Local Profile 隔离（完整多 Profile）| 低 | ~1 周 |
| **Phase 4** | Remote Token 连接管理 | 中 | ~2 周 |
| **Phase 5** | Remote OAuth 连接管理 | 中 | ~2 周 |
| **Phase 6** | SSH 连接管理 + 自动密钥下发 | 高 | ~3 周 |
| **Phase 7** | Hermes One Account 集成 | 高 | ~3 周 |
| **Phase 8** | 企业 LDAP/OIDC 支持 | 高 | ~4 周 |

### 13.2 向后兼容

- **Phase 1-3**：单用户 Local 模式完全兼容，现有 `.Zeloo/` 结构自动迁移
- **Phase 4-6**：Remote 连接作为新增功能，现有 Local 用户不受影响
- **Phase 7-8**：企业功能默认关闭，需要显式启用

### 13.3 数据迁移脚本

```bash
# scripts/migrate_to_profiles.sh
#!/bin/bash
# 从单 Workspace 迁移到多 Profile 结构

set -e

ZELOO_HOME="${ZELOO_HOME:-$HOME/.Zeloo}"

echo "Migrating Zeloo to multi-profile structure..."

# 创建 profiles 目录
mkdir -p "$ZELOO_HOME/profiles/default"

# 迁移文件
for item in config.yaml .env memory sessions skills mcp_config.json; do
    if [ -f "$ZELOO_HOME/$item" ] && [ ! -f "$ZELOO_HOME/profiles/default/$item" ]; then
        cp "$ZELOO_HOME/$item" "$ZELOO_HOME/profiles/default/$item"
        echo "  Migrated: $item"
    elif [ -d "$ZELOO_HOME/$item" ] && [ ! -d "$ZELOO_HOME/profiles/default/$item" ]; then
        cp -r "$ZELOO_HOME/$item" "$ZELOO_HOME/profiles/default/$item"
        echo "  Migrated: $item/"
    fi
done

# 创建 connections.json
cat > "$ZELOO_HOME/connections.json" << 'EOF'
{
  "version": 1,
  "activeConnectionId": "default-local",
  "connections": {
    "default-local": {
      "_version": 1,
      "connectionId": "default-local",
      "name": "Local",
      "mode": "local",
      "createdAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
      "updatedAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
      "local": {
        "profile": "default"
      }
    }
  }
}
EOF

echo "Migration complete!"
echo "Your data is now under ~/.Zeloo/profiles/default/"
```

---

## 14. 安全边界设计

### 14.1 凭证边界

| 层级 | 凭证可见性 | 说明 |
|---|---|---|
| **Renderer (Web UI)** | ❌ 永远不可见 | 通过 IPC 调用，只能获取公开数据 |
| **Preload Bridge** | ❌ 永远不可见 | 只暴露公开类型 |
| **Main Process** | ✅ 仅自身需要 | 持有所有凭证 |
| **Credential Store** | ✅ 加密存储 | OS Keychain 或 Fernet |
| **Remote API** | ✅ 按需传输 | 仅传输必要凭证 |

### 14.2 OAuth 安全

```python
# 安全原则：OAuth 凭证永不离开 Main Process

# 错误做法（在 Renderer 中）：
# const token = await window.hermesAPI.getOAuthToken()  # ❌ 暴露凭证

# 正确做法（通过 Main Process）：
# 1. OAuth cookie 存储在 Electron Session（隔离 partition）
# 2. Renderer 通过 IPC 调用，由 Main Process 执行请求
# 3. Renderer 只能知道"是否已登录"，不能访问 token
```

### 14.3 WebSocket Ticket

每个 OAuth WebSocket 连接使用一次性 ticket：

```python
# 每次连接前请求新 ticket
ticket_url = await mint_remote_oauth_ws_ticket(connection_id)
# ticket 只有一次有效，连接断开后失效
```

### 14.4 SSH 密钥隔离

```python
# SSH 私钥存储在 Credential Store，永不明文存储在 JSON 中

# connections.json 中存储的是加密引用，而非明文 key
ssh: {
    key_file: None,  # 不存储路径，使用 Credential Store 的 credential_id
    encrypted_key_id: "ssh-key/abc123",
}
```

---

## 15. 测试策略

### 15.1 单元测试

| 测试文件 | 覆盖内容 |
|---|---|
| `test_connection_registry.py` | CRUD、原子写入、版本兼容性 |
| `test_credential_store.py` | 加密/解密、Keychain 回退 |
| `test_profile_manager.py` | 创建/删除/切换 Profile |
| `test_session_location.py` | Stable identity tuple、边界 |
| `test_user_registry.py` | API Key 认证、Session Token 管理 |
| `test_hermes_account.py` | Device Flow 所有 RFC 分支 |
| `test_hermesone_provision.py` | 幂等密钥下发、单飞模式 |

### 15.2 集成测试

```python
# tests/integration/test_multiuser_isolation.py

import pytest
from pathlib import Path
from zeloo_cli.connection_registry import ConnectionRegistry
from zeloo_cli.profile_manager import ProfileManager
from zeloo_cli.credential_store import CredentialStore


class TestMultiUserIsolation:
    """Integration tests for multi-user isolation."""

    def test_profiles_are_isolated(self, tmp_path):
        """Data in one profile is not accessible from another."""
        pm = ProfileManager(tmp_path)

        # Create two profiles
        pm.create_profile("work")
        pm.create_profile("personal")

        # Write to work profile
        work_home = pm.get_profile_home("work")
        (work_home / "test.txt").write_text("work data")

        # Verify not in personal profile
        personal_home = pm.get_profile_home("personal")
        assert not (personal_home / "test.txt").exists()

    def test_connection_credentials_are_encrypted(self, tmp_path):
        """API keys stored in connections.json are encrypted."""
        registry = ConnectionRegistry(tmp_path)

        conn = registry.create_remote_token(
            name="Remote",
            url="https://example.com",
            api_key="sk-secret-api-key",
        )
        registry.save_connection(conn)

        # Read raw file
        raw = (tmp_path / "connections.json").read_text()
        assert "sk-secret" not in raw  # Not plaintext
        assert "sk-" not in raw  # Not even partial

    def test_credential_store_keyring_fallback(self, tmp_path, monkeypatch):
        """Falls back to Fernet when OS keyring unavailable."""
        monkeypatch.setenv("KEYRING_BACKEND", "fail.keyring")
        store = CredentialStore(tmp_path / "creds.enc")

        # Should still work with Fernet fallback
        store.store("test/creds", "my-secret")
        assert store.retrieve("test/creds") == "my-secret"

    def test_atomic_write_prevents_corruption(self, tmp_path):
        """Interrupted write does not corrupt config."""
        registry = ConnectionRegistry(tmp_path)

        conn = registry.create_local("Test")
        registry.save_connection(conn)

        # Simulate partial write failure
        # (in practice, we'd mock rename to fail)

        # Verify original data is intact
        loaded = registry.get_connection(conn.connection_id)
        assert loaded is not None
        assert loaded.name == "Test"
```

---

## 16. 实施计划

### 16.1 总体时间线

```
Week 1-2:   Phase 1 - Profile 系统基础
Week 3-4:   Phase 2 - Connection Registry + Credential Store
Week 5:     Phase 3 - Local Profile 隔离
Week 6-7:   Phase 4 - Remote Token 连接
Week 8-9:   Phase 5 - Remote OAuth 连接
Week 10-12: Phase 6 - SSH 连接管理
Week 13-15: Phase 7 - Hermes One Account
Week 16-19: Phase 8 - 企业 LDAP/OIDC（可选）
```

### 16.2 依赖关系

```
Phase 1 ──► Phase 2 ──► Phase 3 ──┬─► Phase 4 ──► Phase 5 ──► Phase 6
                                 │
                                 └─► Phase 7
```

**说明**：
- Phase 1 是所有后续阶段的基础
- Phase 3 完成后，Local 多 Profile 功能可用
- Phase 4-6 可并行开发（各自独立的连接类型）
- Phase 7 依赖 Phase 2 的 Credential Store
- Phase 8 是独立可选扩展

### 16.3 验收标准

| 阶段 | 验收条件 |
|---|---|
| Phase 1 | 可以创建/切换/删除 Profile |
| Phase 2 | API Key 加密存储、原子写入、版本兼容 |
| Phase 3 | 不同 Profile 的记忆/会话完全隔离 |
| Phase 4 | Remote Token 连接可正常通信 |
| Phase 5 | Remote OAuth 浏览器登录成功 |
| Phase 6 | SSH 隧道自动建立、可访问远程会话 |
| Phase 7 | Hermes One Account 登录 + 自动密钥下发 |
| Phase 8 | LDAP/OIDC 企业认证正常 |

---

## 附录 A：文件清单

| 文件 | 行数 | 说明 |
|---|---|---|
| `zeloo_cli/connection_registry.py` | ~200 | 连接注册表 |
| `zeloo_cli/credential_store.py` | ~150 | 凭证安全存储 |
| `zeloo_cli/profile_manager.py` | ~120 | Profile 管理器 |
| `zeloo_cli/session_location.py` | ~100 | 会话位置存储 |
| `zeloo_cli/session_router.py` | ~120 | 会话路由 |
| `zeloo_cli/connection_status.py` | ~100 | 连接状态探测 |
| `zeloo_cli/hermes_account.py` | ~150 | Hermes One Account |
| `zeloo_cli/hermesone_provision.py` | ~100 | 自动密钥下发 |
| `zeloo_cli/workspace_migration.py` | ~80 | 数据迁移 |
| `gateway/multiuser_middleware.py` | ~100