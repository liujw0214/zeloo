"""Video download utilities for persisting generated videos to local files.

Example usage::

    from video_gen import get_provider
    from video_gen.download import download_video_result

    provider = get_provider("deepinfra_video")
    resp = provider.generate("A cat sitting on a windowsill")
    path = download_video_result(resp.results[0], output_dir="./outputs")
    print(f"Saved to {path}")
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

BLOCK_SIZE = 8192

_VERSION_RE = re.compile(r"[^\w\-_.]", re.UNICODE)


def _sanitize_name(text: str, max_len: int = 48) -> str:
    cleaned = _VERSION_RE.sub("_", text)
    cleaned = cleaned.strip("_ ")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("_ ")
    return cleaned.strip("_.-") or "video"


def _url_to_ext(url: str) -> str:
    path = url.split("?")[0].split("#")[0]
    for ext in (".mp4", ".webm", ".mov", ".avi", ".mkv"):
        if path.endswith(ext):
            return ext
    return ".mp4"


def _make_filename(result: Any, ext: str | None = None) -> str:
    prompt = getattr(result, "prompt", "") if hasattr(result, "prompt") else ""
    provider = getattr(result, "provider", "video") if hasattr(result, "provider") else "video"
    model = getattr(result, "model", "") if hasattr(result, "model") else ""
    seed = getattr(result, "seed", None)
    suffix = ""
    if seed is not None:
        suffix = f"_s{seed}"
    base = _sanitize_name(prompt or f"{provider}_{model}")
    if ext is None:
        url = getattr(result, "url", "") if hasattr(result, "url") else ""
        ext = _url_to_ext(url)
    return f"{base}{suffix}{ext}"


def get_output_path(result: Any, output_dir: str | Path, ext: str | None = None) -> Path:
    """Generate a local output path for a :class:`VideoResult` or similar object.

    Args:
        result: Any object with ``url``, ``provider``, ``model``, ``prompt``,
                and optional ``seed`` attributes.
        output_dir: Directory where the file will be saved.
        ext: Override the file extension. If ``None`` it is inferred from the URL.

    Returns:
        A :class:`pathlib.Path` within *output_dir*.
    """
    url = getattr(result, "url", "") if hasattr(result, "url") else ""
    if ext is None:
        ext = _url_to_ext(url)
    filename = _make_filename(result, ext=ext)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    return out / filename


def download_video(
    url: str,
    output_path: str | Path,
    timeout: float = 300.0,
    progress_callback: Any = None,
) -> Path:
    """Download a video from *url* to *output_path*.

    Supports HTTP/HTTPS URLs. Follows up to 10 redirects.

    Args:
        url: The video file URL.
        output_path: Local file path to write. Parent directories are created
            automatically.
        timeout: Maximum time in seconds for the download.
        progress_callback: Optional ``(bytes_downloaded: int, total: int | None) -> None``.
            Called periodically as data is received.

    Returns:
        The resolved :class:`pathlib.Path`.

    Raises:
        httpx.HTTPStatusError: When the server returns a non-2xx status.
        httpx.TransportError: When the connection fails.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        max_redirects=10,
    ) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0)) or None
            downloaded = 0
            with output_path.open("wb") as fh:
                for chunk in resp.iter_bytes(BLOCK_SIZE):
                    if chunk:
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total)
    logger.info("Downloaded %s -> %s", url, output_path)
    return output_path


def download_video_result(
    result: Any,
    output_dir: str | Path,
    overwrite: bool = False,
    ext: str | None = None,
    timeout: float = 300.0,
    progress_callback: Any = None,
) -> Path:
    """Download a :class:`VideoResult` to a local file.

    This is a convenience wrapper that extracts the URL from *result*,
    generates an appropriate filename, and saves the file to *output_dir*.

    Args:
        result: A :class:`VideoResult` (or any duck-typed object with
                ``url``, ``provider``, ``model``, ``prompt``, and optional ``seed``).
        output_dir: Directory where the file will be saved.
        overwrite: If ``False`` (default) and the target file already exists,
                   a numeric suffix ``_1``, ``_2``, … is appended. If ``True``
                   the existing file is replaced.
        ext: Override the file extension.
        timeout: Maximum time in seconds for the download.
        progress_callback: Optional progress callback passed to :func:`download_video`.

    Returns:
        The resolved :class:`pathlib.Path` of the saved file.

    Raises:
        ValueError: When *result* has no URL.
    """
    url = getattr(result, "url", None)
    if not url:
        raise ValueError("VideoResult has no URL to download")

    path = get_output_path(result, output_dir, ext=ext)

    if path.exists() and not overwrite:
        stem = path.stem
        for i in range(1, 1000):
            candidate = path.with_name(f"{stem}_{i}{path.suffix}")
            if not candidate.exists():
                path = candidate
                break

    return download_video(
        url,
        path,
        timeout=timeout,
        progress_callback=progress_callback,
    )


def verify_checksum(file_path: str | Path, expected_sha256: str) -> bool:
    """Verify that *file_path* has the given SHA-256 checksum.

    Args:
        file_path: Path to the downloaded file.
        expected_sha256: Lowercase 64-character hex string.

    Returns:
        ``True`` if the checksum matches, ``False`` otherwise.
    """
    sha = hashlib.sha256()
    path = Path(file_path)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(BLOCK_SIZE), b""):
            sha.update(chunk)
    return sha.hexdigest() == expected_sha256.lower()


__all__ = [
    "download_video",
    "download_video_result",
    "get_output_path",
    "verify_checksum",
]
