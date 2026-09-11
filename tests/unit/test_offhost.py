"""Tests for ``zeloo_state.offhost`` — pushers.

The unit tests cover:
  * ``LocalPusher`` — real file copy semantics.
  * ``NullPusher`` — records uploads but discards.
  * ``S3Pusher`` / ``OSSPusher`` — disabled-mode behaviour without
    real cloud deps.
  * ``build_default_pusher`` — env-driven factory selection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zeloo_state.offhost import (
    LocalPusher,
    NullPusher,
    OffHostPushError,
    OSSPusher,
    PushResult,
    S3Pusher,
    build_default_pusher,
)

# ── helpers ───────────────────────────────────────────────────────────


@pytest.fixture
def src_and_dest(tmp_path: Path) -> tuple[Path, Path]:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dest_dir = tmp_path / "dest"
    src = src_dir / "wal-1.bin"
    src.write_bytes(b"\x00\x01\x02\x03hello")
    return src, dest_dir


# ── LocalPusher ────────────────────────────────────────────────────────


class TestLocalPusher:
    def test_push_copies_file(self, src_and_dest: tuple[Path, Path]) -> None:
        src, dest = src_and_dest
        pusher = LocalPusher(dest)
        result = pusher.push(src)
        assert isinstance(result, PushResult)
        assert (dest / src.name).is_file()
        assert (dest / src.name).read_bytes() == src.read_bytes()

    def test_push_creates_dest_dir(self, tmp_path: Path) -> None:
        pusher = LocalPusher(tmp_path / "missing" / "nested")
        src = tmp_path / "a.bin"
        src.write_bytes(b"data")
        pusher.push(src)
        assert (tmp_path / "missing" / "nested" / "a.bin").is_file()

    def test_push_missing_source_raises(self, tmp_path: Path) -> None:
        pusher = LocalPusher(tmp_path / "dest")
        with pytest.raises(FileNotFoundError):
            pusher.push(tmp_path / "no-such.bin")

    def test_push_with_remote_key(self, src_and_dest: tuple[Path, Path]) -> None:
        src, dest = src_and_dest
        pusher = LocalPusher(dest)
        pusher.push(src, remote_key="custom-name.bin")
        assert (dest / "custom-name.bin").is_file()
        assert not (dest / src.name).exists()

    def test_push_preserves_mtime(self, src_and_dest: tuple[Path, Path]) -> None:
        src, dest = src_and_dest
        pusher = LocalPusher(dest)
        pusher.push(src)
        copied = dest / src.name
        # ``shutil.copy2`` preserves mtime; allow ±1s slop for FS
        # rounding.
        assert abs(copied.stat().st_mtime - src.stat().st_mtime) < 1.0

    def test_offhost_push_error_propagates(self, src_and_dest: tuple[Path, Path]) -> None:
        src, dest = src_and_dest
        pusher = LocalPusher(dest)

        # Simulate a copy failure by making the dest dir read-only
        # *after* construction.
        from unittest.mock import patch

        with patch("shutil.copy2", side_effect=OSError("disk full")):
            with pytest.raises(OffHostPushError, match="disk full"):
                pusher.push(src)

    def test_push_many_returns_all(self, src_and_dest: tuple[Path, Path]) -> None:
        src, dest = src_and_dest
        # Make two more sources.
        b = src.parent / "wal-2.bin"
        b.write_bytes(b"second")
        c = src.parent / "wal-3.bin"
        c.write_bytes(b"third")
        pusher = LocalPusher(dest)
        results = pusher.push_many([src, b, c])
        assert len(results) == 3
        assert (dest / "wal-1.bin").is_file()
        assert (dest / "wal-2.bin").is_file()
        assert (dest / "wal-3.bin").is_file()


# ── NullPusher ─────────────────────────────────────────────────────────


class TestNullPusher:
    def test_records_uploads(self, tmp_path: Path) -> None:
        src = tmp_path / "x.bin"
        src.write_bytes(b"data")
        pusher = NullPusher()
        result = pusher.push(src)
        assert pusher.pushed == [src]
        assert result.remote_uri == "null://x.bin"
        assert result.size_bytes == 4

    def test_missing_source_raises(self, tmp_path: Path) -> None:
        pusher = NullPusher()
        with pytest.raises(FileNotFoundError):
            pusher.push(tmp_path / "missing.bin")

    def test_thread_safe_recording(self, tmp_path: Path) -> None:
        import threading

        src = tmp_path / "concurrent.bin"
        src.write_bytes(b"x")
        pusher = NullPusher()
        threads = [
            threading.Thread(target=pusher.push, args=(src,)) for _ in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(pusher.pushed) == 20


# ── S3Pusher / OSSPusher (disabled mode) ──────────────────────────────


class TestS3PusherDisabled:
    def test_disabled_when_boto3_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Replace ``boto3`` import via ``sys.modules`` trick.
        import sys

        monkeypatch.setitem(sys.modules, "boto3", None)
        pusher = S3Pusher(bucket="x")
        # Push becomes a no-op (doesn't raise, doesn't upload).
        result = pusher.push(Path("/tmp/x"))
        assert result.remote_uri == "s3://disabled"


class TestOSSPusherDisabled:
    def test_disabled_when_oss2_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys

        monkeypatch.setitem(sys.modules, "oss2", None)
        pusher = OSSPusher()
        result = pusher.push(Path("/tmp/x"))
        assert result.remote_uri == "oss://disabled"

    def test_disabled_when_env_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Clear all OSS env vars.
        for var in ("OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET", "OSS_ENDPOINT", "OSS_BUCKET"):
            monkeypatch.delenv(var, raising=False)
        pusher = OSSPusher()
        assert pusher._disabled is True

    def test_disabled_when_partial_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OSS_ACCESS_KEY_ID", "id")
        # Missing secret + endpoint + bucket.
        monkeypatch.delenv("OSS_ACCESS_KEY_SECRET", raising=False)
        monkeypatch.delenv("OSS_ENDPOINT", raising=False)
        monkeypatch.delenv("OSS_BUCKET", raising=False)
        pusher = OSSPusher()
        assert pusher._disabled is True


class TestS3PusherWithClient:
    def test_push_uses_injected_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Provide a stub client; the pusher should call upload_file.
        calls: list[tuple[str, str, str]] = []

        class StubClient:
            def upload_file(self, file_path: str, bucket: str, key: str) -> None:
                calls.append((file_path, bucket, key))

        src = tmp_path / "wal-1.bin"
        src.write_bytes(b"x")
        pusher = S3Pusher(bucket="mybucket", prefix="zeloo/", client=StubClient())
        result = pusher.push(src)
        assert len(calls) == 1
        assert calls[0][1] == "mybucket"
        assert calls[0][2] == "zeloo/wal-1.bin"
        assert result.remote_uri == "s3://mybucket/zeloo/wal-1.bin"

    def test_push_with_remote_key(
        self, tmp_path: Path
    ) -> None:
        calls: list[tuple[str, str, str]] = []

        class StubClient:
            def upload_file(self, file_path: str, bucket: str, key: str) -> None:
                calls.append((file_path, bucket, key))

        src = tmp_path / "a.bin"
        src.write_bytes(b"x")
        pusher = S3Pusher(bucket="bk", prefix="p/", client=StubClient())
        pusher.push(src, remote_key="renamed.bin")
        assert calls[0][2] == "p/renamed.bin"

    def test_upload_failure_raises(
        self, tmp_path: Path
    ) -> None:
        class FailingClient:
            def upload_file(self, *args: object, **kwargs: object) -> None:
                raise RuntimeError("network error")

        src = tmp_path / "a.bin"
        src.write_bytes(b"x")
        pusher = S3Pusher(bucket="bk", client=FailingClient())
        with pytest.raises(OffHostPushError, match="network error"):
            pusher.push(src)


# ── factory ───────────────────────────────────────────────────────────


class TestBuildDefaultPusher:
    def test_returns_null_when_no_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in (
            "OFFHOST_BACKEND",
            "OFFHOST_S3_BUCKET",
            "OSS_BUCKET",
        ):
            monkeypatch.delenv(var, raising=False)
        pusher = build_default_pusher()
        assert isinstance(pusher, NullPusher)

    def test_explicit_local(self, tmp_path: Path) -> None:
        pusher = build_default_pusher(local_dest=tmp_path / "dest")
        assert isinstance(pusher, LocalPusher)
        assert pusher.dest_dir == tmp_path / "dest"

    def test_prefer_overrides_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OFFHOST_BACKEND", "null")
        pusher = build_default_pusher(local_dest=tmp_path / "d", prefer="local")
        assert isinstance(pusher, LocalPusher)

    def test_local_backend_without_dest_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OFFHOST_BACKEND", "local")
        with pytest.raises(ValueError, match="local_dest"):
            build_default_pusher()

    def test_null_backend_forces_null(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OFFHOST_BACKEND", "null")
        pusher = build_default_pusher(local_dest=tmp_path / "d")
        assert isinstance(pusher, NullPusher)

    def test_s3_bucket_env_auto_selects(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OFFHOST_BACKEND", raising=False)
        monkeypatch.setenv("OFFHOST_S3_BUCKET", "mybucket")
        pusher = build_default_pusher()
        assert isinstance(pusher, S3Pusher)
        assert pusher.bucket == "mybucket"

    def test_oss_bucket_env_auto_selects(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OFFHOST_BACKEND", raising=False)
        monkeypatch.delenv("OFFHOST_S3_BUCKET", raising=False)
        # Disable boto3 import path so S3Pusher isn't picked instead.
        import sys

        monkeypatch.setitem(sys.modules, "boto3", None)
        monkeypatch.setenv("OSS_BUCKET", "mybucket")
        pusher = build_default_pusher()
        # If oss2 isn't installed, OSSPusher self-disables but is
        # still an instance.
        assert isinstance(pusher, OSSPusher)