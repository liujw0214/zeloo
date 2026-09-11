"""External memory provider abstraction.

Zeloo supports pluggable memory backends. The default backend stores
MEMORY.md / USER.md as local files under ``~/.Zeloo/memories/``.
External providers (Honcho, Mem0) are supported via the optional SDKs.

To use an external provider, set ``memory.provider: honcho`` (or ``mem0``)
in config.yaml and provide the required credentials. The provider falls
back to local files if the SDK is not installed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent.zeloo_constants import get_memories_dir

logger = logging.getLogger(__name__)


class MemoryProvider:
    """Abstract base class for memory backends."""

    def read(self, kind: str) -> str:
        """Return the memory content for *kind* ('memory' or 'user')."""
        raise NotImplementedError

    def write(self, kind: str, content: str) -> None:
        """Overwrite the memory content for *kind*."""
        raise NotImplementedError

    def append(self, kind: str, content: str) -> None:
        """Append to the memory content for *kind*."""
        existing = self.read(kind)
        if existing:
            self.write(kind, existing.rstrip() + "\n\n" + content)
        else:
            self.write(kind, content)


class LocalFileProvider(MemoryProvider):
    """Default backend — stores memories as local Markdown files."""

    def __init__(self, memories_dir: Path | None = None, max_chars: int = 8000) -> None:
        self.memories_dir = memories_dir or get_memories_dir()
        self.memories_dir.mkdir(parents=True, exist_ok=True)
        self.max_chars = max_chars

    def _path(self, kind: str) -> Path:
        name = "MEMORY.md" if kind == "memory" else "USER.md"
        return self.memories_dir / name

    def read(self, kind: str) -> str:
        path = self._path(kind)
        if not path.is_file():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Failed to read %s", path)
            return ""

    def write(self, kind: str, content: str) -> None:
        if len(content) > self.max_chars:
            content = content[: self.max_chars]
        self._path(kind).write_text(content, encoding="utf-8")


class HonchoProvider(MemoryProvider):
    """[Honcho](https://github.com/astralal/honcho) memory backend.

    Requires the ``honcho`` package. Falls back to LocalFileProvider if
    the SDK is unavailable or misconfigured.
    """

    def __init__(self, app_name: str, user_id: str, max_chars: int = 8000) -> None:
        self.max_chars = max_chars
        self._client: Any = None
        self._session: Any = None
        try:
            from honcho import Honcho  # type: ignore[import-not-found]

            self._client = Honcho(app_name=app_name)
            self._session = self._client.get_or_create_session(user_id=user_id)
            logger.info("Honcho provider initialized for user %s", user_id)
        except Exception as exc:
            logger.warning("Honcho unavailable (%s), falling back to local files", exc)
            self._fallback = LocalFileProvider(max_chars=max_chars)
            self._client = None

    def read(self, kind: str) -> str:
        if self._client is None:
            return self._fallback.read(kind)
        # Honcho stores messages; map memory/user to session message types
        messages = self._session.get_messages()
        relevant = [m.content for m in messages if getattr(m, "message_type", None) == kind]
        return "\n".join(relevant)

    def write(self, kind: str, content: str) -> None:
        if self._client is None:
            self._fallback.write(kind, content)
            return
        if len(content) > self.max_chars:
            content = content[: self.max_chars]
        self._session.create_message(content=content, message_type=kind)


class Mem0Provider(MemoryProvider):
    """[Mem0](https://github.com/mem0ai/mem0) memory backend.

    Requires the ``mem0ai`` package. Falls back to LocalFileProvider if
    the SDK is unavailable or misconfigured.
    """

    def __init__(self, api_key: str, user_id: str, max_chars: int = 8000) -> None:
        self.max_chars = max_chars
        self.user_id = user_id
        self._client: Any = None
        try:
            from mem0 import Memory  # type: ignore[import-not-found]

            self._client = Memory.from_config({"vector_store": {"provider": "qdrant"}})
            logger.info("Mem0 provider initialized for user %s", user_id)
        except Exception as exc:
            logger.warning("Mem0 unavailable (%s), falling back to local files", exc)
            self._fallback = LocalFileProvider(max_chars=max_chars)
            self._client = None

    def read(self, kind: str) -> str:
        if self._client is None:
            return self._fallback.read(kind)
        memories = self._client.get_all(user_id=self.user_id)
        # Filter by memory type stored as metadata
        relevant = [
            m.get("memory", "")
            for m in memories
            if m.get("metadata", {}).get("kind") == kind
        ]
        return "\n".join(relevant)

    def write(self, kind: str, content: str) -> None:
        if self._client is None:
            self._fallback.write(kind, content)
            return
        if len(content) > self.max_chars:
            content = content[: self.max_chars]
        self._client.add(content, user_id=self.user_id, metadata={"kind": kind})


class SupermemoryProvider(MemoryProvider):
    """[Supermemory](https://supermemory.ai) memory backend.

    Uses the Supermemory REST API to store and retrieve memories.
    Falls back to LocalFileProvider if the API key is not configured.
    """

    def __init__(
        self, api_key: str, user_id: str, max_chars: int = 8000
    ) -> None:
        self.max_chars = max_chars
        self.user_id = user_id
        self._api_key = api_key
        self._base_url = "https://api.supermemory.ai/v3"
        self._fallback: LocalFileProvider | None = None
        if not api_key:
            logger.warning("Supermemory API key not set, falling back to local files")
            self._fallback = LocalFileProvider(max_chars=max_chars)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def read(self, kind: str) -> str:
        if self._fallback is not None:
            return self._fallback.read(kind)
        import urllib.parse
        import urllib.request

        params = urllib.parse.urlencode({"q": kind, "userId": self.user_id})
        url = f"{self._base_url}/memories?{params}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            import json as _json

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            items = data if isinstance(data, list) else data.get("data", [])
            return "\n".join(
                m.get("content", "") for m in items if isinstance(m, dict)
            )
        except Exception as exc:
            logger.warning("Supermemory read failed (%s), using empty", exc)
            return ""

    def write(self, kind: str, content: str) -> None:
        if self._fallback is not None:
            self._fallback.write(kind, content)
            return
        if len(content) > self.max_chars:
            content = content[: self.max_chars]
        import json as _json
        import urllib.request

        body = _json.dumps(
            {"content": content, "userId": self.user_id, "metadata": {"kind": kind}}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/memories",
            data=body,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception as exc:
            logger.warning("Supermemory write failed (%s)", exc)


class OpenVikingProvider(MemoryProvider):
    """[OpenViking](https://github.com/openviking) memory backend.

    Uses a simple HTTP API compatible with the OpenViking memory service.
    Falls back to LocalFileProvider if the base URL is not configured.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        user_id: str = "default",
        max_chars: int = 8000,
    ) -> None:
        self.max_chars = max_chars
        self.user_id = user_id
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._fallback: LocalFileProvider | None = None
        if not base_url:
            logger.warning("OpenViking base_url not set, falling back to local files")
            self._fallback = LocalFileProvider(max_chars=max_chars)

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    def read(self, kind: str) -> str:
        if self._fallback is not None:
            return self._fallback.read(kind)
        import json as _json
        import urllib.request

        url = f"{self._base_url}/memories/{self.user_id}/{kind}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            return data.get("content", "") if isinstance(data, dict) else str(data)
        except Exception as exc:
            logger.debug("OpenViking read empty (%s)", exc)
            return ""

    def write(self, kind: str, content: str) -> None:
        if self._fallback is not None:
            self._fallback.write(kind, content)
            return
        if len(content) > self.max_chars:
            content = content[: self.max_chars]
        import json as _json
        import urllib.request

        body = _json.dumps({"content": content}).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/memories/{self.user_id}/{kind}",
            data=body,
            headers=self._headers(),
            method="PUT",
        )
        try:
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception as exc:
            logger.warning("OpenViking write failed (%s)", exc)


class ByteroverProvider(MemoryProvider):
    """[Byterover](https://byterover.com) memory backend.

    Uses the Byterover REST API for persistent memory storage.
    Falls back to LocalFileProvider if the API key is not configured.
    """

    def __init__(
        self, api_key: str, user_id: str = "default", max_chars: int = 8000
    ) -> None:
        self.max_chars = max_chars
        self.user_id = user_id
        self._api_key = api_key
        self._base_url = "https://api.byterover.com/v1"
        self._fallback: LocalFileProvider | None = None
        if not api_key:
            logger.warning("Byterover API key not set, falling back to local files")
            self._fallback = LocalFileProvider(max_chars=max_chars)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def read(self, kind: str) -> str:
        if self._fallback is not None:
            return self._fallback.read(kind)
        import json as _json
        import urllib.request

        url = f"{self._base_url}/memory?user={self.user_id}&namespace={kind}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                return "\n".join(
                    m.get("content", "") for m in data if isinstance(m, dict)
                )
            return data.get("content", "") if isinstance(data, dict) else ""
        except Exception:
            return ""

    def write(self, kind: str, content: str) -> None:
        if self._fallback is not None:
            self._fallback.write(kind, content)
            return
        if len(content) > self.max_chars:
            content = content[: self.max_chars]
        import json as _json
        import urllib.request

        body = _json.dumps(
            {"user": self.user_id, "namespace": kind, "content": content}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/memory",
            data=body,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception as exc:
            logger.warning("Byterover write failed (%s)", exc)


class HindsightProvider(MemoryProvider):
    """[Hindsight](https://github.com/hindsight-ai) memory backend.

    Uses the Hindsight SDK for experience-based memory retrieval.
    Falls back to LocalFileProvider if the SDK is unavailable.
    """

    def __init__(
        self, api_key: str, user_id: str = "default", max_chars: int = 8000
    ) -> None:
        self.max_chars = max_chars
        self.user_id = user_id
        self._api_key = api_key
        self._client: Any = None
        self._fallback: LocalFileProvider | None = None
        try:
            from hindsight import HindsightClient  # type: ignore[import-not-found]

            self._client = HindsightClient(api_key=api_key)
            logger.info("Hindsight provider initialized for user %s", user_id)
        except Exception:
            self._fallback = LocalFileProvider(max_chars=max_chars)
            self._client = None

    def read(self, kind: str) -> str:
        if self._client is None:
            return self._fallback.read(kind)  # type: ignore[union-attr]
        try:
            results = self._client.search(
                query=kind, user_id=self.user_id, top_k=20
            )
            return "\n".join(r.get("content", "") for r in results)
        except Exception as exc:
            logger.warning("Hindsight read failed (%s)", exc)
            return ""

    def write(self, kind: str, content: str) -> None:
        if self._client is None:
            self._fallback.write(kind, content)  # type: ignore[union-attr]
            return
        if len(content) > self.max_chars:
            content = content[: self.max_chars]
        try:
            self._client.add(
                content=content, user_id=self.user_id, metadata={"kind": kind}
            )
        except Exception as exc:
            logger.warning("Hindsight write failed (%s)", exc)


class HolographicProvider(MemoryProvider):
    """[Holographic](https://github.com/holographic-ai) memory backend.

    Uses the Holographic SDK for holographic memory embeddings.
    Falls back to LocalFileProvider if the SDK is unavailable.
    """

    def __init__(
        self, api_key: str, user_id: str = "default", max_chars: int = 8000
    ) -> None:
        self.max_chars = max_chars
        self.user_id = user_id
        self._api_key = api_key
        self._client: Any = None
        self._fallback: LocalFileProvider | None = None
        try:
            from holographic import HolographicMemory  # type: ignore[import-not-found]

            self._client = HolographicMemory(api_key=api_key)
            logger.info("Holographic provider initialized for user %s", user_id)
        except Exception:
            self._fallback = LocalFileProvider(max_chars=max_chars)
            self._client = None

    def read(self, kind: str) -> str:
        if self._client is None:
            return self._fallback.read(kind)  # type: ignore[union-attr]
        try:
            results = self._client.retrieve(
                query=kind, user_id=self.user_id, limit=20
            )
            return "\n".join(r.get("text", "") for r in results)
        except Exception as exc:
            logger.warning("Holographic read failed (%s)", exc)
            return ""

    def write(self, kind: str, content: str) -> None:
        if self._client is None:
            self._fallback.write(kind, content)  # type: ignore[union-attr]
            return
        if len(content) > self.max_chars:
            content = content[: self.max_chars]
        try:
            self._client.store(
                text=content, user_id=self.user_id, tags=[kind]
            )
        except Exception as exc:
            logger.warning("Holographic write failed (%s)", exc)


class RetainDBProvider(MemoryProvider):
    """[RetainDB](https://github.com/retaindb) memory backend.

    Uses a SQLite-based persistent store for long-term memory retention.
    Falls back to LocalFileProvider if sqlite3 is unavailable (very
    unlikely on standard Python, but handled for safety).
    """

    def __init__(
        self,
        db_path: str = "",
        user_id: str = "default",
        max_chars: int = 8000,
    ) -> None:
        self.max_chars = max_chars
        self.user_id = user_id
        self._fallback: LocalFileProvider | None = None
        self._db_path = db_path

        if not db_path:
            # Default to a file under the memories directory
            self._db_path = str(get_memories_dir() / "retain.db")

        try:
            import sqlite3

            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS memories ("
                "  user_id TEXT NOT NULL,"
                "  kind TEXT NOT NULL,"
                "  content TEXT NOT NULL,"
                "  created_at TEXT DEFAULT (datetime('now')),"
                "  PRIMARY KEY (user_id, kind)"
                ")"
            )
            self._conn.commit()
            logger.info("RetainDB provider initialized at %s", self._db_path)
        except Exception as exc:
            logger.warning("RetainDB unavailable (%s), falling back to local files", exc)
            self._fallback = LocalFileProvider(max_chars=max_chars)
            self._conn = None  # type: ignore[assignment]

    def read(self, kind: str) -> str:
        """Read the latest memory for *kind* from the SQLite store."""
        if self._fallback is not None:
            return self._fallback.read(kind)
        try:
            cursor = self._conn.execute(  # type: ignore[union-attr]
                "SELECT content FROM memories WHERE user_id = ? AND kind = ?",
                (self.user_id, kind),
            )
            row = cursor.fetchone()
            return row[0] if row else ""
        except Exception as exc:
            logger.warning("RetainDB read failed (%s)", exc)
            return ""

    def write(self, kind: str, content: str) -> None:
        """Upsert (insert or replace) memory content for *kind*."""
        if self._fallback is not None:
            self._fallback.write(kind, content)
            return
        if len(content) > self.max_chars:
            content = content[: self.max_chars]
        try:
            self._conn.execute(  # type: ignore[union-attr]
                "INSERT OR REPLACE INTO memories (user_id, kind, content) "
                "VALUES (?, ?, ?)",
                (self.user_id, kind, content),
            )
            self._conn.commit()  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("RetainDB write failed (%s)", exc)


def get_memory_provider(config: dict[str, Any] | None = None) -> MemoryProvider:
    """Factory: return a memory provider based on config.

    Supported config (under ``memory`` key):
      * ``provider``: "local" (default), "honcho", "mem0",
        "supermemory", "openviking", "byterover", "hindsight",
        "holographic", "retaindb"
      * ``max_chars``: max characters per memory (default 8000)
      * ``honcho.app_name`` / ``honcho.user_id``
      * ``mem0.api_key`` / ``mem0.user_id``
      * ``supermemory.api_key`` / ``supermemory.user_id``
      * ``openviking.base_url`` / ``openviking.api_key`` / ``openviking.user_id``
      * ``byterover.api_key`` / ``byterover.user_id``
      * ``hindsight.api_key`` / ``hindsight.user_id``
      * ``holographic.api_key`` / ``holographic.user_id``
      * ``retaindb.db_path`` / ``retaindb.user_id``
    """
    memory_cfg = (config or {}).get("memory", {}) if isinstance(config, dict) else {}
    if not isinstance(memory_cfg, dict):
        memory_cfg = {}

    provider_name = (memory_cfg.get("provider") or "local").lower()
    max_chars = int(memory_cfg.get("max_chars", 8000))

    if provider_name == "honcho":
        honcho_cfg = memory_cfg.get("honcho", {}) or {}
        return HonchoProvider(
            app_name=honcho_cfg.get("app_name", "Zeloo"),
            user_id=honcho_cfg.get("user_id", "default"),
            max_chars=max_chars,
        )

    if provider_name == "mem0":
        mem0_cfg = memory_cfg.get("mem0", {}) or {}
        return Mem0Provider(
            api_key=mem0_cfg.get("api_key", ""),
            user_id=mem0_cfg.get("user_id", "default"),
            max_chars=max_chars,
        )

    if provider_name == "supermemory":
        cfg = memory_cfg.get("supermemory", {}) or {}
        return SupermemoryProvider(
            api_key=cfg.get("api_key", ""),
            user_id=cfg.get("user_id", "default"),
            max_chars=max_chars,
        )

    if provider_name == "openviking":
        cfg = memory_cfg.get("openviking", {}) or {}
        return OpenVikingProvider(
            base_url=cfg.get("base_url", ""),
            api_key=cfg.get("api_key", ""),
            user_id=cfg.get("user_id", "default"),
            max_chars=max_chars,
        )

    if provider_name == "byterover":
        cfg = memory_cfg.get("byterover", {}) or {}
        return ByteroverProvider(
            api_key=cfg.get("api_key", ""),
            user_id=cfg.get("user_id", "default"),
            max_chars=max_chars,
        )

    if provider_name == "hindsight":
        cfg = memory_cfg.get("hindsight", {}) or {}
        return HindsightProvider(
            api_key=cfg.get("api_key", ""),
            user_id=cfg.get("user_id", "default"),
            max_chars=max_chars,
        )

    if provider_name == "holographic":
        cfg = memory_cfg.get("holographic", {}) or {}
        return HolographicProvider(
            api_key=cfg.get("api_key", ""),
            user_id=cfg.get("user_id", "default"),
            max_chars=max_chars,
        )

    if provider_name == "retaindb":
        cfg = memory_cfg.get("retaindb", {}) or {}
        return RetainDBProvider(
            db_path=cfg.get("db_path", ""),
            user_id=cfg.get("user_id", "default"),
            max_chars=max_chars,
        )

    return LocalFileProvider(max_chars=max_chars)
