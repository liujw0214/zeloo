"""Off-host pushers for snapshots and WAL segments.

The :class:`PITREngine` writes artifacts to a local directory first
(durable on the host's disk) and then *asynchronously* hands them off
to an :class:`OffHostPusher`. The off-host copy is a *secondary*
defense-in-depth: the local archive is still the source of truth for
restores within the retention window, but a separate host / bucket /
disk means we survive the worst single-point failures (whole-disk
loss, ransomware, datacenter fire).

Backends
========

* :class:`LocalPusher` — copies to a second directory. The two
  directories should live on different physical disks (or at
  minimum different mount points). Always available; no external
  dependency. This is the default and the only backend covered
  by the unit tests.

* :class:`S3Pusher` — uploads to AWS S3 (or any S3-compatible
  service: MinIO, R2, Backblaze B2). Optional ``boto3`` import;
  if missing, the pusher logs a warning and becomes a no-op
  rather than crashing the archive loop.

* :class:`OSSPusher` — uploads to Aliyun OSS. Optional ``oss2``
  import; same no-op fallback.

* :class:`NullPusher` — explicitly discards uploads. Useful in
  tests and when an operator wants to disable off-host while
  keeping the engine API surface unchanged.

Retry & failure
===============

Pushers raise :class:`OffHostPushError` on transient failures
(network timeout, 5xx, throttle). The engine catches and logs
the error; the local archive remains untouched, so a failed
push does *not* lose data. We expose :meth:`push_with_retry`
on the engine that wraps a single push with bounded retries
and exponential backoff.

Security
========

* All HTTP-based pushers should be configured with TLS-only
  endpoints (``https://`` or ``s3://`` with TLS).
* Credentials are read from environment variables:
  - S3: ``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``,
    optionally ``AWS_SESSION_TOKEN`` and ``AWS_ENDPOINT_URL``.
  - OSS: ``OSS_ACCESS_KEY_ID``, ``OSS_ACCESS_KEY_SECRET``,
    ``OSS_ENDPOINT``, ``OSS_BUCKET``.
* The pusher never embeds credentials in the URL or query string.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class OffHostPushError(RuntimeError):
    """Raised when a pusher fails to upload an artifact.

    The engine treats this as recoverable: the local archive is
    still authoritative. Operators can re-trigger a push later
    by calling :meth:`PITREngine.push_pending` (a future addition)
    or by manually re-uploading the files.
    """


@dataclass
class PushResult:
    """Result of a single push attempt."""

    source_path: Path
    remote_uri: str
    duration_seconds: float
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "remote_uri": self.remote_uri,
            "duration_seconds": self.duration_seconds,
            "size_bytes": self.size_bytes,
        }


class OffHostPusher(ABC):
    """Abstract base for off-host pushers."""

    name: str = "abstract"

    @abstractmethod
    def push(self, local_path: Path, *, remote_key: str | None = None) -> PushResult:
        """Upload *local_path* to off-host storage.

        Args:
            local_path: File to upload.
            remote_key: Destination path / object key. Defaults to
                the local file's basename.

        Returns:
            :class:`PushResult` with the URI where the artifact
            landed and timing info.

        Raises:
            OffHostPushError: Transient failure (network, 5xx).
            FileNotFoundError: *local_path* does not exist.
        """
        raise NotImplementedError

    def push_many(
        self, paths: list[Path], *, remote_prefix: str = ""
    ) -> list[PushResult]:
        """Push several files in order. Stops on first failure.

        Returns the list of successful pushes (excluding the failed
        one). Subclasses can override to batch uploads in parallel.
        """
        results: list[PushResult] = []
        for path in paths:
            try:
                results.append(
                    self.push(
                        path,
                        remote_key=f"{remote_prefix}{path.name}" if remote_prefix else path.name,
                    )
                )
            except OffHostPushError:
                raise
        return results


# ── local backend ─────────────────────────────────────────────────────


class LocalPusher(OffHostPusher):
    """Copy artifacts to a second local directory.

    Intended for setups where the two directories live on
    different physical disks (raid ≠ backup). The copy is best-
    effort: a failure raises :class:`OffHostPushError` but never
    deletes the source.
    """

    name = "local"

    def __init__(self, dest_dir: Path | str) -> None:
        self.dest_dir = Path(dest_dir).expanduser()
        self.dest_dir.mkdir(parents=True, exist_ok=True)

    def push(self, local_path: Path, *, remote_key: str | None = None) -> PushResult:
        if not local_path.exists():
            raise FileNotFoundError(local_path)
        key = remote_key or local_path.name
        target = self.dest_dir / key
        start = time.monotonic()
        try:
            # ``shutil.copy2`` preserves mtime / atime for forensic
            # consistency with the local archive.
            shutil.copy2(str(local_path), str(target))
        except OSError as exc:
            raise OffHostPushError(
                f"local copy failed: {local_path} → {target}: {exc}"
            ) from exc
        return PushResult(
            source_path=local_path,
            remote_uri=str(target),
            duration_seconds=time.monotonic() - start,
            size_bytes=local_path.stat().st_size,
        )


# ── null backend (tests / disable) ─────────────────────────────────────


class NullPusher(OffHostPusher):
    """A pusher that discards uploads. Used in tests and to disable
    off-host without changing the engine's API surface."""

    name = "null"

    def __init__(self) -> None:
        self.pushed: list[Path] = []
        self._lock = threading.Lock()

    def push(self, local_path: Path, *, remote_key: str | None = None) -> PushResult:
        if not local_path.exists():
            raise FileNotFoundError(local_path)
        with self._lock:
            self.pushed.append(local_path)
        return PushResult(
            source_path=local_path,
            remote_uri=f"null://{local_path.name}",
            duration_seconds=0.0,
            size_bytes=local_path.stat().st_size,
        )


