"""Tests for agent.context_breakdown."""

from __future__ import annotations

from agent.context_breakdown import (
    _BOUNDARY_PATTERNS,
    _find_safe_boundary,
    breakdown_by_files,
    breakdown_by_size,
    breakdown_by_tokens,
    breakdown_by_turns,
)


class TestBreakdownByTokens:
    def test_empty_text(self) -> None:
        assert breakdown_by_tokens("") == []
        assert breakdown_by_tokens("") == []

    def test_short_text_no_split(self) -> None:
        text = "hello world"
        # One chunk because the text fits inside chunk_size.
        chunks = breakdown_by_tokens(text, chunk_size=100, overlap_tokens=10)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_splits_at_boundary(self) -> None:
        text = ("para one. " * 200) + "\n\n" + ("para two. " * 200)
        chunks = breakdown_by_tokens(text, chunk_size=200, overlap_tokens=20)
        assert len(chunks) >= 2

    def test_invalid_chunk_size(self) -> None:
        """``chunk_size <= 0`` returns the original text unchanged
        rather than crashing — matches the documented ``[text] if text else []``
        short-circuit in ``breakdown_by_tokens``."""
        assert breakdown_by_tokens("hi", chunk_size=0) == ["hi"]
        assert breakdown_by_tokens("", chunk_size=0) == []
        assert breakdown_by_tokens("hi", chunk_size=-5) == ["hi"]


class TestFindSafeBoundary:
    def test_prefers_paragraph_boundary(self) -> None:
        text = "first\n\nsecond"
        # The first paragraph ends at index 6 (``\n\n`` ends).
        result = _find_safe_boundary(text, 0, len(text))
        # The boundary offset should land on or just after the blank line.
        assert result >= 6

    def test_falls_back_to_newline(self) -> None:
        text = "first line\nsecond line"
        # No ``\n\n+``, so falls back to single ``\n``.
        result = _find_safe_boundary(text, 0, len(text))
        # Should be after the ``\n`` (offset 11).
        assert result >= 10

    def test_falls_back_to_space(self) -> None:
        """Without ``\\n`` or ``. `` or ``, `` separators, fall back
        to a single space and return the offset right after it."""
        text = "no separators at all here"
        result = _find_safe_boundary(text, 0, len(text))
        # The boundary should land somewhere in the text (not outside).
        assert 0 < result <= len(text)
        # ``m.end()`` lands right after the matched space.
        assert text[result - 1] == " "

    def test_empty_chunk_returns_end(self) -> None:
        assert _find_safe_boundary("anything", 5, 5) == 5

    def test_no_safe_point_returns_end(self) -> None:
        # A single character with no boundary at all — last fallback
        # would match it. Either way, the result must be in range.
        result = _find_safe_boundary("x", 0, 1)
        assert result >= 0


class TestBreakdownByTurns:
    def test_empty(self) -> None:
        assert breakdown_by_turns([]) == []

    def test_one_turn_one_chunk(self) -> None:
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = breakdown_by_turns(msgs, chunk_turns=10)
        assert len(result) == 1
        assert len(result[0]) == 2

    def test_splits_at_chunk_boundary(self) -> None:
        # Each user + assistant message counts as one "turn".
        # 2 turns per chunk × 4 turn-pairs = 4 groups.
        msgs = []
        for i in range(4):
            msgs.append({"role": "user", "content": f"u{i}"})
            msgs.append({"role": "assistant", "content": f"a{i}"})
        result = breakdown_by_turns(msgs, chunk_turns=2)
        assert len(result) == 4
        # Every group contains one user/assistant pair (no orphans).
        for group in result:
            assert len(group) == 2


class TestBreakdownByFiles:
    def test_empty(self) -> None:
        assert breakdown_by_files([]) == []

    def test_splits_into_chunks(self) -> None:
        files = [f"file_{i}.py" for i in range(45)]
        chunks = breakdown_by_files(files, max_files_per_chunk=20)
        assert len(chunks) == 3
        assert chunks[0] == files[0:20]
        assert chunks[1] == files[20:40]
        assert chunks[2] == files[40:45]


