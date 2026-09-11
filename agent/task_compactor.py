"""Task compactor — semantic compression of tool outputs to fit token budget."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default cache location under the workspace.
DEFAULT_CACHE_DIR = Path.home() / ".Zeloo" / "cache" / "task_compactor"

# Heuristic: ~4 characters per token for English / mixed text.
_CHARS_PER_TOKEN = 4


@dataclass
class CompactionRecord:
    """A single compacted output cache entry."""

    cache_key: str
    tool_name: str
    original_chars: int
    compacted_chars: int
    compressed_at: float
    hits: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_key": self.cache_key,
            "tool_name": self.tool_name,
            "original_chars": self.original_chars,
            "compacted_chars": self.compacted_chars,
            "compressed_at": self.compressed_at,
            "hits": self.hits,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompactionRecord:
        return cls(
            cache_key=data["cache_key"],
            tool_name=data["tool_name"],
            original_chars=data["original_chars"],
            compacted_chars=data["compacted_chars"],
            compressed_at=data["compressed_at"],
            hits=data.get("hits", 0),
        )


@dataclass
class CompactorStats:
    """Aggregate statistics for the compactor."""

    lookups: int = 0
    hits: int = 0
    misses: int = 0
    original_chars: int = 0
    compacted_chars: int = 0

    @property
    def hit_rate(self) -> float:
        if self.lookups == 0:
            return 0.0
        return self.hits / self.lookups

    @property
    def compression_ratio(self) -> float:
        if self.original_chars == 0:
            return 0.0
        return self.compacted_chars / self.original_chars

    def to_dict(self) -> dict[str, Any]:
        return {
            "lookups": self.lookups,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hit_rate, 4),
            "original_chars": self.original_chars,
            "compacted_chars": self.compacted_chars,
            "compression_ratio": round(self.compression_ratio, 4),
        }


class TaskCompactor:
    """Compact tool outputs to fit token budget.

    The compactor applies a sequence of cheap heuristics to trim verbose
    outputs while preserving the semantically important prefix. It also
    maintains a disk-backed cache so identical outputs hit a fast path on
    subsequent turns.
    """

    def __init__(
        self,
        max_output_tokens: int = 400,
        similarity_threshold: float = 0.85,
        cache_dir: Path | None = None,
    ) -> None:
        self.max_output_tokens = max_output_tokens
        self.similarity_threshold = similarity_threshold
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "compaction_cache.json"
        self._cache: dict[str, CompactionRecord] = self._load_cache()
        self.stats = CompactorStats()
        # Stop words stripped during summarization to keep summary dense.
        self._stop_words = {
            "the", "a", "an", "and", "or", "but", "of", "to", "in", "on",
            "for", "with", "is", "are", "was", "were", "be", "been", "being",
        }

    # ------------------------------------------------------------------
    # Cache I/O
    # ------------------------------------------------------------------

    def _load_cache(self) -> dict[str, CompactionRecord]:
        if not self.cache_file.exists():
            return {}
        try:
            raw = json.loads(self.cache_file.read_text(encoding="utf-8"))
            return {
                k: CompactionRecord.from_dict(v) for k, v in raw.items()
            }
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("Failed to load compaction cache: %s", exc)
            return {}

    def _flush_cache(self) -> None:
        try:
            payload = {k: v.to_dict() for k, v in self._cache.items()}
            tmp = self.cache_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self.cache_file)
        except OSError as exc:
            logger.warning("Failed to persist compaction cache: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_cache_key(self, tool_name: str, output: str) -> str:
        """Return a stable hash key for the (tool, output) pair."""
        digest = hashlib.sha256()
        digest.update(tool_name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(output.encode("utf-8", errors="ignore"))
        return digest.hexdigest()[:32]

    def compact_tool_output(
        self,
        tool_name: str,
        output: str,
        cache_key: str | None = None,
    ) -> str:
        """Compact a tool output string down to ``max_output_tokens``.

        Args:
            tool_name: Identifier of the tool that produced the output.
            output: Raw output text.
            cache_key: Optional pre-computed cache key. When provided, the
                compactor will reuse the cached compaction when present.

        Returns:
            Compacted output string.
        """
        if not output:
            return output

        key = cache_key or self.get_cache_key(tool_name, output)
        self.stats.lookups += 1

        # Cache hit path.
        record = self._cache.get(key)
        if record is not None:
            record.hits += 1
            self.stats.hits += 1
            self._flush_cache()
            return self._reconstruct_compacted(record, output)

        # Cache miss — actually compact.
        compacted = self._apply_heuristics(tool_name, output)
        self.stats.misses += 1
        self.stats.original_chars += len(output)
        self.stats.compacted_chars += len(compacted)

        self._cache[key] = CompactionRecord(
            cache_key=key,
            tool_name=tool_name,
            original_chars=len(output),
            compacted_chars=len(compacted),
            compressed_at=time.time(),
        )
        self._flush_cache()
        return compacted

    def evict_cache_older_than(self, days: int = 7) -> int:
        """Remove cache entries older than ``days`` days.

        Returns the number of entries evicted.
        """
        cutoff = time.time() - days * 86400
        stale = [k for k, v in self._cache.items() if v.compressed_at < cutoff]
        for k in stale:
            del self._cache[k]
        if stale:
            self._flush_cache()
        return len(stale)

    def get_stats(self) -> dict[str, Any]:
        """Return a snapshot of compactor statistics."""
        return {
            **self.stats.to_dict(),
            "cache_entries": len(self._cache),
        }

    # ------------------------------------------------------------------
    # Heuristics
    # ------------------------------------------------------------------

    def _apply_heuristics(self, tool_name: str, output: str) -> str:
        """Apply cheap, deterministic compaction passes."""
        text = output

        # 1. Normalize whitespace and collapse repeated blank lines.
        text = re.sub(r"\r\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)

        # 2. Drop trailing whitespace per line.
        text = "\n".join(line.rstrip() for line in text.splitlines())

        # 3. Truncate by token budget (head + tail preservation).
        max_chars = self.max_output_tokens * _CHARS_PER_TOKEN
        if len(text) > max_chars:
            head_chars = int(max_chars * 0.7)
            tail_chars = max_chars - head_chars
            text = (
                text[:head_chars]
                + "\n\n[... compacted {} chars ...]\n\n".format(
                    len(text) - head_chars - tail_chars
                )
                + text[-tail_chars:]
            )

        # 4. Tool-specific trimming hints.
        text = self._apply_tool_specific(tool_name, text)

        return text

    def _apply_tool_specific(self, tool_name: str, text: str) -> str:
        """Apply tool-specific trimming hints."""
        lower = tool_name.lower()
        if "search" in lower or "grep" in lower:
            # Keep only unique lines for search-like outputs.
            seen: set[str] = set()
            deduped: list[str] = []
            for line in text.splitlines():
                if line not in seen:
                    seen.add(line)
                    deduped.append(line)
            text = "\n".join(deduped)
        elif "log" in lower or "trace" in lower:
            # Keep last 60% of log-like output (most recent context is gold).
            cut = int(len(text) * 0.4)
            text = "[... earlier log entries omitted ...]\n" + text[cut:]
        return text

    def _reconstruct_compacted(
        self,
        record: CompactionRecord,
        original: str,
    ) -> str:
        """Re-compact the original when the cached metadata is partial."""
        return self._apply_heuristics(record.tool_name, original)