# ── S3 backend (optional boto3) ───────────────────────────────────────


class S3Pusher(OffHostPusher):
    """Upload to AWS S3 / S3-compatible storage via ``boto3``.

    Requires the optional ``boto3`` package. If not installed,
    :meth:`push` becomes a no-op that logs a warning — the engine
    keeps working, just without off-host.

    Configuration via environment variables:

    =====================  ===========================================
    Variable                Meaning
    =====================  ===========================================
    ``AWS_ACCESS_KEY_ID``   AWS access key
    ``AWS_SECRET_ACCESS_KEY``  AWS secret access key
    ``AWS_SESSION_TOKEN``   Optional STS token
    ``AWS_ENDPOINT_URL``    Optional custom endpoint (MinIO, R2, B2)
    ``AWS_REGION``          AWS region (default ``us-east-1``)
    ``OFFHOST_S3_BUCKET``   Required: destination bucket name
    =====================  ===========================================
    """

    name = "s3"

    def __init__(
        self,
        bucket: str | None = None,
        *,
        prefix: str = "zeloo-state/",
        endpoint_url: str | None = None,
        region: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.bucket = bucket or os.environ.get("OFFHOST_S3_BUCKET", "")
        self.prefix = prefix
        self.endpoint_url = endpoint_url or os.environ.get("AWS_ENDPOINT_URL")
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self._client: Any = client
        self._disabled = False
        if not self._client:
            try:
                import boto3  # type: ignore[import-untyped]
                from botocore.config import Config  # type: ignore[import-untyped]
            except ImportError:
                logger.warning(
                    "boto3 not installed; S3Pusher disabled. "
                    "Install with: pip install boto3"
                )
                self._disabled = True
                return
            if not self.bucket:
                logger.warning("OFFHOST_S3_BUCKET not set; S3Pusher disabled")
                self._disabled = True
                return
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                region_name=self.region,
                config=Config(retries={"max_attempts": 3, "mode": "adaptive"}),
            )

    def push(self, local_path: Path, *, remote_key: str | None = None) -> PushResult:
        if self._disabled:
            logger.debug("S3Pusher disabled; skipping %s", local_path)
            return PushResult(
                source_path=local_path,
                remote_uri="s3://disabled",
                duration_seconds=0.0,
                size_bytes=local_path.stat().st_size if local_path.exists() else 0,
            )
        if not local_path.exists():
            raise FileNotFoundError(local_path)
        key = f"{self.prefix}{remote_key or local_path.name}"
        start = time.monotonic()
        try:
            self._client.upload_file(str(local_path), self.bucket, key)
        except Exception as exc:  # noqa: BLE001
            raise OffHostPushError(
                f"S3 upload failed: {local_path} → s3://{self.bucket}/{key}: {exc}"
            ) from exc
        return PushResult(
            source_path=local_path,
            remote_uri=f"s3://{self.bucket}/{key}",
            duration_seconds=time.monotonic() - start,
            size_bytes=local_path.stat().st_size,
        )


# ── Aliyun OSS backend (optional oss2) ────────────────────────────────


