"""Research Skills — literature review, paper summarization, and citation analysis."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["summarize_paper", "extract_citations", "literature_review"]


def summarize_paper(
    text: str,
    max_length: int = 300,
    style: str = "abstract",
    **kwargs: Any,
) -> dict[str, Any]:
    """Summarize an academic paper or research document.

    Args:
        text: Raw text content of the paper.
        max_length: Maximum character length of the summary.
        style: 'abstract', 'bullet_points', or 'tl;dr'.

    Returns:
        A dict with 'summary' and 'key_terms'.
    """
    if not text or len(text.strip()) < 50:
        return {"summary": "Text too short to summarize.", "key_terms": []}

    sentences = re.split(r"(?<=[.!?])\s+", text.strip())

    if len(sentences) < 3:
        return {"summary": text[:max_length], "key_terms": []}

    if style == "tl;dr":
        summary = sentences[0][:max_length]
    elif style == "bullet_points":
        key_sentences = sentences[:5]
        bullets = [f"- {s.strip()}" for s in key_sentences if s.strip()]
        summary = "\n".join(bullets[:6])
    else:
        combined = " ".join(sentences[:8])
        summary = combined[:max_length].rsplit(" ", 1)[0] + "..."

    word_freq: dict[str, int] = {}
    stop_words = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "this", "that", "these", "those",
        "it", "its", "they", "their", "them", "we", "our", "us", "i", "my",
    }
    for word in re.findall(r"[a-zA-Z]{4,}", text.lower()):
        if word not in stop_words:
            word_freq[word] = word_freq.get(word, 0) + 1

    top_terms = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:10]
    key_terms = [term for term, _ in top_terms]

    return {"summary": summary, "key_terms": key_terms}


def extract_citations(
    text: str,
    format: str = "list",
    **kwargs: Any,
) -> dict[str, Any]:
    """Extract citation references from academic text.

    Args:
        text: Text that may contain citations.
        format: 'list' (plain list) or 'bibtex' (structured).

    Returns:
        A dict with 'citations' (list) and 'count'.
    """
    if not text:
        return {"citations": [], "count": 0}

    patterns = [
        r"\[(\d+)\]",
        r"\(([A-Z][a-z]+(?:\s+(?:et\s+al\.|and))?(?:\s+\d{4})?(?:,\s*p\.\s*\d+)?)\)",
        r"([A-Z][a-z]+\s+et\s+al\.?\s*\(\d{4}\))",
    ]

    all_cites: list[str] = []
    seen: set[str] = set()

    for pattern in patterns:
        for match in re.finditer(pattern, text):
            cite = match.group(0).strip()
            if cite not in seen:
                seen.add(cite)
                all_cites.append(cite)

    if format == "bibtex":
        bibtex_entries = []
        for i, cite in enumerate(all_cites, 1):
            clean = re.sub(r"[^\w\s,]", "", cite)
            bibtex_entries.append(
                f"@misc{{ref{i},\n  author = {{{clean}}},\n  year = {{n.d.}},\n}}"
            )
        return {"citations": bibtex_entries, "count": len(all_cites)}

    return {"citations": all_cites, "count": len(all_cites)}


def literature_review(
    paper_dir: str | Path | None = None,
    keywords: list[str] | None = None,
    max_papers: int = 20,
    **kwargs: Any,
) -> dict[str, Any]:
    """Scan a directory of papers and organize them by theme.

    Args:
        paper_dir: Directory containing paper text files.
        keywords: List of research keywords to filter/score papers.
        max_papers: Maximum number of papers to analyze.

    Returns:
        A dict with 'papers' (scored/filtered list) and 'summary'.
    """
    if keywords is None:
        keywords = []
    if paper_dir is None:
        return {
            "papers": [],
            "themes": {},
            "summary": "No paper_dir provided",
        }

    p = Path(paper_dir)
    if not p.is_dir():
        return {
            "papers": [],
            "themes": {},
            "summary": f"Directory not found: {paper_dir}",
        }

    paper_files = sorted(p.glob("*.txt"))[:max_papers]
    papers: list[dict[str, Any]] = []

    for pf in paper_files:
        try:
            content = pf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        word_lower = content.lower()
        keyword_scores = {
            kw: word_lower.count(kw.lower()) for kw in keywords
        }
        total_score = sum(keyword_scores.values())

        sentences = re.split(r"(?<=[.!?])\s+", content.strip())
        abstract_candidate = " ".join(sentences[:3])[:200]

        papers.append({
            "filename": pf.name,
            "score": total_score,
            "keyword_matches": keyword_scores,
            "abstract": abstract_candidate,
            "word_count": len(content.split()),
        })

    papers.sort(key=lambda x: x["score"], reverse=True)

    themes: dict[str, int] = {}
    for kw in keywords:
        count = sum(1 for paper in papers if paper["keyword_matches"].get(kw, 0) > 0)
        if count > 0:
            themes[kw] = count

    summary = f"{len(papers)} paper(s), top keyword: {themes}"

    return {
        "papers": papers,
        "themes": themes,
        "summary": summary,
    }
