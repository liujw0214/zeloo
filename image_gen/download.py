"""Image download utilities for image_gen providers."""
from __future__ import annotations

import hashlib
import logging
import re
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_CHUNK_BYTES = 1024 * 1024 * 64
DEFAULT_TIMEOUT = 60


def sanitize_filename(text: str) -> str:
    text = re.sub(r"[<>:\"/\\/|?*]", "_", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_.")


def get_output_path(
    output_dir: str | Path,
    prompt: str,
    model: str = "",
    extension: str = ".png",
    overwrite: bool = False,
) -> Path:
    base = sanitize_filename(prompt or "image")
    if model:
        base = sanitize_filename(model) + "_" + base
    if len(base) > 200:
        base = base[:200]
    filename = base + extension
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    img_path = out_dir / filename
    if overwrite:
        return img_path
    counter = 1
    stem = img_path.stem
    while img_path.exists():
        img_path = out_dir / (stem + "_" + str(counter) + img_path.suffix)
        counter += 1
    return img_path


def download_image(
    url: str,
    img_path: Path,
    timeout: int = DEFAULT_TIMEOUT,
    overwrite: bool = False,
    expected_hash: str | None = None,
) -> dict[str, Any]:
    if img_path.exists() and not overwrite:
        sz = img_path.stat().st_size
        return {
            "success": True,
            "path": str(img_path),
            "url": url,
            "size_bytes": sz,
            "skipped": True,
        }
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Zeloo/1.0")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = b""
            while True:
                chunk = resp.read(MAX_CHUNK_BYTES)
                if not chunk:
                    break
                data += chunk
    except Exception as exc:  # noqa: BLE001
        logger.error("Download failed: %s", exc)
        return {"success": False, "error": str(exc), "path": None}

    if expected_hash:
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected_hash:
            return {"success": False, "error": "Checksum mismatch", "path": None}

    img_path.parent.mkdir(parents=True, exist_ok=True)
    with open(img_path, "wb") as fh:
        fh.write(data)

    return {
        "success": True,
        "path": str(img_path),
        "url": url,
        "size_bytes": len(data),
        "skipped": False,
    }


def download_image_result(
    result: Any,
    output_dir: str | Path = ".",
    overwrite: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    if result is None:
        return {
            "success": False,
            "paths": [],
            "errors": ["result is None"],
            "total": 0,
            "downloaded": 0,
        }

    items = getattr(result, "results", None)
    if items is None:
        items = [result]

    paths: list[str] = []
    errors: list[str] = []
    skipped: list[str] = []

    for img in items:
        img_url = getattr(img, "url", None) or ""
        if not img_url:
            errors.append("No URL in image result")
            continue
        img_model = getattr(img, "model", "") or ""
        img_prompt = getattr(img, "revised_prompt", "") or getattr(img, "prompt", "") or img_url
        ext = Path(img_url).suffix.lower() or ".png"
        out_path = get_output_path(output_dir, img_prompt, img_model, ext, overwrite)
        dl = download_image(img_url, out_path, timeout=timeout, overwrite=overwrite)
        if dl.get("success"):
            paths.append(str(dl.get("path", "")))
        elif dl.get("skipped"):
            skipped.append(str(dl.get("path", "")))
        else:
            errors.append(str(dl.get("error", "Unknown error")))

    return {
        "success": len(errors) == 0,
        "paths": paths,
        "errors": errors,
        "total": len(items),
        "downloaded": len(paths),
        "skipped": skipped,
    }


def verify_checksum(path: Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with open(path, "rb") as fh:
        while chunk := fh.read(MAX_CHUNK_BYTES):
            h.update(chunk)
    return h.hexdigest()


__all__ = [
    "download_image",
    "download_image_result",
    "get_output_path",
    "verify_checksum",
    "sanitize_filename",
]