class OSSPusher(OffHostPusher):
    """Upload to Aliyun OSS via ``oss2``.

    Requires the optional ``oss2`` package. Falls back to a no-op
    when missing.

    Configuration via environment variables:

    =====================  ===========================================
    Variable                Meaning
    =====================  ===========================================
    ``OSS_ACCESS_KEY_ID``   OSS access key
    ``OSS_ACCESS_KEY_SECRET``  OSS secret
    ``OSS_ENDPOINT``       e.g. ``https://oss-cn-hangzhou.aliyuncs.com``
    ``OSS_BUCKET``         Required: destination bucket
    =====================  ===========================================
    """

    name = "oss"

    def __init__(
        self,
        bucket: str | None = None,
        *,
        prefix: str = "zeloo-state/",
        endpoint: str | None = None,
        access_key_id: str | None = None,
        access_key_secret: str | None = None,
        bucket_obj: Any | None = None,
    ) -> None:
        self.prefix = prefix
        self._bucket: Any = bucket_obj
        self._disabled = False
        if not self._bucket:
            try:
                import oss2  # type: ignore[import-untyped]
            except ImportError:
                logger.warning(
                    "oss2 not installed; OSSPusher disabled. "
                    "Install with: pip install oss2"
                )
                self._disabled = True
                return
            bucket_name = bucket or os.environ.get("OSS_BUCKET", "")
            endpoint_url = endpoint or os.environ.get("OSS_ENDPOINT", "")
            access_key = access_key_id or os.environ.get("OSS_ACCESS_KEY_ID", "")
            secret = access_key_secret or os.environ.get("OSS_ACCESS_KEY_SECRET", "")
            if not (bucket_name and endpoint_url and access_key and secret):
                logger.warning("OSS env vars missing; OSSPusher disabled")
                self._disabled = True
                return
            self._bucket = oss2.Bucket(oss2.Auth(access_key, secret), endpoint_url, bucket_name)

    def push(self, local_path: Path, *, remote_key: str | None = None) -> PushResult:
        if self._disabled:
            logger.debug("OSSPusher disabled; skipping %s", local_path)
            return PushResult(
                source_path=local_path,
                remote_uri="oss://disabled",
                duration_seconds=0.0,
                size_bytes=local_path.stat().st_size if local_path.exists() else 0,
            )
        if not local_path.exists():
            raise FileNotFoundError(local_path)
        key = f"{self.prefix}{remote_key or local_path.name}"
        start = time.monotonic()
        try:
            self._bucket.put_object_from_file(key, str(local_path))
        except Exception as exc:  # noqa: BLE001
            raise OffHostPushError(
                f"OSS upload failed: {local_path} → {key}: {exc}"
            ) from exc
        return PushResult(
            source_path=local_path,
            remote_uri=f"oss://{self._bucket.bucket_name}/{key}",
            duration_seconds=time.monotonic() - start,
            size_bytes=local_path.stat().st_size,
        )


# ── factory ───────────────────────────────────────────────────────────


def build_default_pusher(
    *,
    local_dest: Path | str | None = None,
    prefer: str | None = None,
) -> OffHostPusher:
    """Build a sensible pusher from the current environment.

    Resolution order:

    1. If ``prefer`` is given (``"local"``, ``"s3"``, ``"oss"``,
       ``"null"``) — return that backend.
    2. Otherwise honour ``OFFHOST_BACKEND`` env var (same values).
    3. If ``local_dest`` is provided, return :class:`LocalPusher`.
    4. If ``OFFHOST_S3_BUCKET`` is set and ``boto3`` is installed,
       return :class:`S3Pusher`.
    5. If ``OSS_BUCKET`` is set and ``oss2`` is installed,
       return :class:`OSSPusher`.
    6. Default: :class:`NullPusher` (so callers don't have to
       special-case ``None``).

    Tests inject a :class:`LocalPusher` (or :class:`NullPusher`)
    directly to keep behaviour deterministic.
    """
    backend = (prefer or os.environ.get("OFFHOST_BACKEND", "")).lower()
    if backend == "null":
        return NullPusher()
    if backend == "local" or local_dest is not None:
        if local_dest is None:
            raise ValueError("local backend requires local_dest")
        return LocalPusher(local_dest)
    if backend == "s3":
        return S3Pusher()
    if backend == "oss":
        return OSSPusher()
    # Auto-detect from env.
    if os.environ.get("OFFHOST_S3_BUCKET"):
        return S3Pusher()
    if os.environ.get("OSS_BUCKET"):
        return OSSPusher()
    return NullPusher()


__all__ = [
    "OffHostPusher",
    "OffHostPushError",
    "PushResult",
    "LocalPusher",
    "NullPusher",
    "S3Pusher",
    "OSSPusher",
    "build_default_pusher",
]