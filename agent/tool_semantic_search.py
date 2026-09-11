"""Tool semantic search — embedding retrieval over registered tools."""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

SearchBackend = Literal["tfidf", "fastembed", "sentence_transformers"]
DEFAULT_INDEX_PATH = Path.home() / ".Zeloo" / "cache" / "tool_semantic_search" / "index.json"

_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "have", "in", "is", "it", "its", "of", "on", "or", "that", "the",
    "to", "was", "were", "will", "with", "this", "i", "you", "we", "they",
}
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


@dataclass
class ToolEntry:
    """Indexed tool record."""

    name: str
    category: str
    description: str
    parameters: dict[str, Any]
    text_blob: str = ""
    tfidf_vector: dict[str, float] = field(default_factory=dict)
    embedding: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "category": self.category, "description": self.description,
            "parameters": self.parameters, "text_blob": self.text_blob,
            "tfidf_vector": self.tfidf_vector, "embedding": self.embedding,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolEntry:
        return cls(
            name=data["name"], category=data["category"], description=data["description"],
            parameters=data.get("parameters", {}), text_blob=data.get("text_blob", ""),
            tfidf_vector=data.get("tfidf_vector", {}), embedding=data.get("embedding"),
        )


class ToolSemanticSearch:
    """Semantic search over tools with a swappable embedding backend."""

    def __init__(
        self,
        backend: SearchBackend = "tfidf",
        index_path: Path | None = None,
    ) -> None:
        self.backend_requested: SearchBackend = backend
        self.backend_active: SearchBackend = backend
        self.index_path = Path(index_path) if index_path else DEFAULT_INDEX_PATH
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._tools: dict[str, ToolEntry] = {}
        self._doc_freqs: Counter[str] = Counter()
        self._doc_count: int = 0
        self._embedder = None
        self._init_backend()
        self._load_index()

    def _init_backend(self) -> None:
        if self.backend_requested == "tfidf":
            return
        try:
            if self.backend_requested == "fastembed":
                from fastembed import TextEmbedding  # type: ignore[import-not-found]
                self._embedder = TextEmbedding()
                return
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
            self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as exc:
            logger.warning("%s unavailable (%s); using TF-IDF", self.backend_requested, exc)
            self.backend_active = "tfidf"

    def _load_index(self) -> None:
        if not self.index_path.exists():
            return
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
            self._tools = {n: ToolEntry.from_dict(e) for n, e in raw.get("tools", {}).items()}
            self._doc_freqs = Counter(raw.get("doc_freqs", {}))
            self._doc_count = int(raw.get("doc_count", len(self._tools)))
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Failed to load tool index: %s", exc)

    def _persist_index(self) -> None:
        payload = {
            "tools": {n: t.to_dict() for n, t in self._tools.items()},
            "doc_freqs": dict(self._doc_freqs),
            "doc_count": self._doc_count,
        }
        try:
            tmp = self.index_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self.index_path)
        except OSError as exc:
            logger.warning("Failed to persist tool index: %s", exc)

    def index_tool(
        self,
        name: str,
        category: str,
        description: str,
        parameters: dict[str, Any],
    ) -> None:
        """Add or update a tool entry in the search index."""
        blob = self._build_text_blob(name, category, description, parameters)
        tokens = self._tokenise(blob)
        existing = self._tools.get(name)
        if existing is not None:
            for tok in set(self._tokenise(existing.text_blob)):
                self._doc_freqs[tok] = max(0, self._doc_freqs[tok] - 1)
                if self._doc_freqs[tok] == 0:
                    del self._doc_freqs[tok]
            self._doc_count = max(0, self._doc_count - 1)
        for tok in set(tokens):
            self._doc_freqs[tok] += 1
        self._doc_count += 1
        entry = ToolEntry(
            name=name, category=category, description=description, parameters=parameters,
            text_blob=blob, tfidf_vector=self._compute_tfidf(tokens), embedding=self._embed(blob),
        )
        self._tools[name] = entry
        self._persist_index()

    def remove_tool(self, name: str) -> bool:
        """Remove a tool from the index. Returns True if removed."""
        entry = self._tools.pop(name, None)
        if entry is None:
            return False
        for tok in set(self._tokenise(entry.text_blob)):
            self._doc_freqs[tok] = max(0, self._doc_freqs[tok] - 1)
            if self._doc_freqs[tok] == 0:
                del self._doc_freqs[tok]
        self._doc_count = max(0, self._doc_count - 1)
        self._persist_index()
        return True

    def search(
        self,
        query: str,
        category: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search for tools most relevant to ``query``."""
        if not self._tools:
            return []
        candidates = list(self._tools.values())
        if category:
            candidates = [t for t in candidates if t.category == category]
        if not candidates:
            return []
        scored = self._score_tfidf(query, candidates) if self.backend_active == "tfidf" \
            else self._score_embedding(query, candidates)
        scored.sort(key=lambda x: x[1], reverse=True)
        return [{
            "name": entry.name, "category": entry.category, "description": entry.description,
            "score": round(score, 6), "parameters": entry.parameters,
        } for entry, score in scored[:top_k]]

    def get_recommendation(
        self,
        query: str,
        available_tools: list[str],
    ) -> list[str]:
        """Recommend tools from the user's available subset."""
        if not available_tools:
            return []
        results = self.search(query, top_k=max(1, len(available_tools)))
        allowed = set(available_tools)
        return [r["name"] for r in results if r["name"] in allowed][: len(available_tools)]

    def get_index_size(self) -> int:
        """Number of tools currently indexed."""
        return len(self._tools)

    # Scoring helpers
    def _score_tfidf(self, query: str, candidates: list[ToolEntry]) -> list[tuple[ToolEntry, float]]:
        q_tokens = self._tokenise(query)
        if not q_tokens:
            return [(c, 0.0) for c in candidates]
        q_vec = self._compute_tfidf(q_tokens)
        return [(c, self._cosine(q_vec, c.tfidf_vector)) for c in candidates]

    def _score_embedding(self, query: str, candidates: list[ToolEntry]) -> list[tuple[ToolEntry, float]]:
        q_vec = self._embed(query)
        return [(c, self._cosine_vec(q_vec, c.embedding) if c.embedding else 0.0) for c in candidates]

    # Low-level helpers
    @staticmethod
    def _build_text_blob(name: str, category: str, description: str, parameters: dict[str, Any]) -> str:
        param_blob = " ".join([
            *(str(k) for k in parameters.keys() if isinstance(k, str)),
            *(str(v) for v in parameters.values() if isinstance(v, (str, int, float, bool))),
        ])
        return " ".join([name, category, description, param_blob])

    @staticmethod
    def _tokenise(text: str) -> list[str]:
        return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOP_WORDS]

    def _compute_tfidf(self, tokens: list[str]) -> dict[str, float]:
        if not tokens or self._doc_count == 0:
            return {}
        counts = Counter(tokens)
        total = sum(counts.values())
        vec: dict[str, float] = {}
        for term, freq in counts.items():
            tf = freq / total
            df = self._doc_freqs.get(term, 0)
            idf = math.log((1 + self._doc_count) / (1 + df)) + 1.0
            vec[term] = tf * idf
        return vec

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        common = set(a).intersection(b)
        if not common:
            return 0.0
        dot = sum(a[k] * b[k] for k in common)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    @staticmethod
    def _cosine_vec(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    def _embed(self, text: str) -> list[float]:
        if self._embedder is None or self.backend_active == "tfidf":
            return []
        try:
            if self.backend_active == "fastembed":
                embeddings = list(self._embedder.embed([text]))
                return [float(x) for x in embeddings[0].tolist()]
            vec = self._embedder.encode(text, show_progress_bar=False)
            return [float(x) for x in vec.tolist()]
        except Exception as exc:
            logger.warning("Embedding failed for %r: %s", text[:40], exc)
            return []