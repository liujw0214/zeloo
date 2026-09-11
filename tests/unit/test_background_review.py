"""Tests for background review validation and parsing logic."""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from agent.background_review import (
    REVIEW_SYSTEM_PROMPT,
    _parse_review_json,
    _validate_skill,
)


def test_parse_review_json_plain():
    content = '{"skills": [], "memories": []}'
    result = _parse_review_json(content)
    assert result["skills"] == []
    assert result["memories"] == []


def test_parse_review_json_with_fences():
    content = "```json\n{\"skills\": [{\"name\": \"x\"}], \"memories\": []}\n```"
    result = _parse_review_json(content)
    assert len(result["skills"]) == 1
    assert result["skills"][0]["name"] == "x"


def test_parse_review_json_invalid_returns_empty():
    content = "not json at all"
    result = _parse_review_json(content)
    assert result["skills"] == []
    assert result["memories"] == []


def test_validate_skill_valid():
    candidate = {
        "name": "fix-django-migration",
        "content": (
            "---\nname: fix-django-migration\n"
            "description: Fix Django migrations\n"
            "---\n## Steps\n1. Run makemigrations"
        ),
    }
    assert _validate_skill(candidate) is True


def test_validate_skill_invalid_name():
    candidate = {
        "name": "Invalid Name!",
        "content": "---\nname: x\n---\nbody",
    }
    assert _validate_skill(candidate) is False


def test_validate_skill_empty_content():
    candidate = {"name": "my-skill", "content": ""}
    assert _validate_skill(candidate) is False


def test_validate_skill_no_frontmatter():
    candidate = {"name": "my-skill", "content": "Just a body without frontmatter"}
    assert _validate_skill(candidate) is False


def test_validate_skill_with_secret():
    candidate = {
        "name": "my-skill",
        "content": "---\nname: x\n---\nkey: sk-abcdefghijklmnopqrstuvwxyz0123456789",
    }
    assert _validate_skill(candidate) is False


def test_review_system_prompt_mentions_json_shape():
    assert '"skills"' in REVIEW_SYSTEM_PROMPT
    assert '"memories"' in REVIEW_SYSTEM_PROMPT


if __name__ == "__main__":
    test_parse_review_json_plain()
    test_parse_review_json_with_fences()
    test_parse_review_json_invalid_returns_empty()
    test_validate_skill_valid()
    test_validate_skill_invalid_name()
    test_validate_skill_empty_content()
    test_validate_skill_no_frontmatter()
    test_validate_skill_with_secret()
    test_review_system_prompt_mentions_json_shape()
    print("All background_review tests passed!")