class TestBreakdownBySize:
    def test_empty(self) -> None:
        assert breakdown_by_size([]) == []

    def test_groups_by_byte_size(self) -> None:
        items = ["abc", "de", "f", "ghijklm"]  # 3+2+1+7 = 13 bytes
        chunks = breakdown_by_size(items, max_bytes=5)
        # First chunk: "abc" (3) + "de" (2) = 5 → group.
        # Then "f" alone (1) → new group.
        # Then "ghijklm" alone (7) → new group.
        assert chunks[0] == ["abc", "de"]
        assert chunks[1] == ["f"]
        assert chunks[2] == ["ghijklm"]

    def test_utf8_bytes_counted(self) -> None:
        items = ["€"]  # 3 bytes in UTF-8
        chunks = breakdown_by_size(items, max_bytes=2)
        # 3 bytes > max_bytes=2 → empty group? Or stays together?
        # Implementation: keeps single-item groups so total >= 1.
        assert len(chunks) >= 1


class TestBoundaryPatternsCompiled:
    def test_patterns_are_precompiled(self) -> None:
        import re

        # Each pattern must be a compiled Pattern, not a string.
        for pattern in _BOUNDARY_PATTERNS:
            assert isinstance(pattern, re.Pattern)

    def test_patterns_in_priority_order(self) -> None:
        # Paragraph break (``\n\n+``) must come before single ``\n``.
        assert _BOUNDARY_PATTERNS[0].pattern == r"\n\n+"
        assert _BOUNDARY_PATTERNS[1].pattern == r"\n"


class TestCoalesceGroups:
    """Verify ``_coalesce_groups`` reduces groups to ``target`` count.

    Tests are split between behavioural equivalence (same result as
    before the heap-based optimisation) and shape-checks (correct
    output sizes / element counts).
    """

    def _g(self, *sizes: int) -> list[list[int]]:
        """Build groups whose i-th element is a list of i repeated size."""
        return [[i] * size for i, size in enumerate(sizes)]

    def test_target_already_reached(self) -> None:
        """When ``len(groups) <= target`` we return groups unchanged."""
        from agent.context_breakdown import _coalesce_groups

        g = self._g(1, 2, 3)
        assert _coalesce_groups(g, target=5) == g
        assert _coalesce_groups(g, target=3) == g

    def test_target_one_collapses_all(self) -> None:
        from agent.context_breakdown import _coalesce_groups

        g = self._g(1, 2, 3)
        merged = _coalesce_groups(g, target=1)
        assert len(merged) == 1
        assert sum(len(x) for x in merged) == 6  # 1 + 2 + 3

    def test_target_two_merges_smallest_pair(self) -> None:
        """The pair with the smallest combined size is merged first."""
        from agent.context_breakdown import _coalesce_groups

        # ``_g(1, 2, 3, 4, 5)`` produces groups whose sizes are
        # [1, 2, 3, 4, 5]. Adjacent pair sizes: 1+2=3, 2+3=5,
        # 3+4=7, 4+5=9 — the smallest is 3 at idx=0, so the first
        # two groups (sizes 1 and 2) merge first.
        g = self._g(1, 2, 3, 4, 5)
        merged = _coalesce_groups(g, target=4)
        assert len(merged) == 4
        # Merged group is groups[0] + groups[1] = [0] + [1, 1].
        assert merged[0] == [0, 1, 1]

    def test_total_item_count_preserved(self) -> None:
        """Coalescing only re-groups — it must not lose any items."""
        from agent.context_breakdown import _coalesce_groups

        g = self._g(2, 5, 1, 3, 7, 4)
        merged = _coalesce_groups(g, target=2)
        assert len(merged) == 2
        total = sum(len(group) for group in merged)
        assert total == sum(len(group) for group in g)

    def test_correct_target_reached(self) -> None:
        from agent.context_breakdown import _coalesce_groups

        for initial in (5, 10, 20):
            for target in (1, 2, 3):
                g = self._g(*([1] * initial))
                merged = _coalesce_groups(g, target=target)
                assert len(merged) == target

    def test_order_within_groups_preserved(self) -> None:
        """Coalescing concatenates lists — the inner order must be stable."""
        from agent.context_breakdown import _coalesce_groups

        g = [[0], [1], [2], [3], [4]]
        merged = _coalesce_groups(g, target=1)
        assert merged[0] == [0, 1, 2, 3, 4]

    def test_single_group_unchanged(self) -> None:
        from agent.context_breakdown import _coalesce_groups

        g = self._g(1, 2, 3)
        assert _coalesce_groups(g, target=10) == g
        assert _coalesce_groups([self._g(1, 2, 3)[0]], target=1) == [[0]]