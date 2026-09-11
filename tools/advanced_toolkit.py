"""Advanced toolkit — JSON/Diff/Regex/UUID/Base64/etc. utilities."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from datetime import UTC
from typing import Any

from tools.base import tool


@tool(toolset="advanced")
def json_validate(json_string: str) -> str:
    """Validate a JSON string and return info about its structure.

    Args:
        json_string: The JSON string to validate.
    """
    try:
        parsed = json.loads(json_string)
        keys = []
        if isinstance(parsed, dict):
            keys = list(parsed.keys())
            kind = "object"
        elif isinstance(parsed, list):
            keys = [str(i) for i in range(len(parsed))]
            kind = "array"
        else:
            kind = type(parsed).__name__
        return json.dumps({
            "valid": True,
            "type": kind,
            "keys_or_length": len(keys),
            "preview": str(parsed)[:200],
        }, indent=2)
    except json.JSONDecodeError as e:
        return json.dumps({
            "valid": False,
            "error": str(e),
            "line": e.lineno,
            "column": e.colno,
        }, indent=2)


@tool(toolset="advanced")
def json_format(json_string: str, indent: int = 2) -> str:
    """Format JSON string with proper indentation.

    Args:
        json_string: The JSON string to format.
        indent: Indentation spaces (default 2).
    """
    try:
        parsed = json.loads(json_string)
        return json.dumps(parsed, indent=indent, ensure_ascii=False)
    except json.JSONDecodeError as e:
        return json.dumps({"error": str(e)}, indent=2)


@tool(toolset="advanced")
def json_minify(json_string: str) -> str:
    """Minify JSON string by removing whitespace."""
    try:
        parsed = json.loads(json_string)
        return json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)
    except json.JSONDecodeError as e:
        return json.dumps({"error": str(e)}, indent=2)


@tool(toolset="advanced")
def json_path(json_string: str, path: str) -> str:
    """Extract a value from JSON using dot notation path.

    Args:
        json_string: The JSON string to query.
        path: Dot-separated path (e.g. 'user.profile.email').
    """
    try:
        data = json.loads(json_string)
        keys = path.split(".")
        current: Any = data
        for key in keys:
            if "[" in key:
                base, idx = key.split("[")
                idx = int(idx.rstrip("]"))
                current = current[base][idx]
            else:
                if isinstance(current, dict):
                    current = current[key]
                elif isinstance(current, list):
                    current = current[int(key)]
                else:
                    return json.dumps({"error": f"Cannot index {type(current).__name__}"})
        return json.dumps({"path": path, "value": current}, indent=2)
    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
        return json.dumps({"error": str(e)}, indent=2)


@tool(toolset="advanced")
def diff_text(text_a: str, text_b: str, context_lines: int = 3) -> str:
    """Show line-by-line diff between two texts.

    Args:
        text_a: First text.
        text_b: Second text.
        context_lines: Number of context lines.
    """
    import difflib
    diff = difflib.unified_diff(
        text_a.splitlines(keepends=True),
        text_b.splitlines(keepends=True),
        fromfile="text_a",
        tofile="text_b",
        n=context_lines,
    )
    return "".join(diff)


@tool(toolset="advanced")
def regex_test(pattern: str, text: str) -> str:
    """Test regex pattern against text, return all matches.

    Args:
        pattern: Regular expression pattern.
        text: Text to search in.
    """
    try:
        matches = re.findall(pattern, text)
        if not matches:
            return json.dumps({"matches": [], "count": 0}, indent=2)
        spans = []
        for m in re.finditer(pattern, text):
            spans.append({
                "match": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "groups": list(m.groups()),
            })
        return json.dumps({
            "count": len(matches),
            "matches": matches[:50],
            "spans": spans[:50],
        }, indent=2, ensure_ascii=False)
    except re.error as e:
        return json.dumps({"error": str(e)}, indent=2)


@tool(toolset="advanced")
def regex_extract(pattern: str, text: str, group: int = 1) -> str:
    """Extract first capture group from regex pattern matches.

    Args:
        pattern: Regular expression pattern.
        text: Text to search in.
        group: Capture group number to extract.
    """
    matches = re.findall(pattern, text)
    if not matches:
        return json.dumps({"extracted": [], "count": 0})
    extracted = []
    for m in matches:
        if isinstance(m, tuple):
            extracted.append(m[group - 1] if len(m) >= group else "")
        else:
            extracted.append(m if group == 0 else m)
    return json.dumps({"extracted": extracted, "count": len(extracted)}, indent=2)


@tool(toolset="advanced")
def uuid_generate(version: int = 4, count: int = 1) -> str:
    """Generate UUIDs.

    Args:
        version: UUID version (1, 4, or 7).
        count: Number of UUIDs to generate (max 100).
    """
    count = min(count, 100)
    uuids = []
    for _ in range(count):
        if version == 1:
            uuids.append(str(uuid.uuid1()))
        elif version == 4:
            uuids.append(str(uuid.uuid4()))
        elif version == 7:
            uuids.append(str(uuid.uuid7()) if hasattr(uuid, "uuid7") else str(uuid.uuid4()))
        else:
            uuids.append(str(uuid.uuid4()))
    return json.dumps({"uuids": uuids, "count": len(uuids)}, indent=2)


@tool(toolset="advanced")
def hash_text(text: str, algorithm: str = "sha256") -> str:
    """Compute hash of text using specified algorithm.

    Args:
        text: Text to hash.
        algorithm: Hash algorithm (md5/sha1/sha256/sha384/sha512).
    """
    try:
        h = hashlib.new(algorithm)
        h.update(text.encode("utf-8"))
        return json.dumps({
            "algorithm": algorithm,
            "hash": h.hexdigest(),
            "length": len(text),
        }, indent=2)
    except ValueError as e:
        return json.dumps({"error": str(e)}, indent=2)


@tool(toolset="advanced")
def base64_encode(text: str) -> str:
    """Encode text to Base64.

    Args:
        text: Text to encode.
    """
    encoded = base64.b64encode(text.encode("utf-8")).decode("utf-8")
    return json.dumps({
        "encoded": encoded,
        "decoded": text,
        "length": len(encoded),
    }, indent=2)


@tool(toolset="advanced")
def base64_decode(encoded: str) -> str:
    """Decode Base64 to text.

    Args:
        encoded: Base64 encoded string.
    """
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
        return json.dumps({
            "encoded": encoded,
            "decoded": decoded,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


@tool(toolset="advanced")
def timestamp_now() -> str:
    """Get current Unix timestamp and ISO format."""
    now = __import__("time").time()
    from datetime import datetime
    iso = datetime.fromtimestamp(now, tz=UTC).isoformat()
    return json.dumps({
        "unix": int(now),
        "unix_ms": int(now * 1000),
        "iso8601": iso,
        "utc": iso,
    }, indent=2)


@tool(toolset="advanced")
def timestamp_to_iso(timestamp: float) -> str:
    """Convert Unix timestamp to ISO 8601 format.

    Args:
        timestamp: Unix timestamp (seconds or milliseconds).
    """
    from datetime import datetime
    if timestamp > 1e12:
        timestamp = timestamp / 1000
    iso = datetime.fromtimestamp(timestamp, tz=UTC).isoformat()
    return json.dumps({"unix": timestamp, "iso8601": iso}, indent=2)


@tool(toolset="advanced")
def text_diff_summary(text_a: str, text_b: str) -> str:
    """Get a summary of differences between two texts.

    Args:
        text_a: First text.
        text_b: Second text.
    """
    lines_a = text_a.splitlines()
    lines_b = text_b.splitlines()
    added = len([ln for ln in lines_b if ln not in lines_a])
    removed = len([ln for ln in lines_a if ln not in lines_b])
    common = len(set(lines_a) & set(lines_b))
    return json.dumps({
        "a_lines": len(lines_a),
        "b_lines": len(lines_b),
        "common_lines": common,
        "added_lines": added,
        "removed_lines": removed,
        "similarity": round(common / max(len(lines_a), len(lines_b), 1), 3),
    }, indent=2)


@tool(toolset="advanced")
def slugify(text: str) -> str:
    """Convert text to URL-friendly slug.

    Args:
        text: Text to slugify.
    """
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = slug.strip("-")
    return json.dumps({"original": text, "slug": slug}, indent=2)


@tool(toolset="advanced")
def word_count(text: str) -> str:
    """Count words, characters, and lines in text.

    Args:
        text: Text to analyze.
    """
    lines = text.splitlines()
    words = text.split()
    return json.dumps({
        "characters": len(text),
        "characters_no_spaces": len(re.sub(r"\s", "", text)),
        "words": len(words),
        "lines": len(lines),
        "unique_words": len(set(words)),
    }, indent=2)


TOOLS = [
    json_validate,
    json_format,
    json_minify,
    json_path,
    diff_text,
    regex_test,
    regex_extract,
    uuid_generate,
    hash_text,
    base64_encode,
    base64_decode,
    timestamp_now,
    timestamp_to_iso,
    text_diff_summary,
    slugify,
    word_count,
]


__all__ = ["TOOLS"]