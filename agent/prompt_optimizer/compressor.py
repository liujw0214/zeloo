"""Prompt compressor — reduce token usage while preserving meaning."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CompressionResult:
    """Result of prompt compression."""

    original_text: str
    compressed_text: str
    original_tokens: int
    compressed_tokens: int
    compression_ratio: float
    techniques_applied: list[str] = field(default_factory=list)
    quality_preserved: bool = True


class PromptCompressor:
    """Compress prompts to reduce token usage.

    Techniques:
    - Whitespace normalization
    - Filler word removal
    - Example deduplication
    - Repetitive phrase collapse
    - Verbose phrasing simplification
    """

    FILLER_WORDS: list[str] = [
        "actually", "basically", "essentially", "literally",
        "obviously", "clearly", "simply", "just",
        "really", "very", "quite", "rather", "somewhat",
    ]

    VERBOSE_REPLACEMENTS: dict[str, str] = {
        r"\bin order to\b": "to",
        r"\bdue to the fact that\b": "because",
        r"\bat this point in time\b": "now",
        r"\bin the event that\b": "if",
        r"\bfor the purpose of\b": "for",
        r"\bwith regard to\b": "about",
        r"\bin regards to\b": "about",
        r"\bin spite of the fact that\b": "although",
        r"\bdue to\b": "from",
        r"\ba large number of\b": "many",
        r"\bthe majority of\b": "most",
        r"\ba sufficient amount of\b": "enough",
        r"\bin close proximity to\b": "near",
        r"\bprior to\b": "before",
        r"\bsubsequent to\b": "after",
        r"\bin light of the fact that\b": "since",
        r"\bnot later than\b": "by",
        r"\bin connection with\b": "about",
        r"\bwith respect to\b": "for",
        r"\bin order that\b": "so",
        r"\bin the absence of\b": "without",
        r"\bin the case of\b": "for",
        r"\bat the present time\b": "now",
        r"\bas a matter of fact\b": "",
        r"\bneedless to say\b": "",
        r"\bit is important to note that\b": "",
        r"\bit should be noted that\b": "",
        r"\bplease note that\b": "",
        r"\bfor the sake of clarity\b": "",
    }

    def __init__(
        self,
        remove_fillers: bool = True,
        simplify_verbose: bool = True,
        normalize_whitespace: bool = True,
        target_ratio: float = 0.7,
    ) -> None:
        self.remove_fillers = remove_fillers
        self.simplify_verbose = simplify_verbose
        self.normalize_whitespace = normalize_whitespace
        self.target_ratio = target_ratio

    def compress(self, text: str) -> CompressionResult:
        """Compress text using all enabled techniques."""
        techniques: list[str] = []
        original_text = text
        result = text

        if self.normalize_whitespace:
            result = self._normalize_whitespace(result)
            if result != text:
                techniques.append("whitespace_normalization")

        if self.remove_fillers:
            prev = result
            result = self._remove_filler_words(result)
            if result != prev:
                techniques.append("filler_removal")

        if self.simplify_verbose:
            prev = result
            result = self._simplify_verbose_phrases(result)
            if result != prev:
                techniques.append("verbose_simplification")

        prev = result
        result = self._deduplicate_repetition(result)
        if result != prev:
            techniques.append("repetition_dedup")

        prev = result
        result = self._trim_redundant_phrases(result)
        if result != prev:
            techniques.append("phrase_trimming")

        original_tokens = self._estimate_tokens(original_text)
        compressed_tokens = self._estimate_tokens(result)
        compression_ratio = (
            compressed_tokens / original_tokens
            if original_tokens > 0
            else 1.0
        )

        return CompressionResult(
            original_text=original_text,
            compressed_text=result,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_ratio=compression_ratio,
            techniques_applied=techniques,
            quality_preserved=compression_ratio >= self.target_ratio * 0.9,
        )

    def _normalize_whitespace(self, text: str) -> str:
        result = re.sub(r"[ \t]+", " ", text)
        result = re.sub(r"\n{3,}", "\n\n", result)
        result = re.sub(r"\n ", "\n", result)
        return result.strip()

    def _remove_filler_words(self, text: str) -> str:
        result = text
        for word in self.FILLER_WORDS:
            pattern = r"\b" + word + r"\b\s*"
            result = re.sub(pattern, "", result, flags=re.IGNORECASE)
        result = re.sub(r"\s+", " ", result)
        return result.strip()

    def _simplify_verbose_phrases(self, text: str) -> str:
        result = text
        for verbose, concise in self.VERBOSE_REPLACEMENTS.items():
            result = re.sub(verbose, concise, result, flags=re.IGNORECASE)
        result = re.sub(r"  +", " ", result)
        result = re.sub(r"\n +", "\n", result)
        return result.strip()

    def _deduplicate_repetition(self, text: str) -> str:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        seen: set[str] = set()
        unique_sentences: list[str] = []
        for sentence in sentences:
            normalized = sentence.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique_sentences.append(sentence.strip())
        return " ".join(unique_sentences)

    def _trim_redundant_phrases(self, text: str) -> str:
        text = re.sub(r"\.{2,}", ".", text)
        text = re.sub(r"!{2,}", "!", text)
        text = re.sub(r"\?{2,}", "?", text)
        text = re.sub(r",\s*,", ",", text)
        return text

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4


__all__ = [
    "CompressionResult",
    "PromptCompressor",
]