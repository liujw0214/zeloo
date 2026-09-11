"""Tests for video_gen.download utilities."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from video_gen.download import (
    _make_filename,
    _sanitize_name,
    _url_to_ext,
    download_video,
    download_video_result,
    get_output_path,
    verify_checksum,
)


class _DummyResult:
    url = "https://cdn.example.com/output.mp4"
    prompt = "A cat sitting on a windowsill"
    provider = "deepinfra"
    model = "hunyuan-video"
    seed = 42


class _DummyResultNoSeed:
    url = "https://cdn.example.com/video.webm"
    prompt = "Dog running"
    provider = "fal"
    model = "kling"
    seed = None


def test_sanitize_name_trims():
    assert _sanitize_name("  hello world  ") == "hello_world"


def test_sanitize_name_removes_special_chars():
    assert _sanitize_name("foo<bar>baz") == "foo_bar_baz"


def test_sanitize_name_truncates_long():
    long_name = "a" * 100
    result = _sanitize_name(long_name)
    assert len(result) <= 48
    assert result == "a" * 48


def test_sanitize_name_empty_falls_back_to_video():
    assert _sanitize_name("...//") == "video"


def test_url_to_ext_mp4():
    assert _url_to_ext("https://example.com/video.mp4?token=abc") == ".mp4"


def test_url_to_ext_webm():
    assert _url_to_ext("https://example.com/clip.webm#section") == ".webm"


def test_url_to_ext_unknown_falls_back_to_mp4():
    assert _url_to_ext("https://example.com/clip") == ".mp4"


def test_make_filename_with_seed():
    r = _DummyResult()
    name = _make_filename(r)
    assert name.startswith("A_cat_sitting_on_a_windowsill")
    assert "_s42" in name
    assert name.endswith(".mp4")


def test_make_filename_no_seed():
    r = _DummyResultNoSeed()
    name = _make_filename(r)
    assert "Dog_running" in name
    assert name.endswith(".webm")


def test_get_output_path_creates_dir(tmp_path: Path):
    r = _DummyResult()
    path = get_output_path(r, tmp_path / "videos")
    assert path.parent.exists()
    assert path.suffix == ".mp4"


def test_get_output_path_respects_ext_override(tmp_path: Path):
    r = _DummyResult()
    path = get_output_path(r, tmp_path, ext=".webm")
    assert path.suffix == ".webm"


def test_download_video_writes_file(tmp_path: Path, monkeypatch):
    content = b"\x00\x01\x02" * 100

    mock_stream = MagicMock()
    mock_stream.__enter__ = MagicMock(return_value=mock_stream)
    mock_stream.__exit__ = MagicMock(return_value=None)
    mock_stream.status_code = 200
    mock_stream.headers = {"content-length": str(len(content))}
    mock_stream.raise_for_status = MagicMock()
    mock_stream.iter_bytes = MagicMock(return_value=[content])

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_stream)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    with patch("httpx.Client", return_value=mock_client):
        target = tmp_path / "video.mp4"
        path = download_video("https://cdn.example.com/video.mp4", target)

    assert path.exists()
    assert path.read_bytes() == content


def test_download_video_result_no_url_raises():
    class NoUrlResult:
        pass

    with pytest.raises(ValueError, match="no URL"):
        download_video_result(NoUrlResult(), output_dir="/tmp")


def test_download_video_result_creates_file(tmp_path: Path):
    content = b"fake video data"
    r = _DummyResult()

    mock_stream = MagicMock()
    mock_stream.__enter__ = MagicMock(return_value=mock_stream)
    mock_stream.__exit__ = MagicMock(return_value=None)
    mock_stream.status_code = 200
    mock_stream.headers = {"content-length": str(len(content))}
    mock_stream.raise_for_status = MagicMock()
    mock_stream.iter_bytes = MagicMock(return_value=[content])

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_stream)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    with patch("httpx.Client", return_value=mock_client):
        path = download_video_result(r, tmp_path)

    assert path.exists()
    assert path.read_bytes() == content


def test_download_video_result_no_overwrite_suffix(tmp_path: Path):
    content1 = b"first"
    content2 = b"second"
    r = _DummyResult()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-length": "1000"}
    mock_response.raise_for_status = MagicMock()

    def iter_chunks():
        yield content1

    def iter_chunks2():
        yield content2

    for _label, chunks in [("first", iter_chunks()), ("second", iter_chunks2())]:
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=None)
        mock_stream.status_code = 200
        mock_stream.headers = {"content-length": "1000"}
        mock_stream.raise_for_status = MagicMock()
        mock_stream.iter_bytes = MagicMock(return_value=chunks)

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=mock_stream)

        with patch("httpx.Client") as MockClient:
            MockClient.return_value = mock_client
            download_video_result(r, tmp_path, overwrite=False)

    files = list(tmp_path.glob("*"))
    assert len(files) == 2
    names = [f.name for f in files]
    assert any("_1." in n for n in names)


def test_verify_checksum_match(tmp_path: Path):
    content = b"hello world"
    sha = hashlib.sha256(content).hexdigest()
    path = tmp_path / "test.bin"
    path.write_bytes(content)

    assert verify_checksum(path, sha) is True


def test_verify_checksum_mismatch(tmp_path: Path):
    path = tmp_path / "test.bin"
    path.write_bytes(b"hello world")
    wrong_sha = "0" * 64

    assert verify_checksum(path, wrong_sha) is False


def test_verify_checksum_uppercase(tmp_path: Path):
    content = b"data"
    sha = hashlib.sha256(content).hexdigest().upper()
    path = tmp_path / "test.bin"
    path.write_bytes(content)

    assert verify_checksum(path, sha) is True
