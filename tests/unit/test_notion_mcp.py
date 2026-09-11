"""Tests for optional_mcps.notion MCP server."""

from optional_mcps.notion import (
    TOOLS,
    _extract_text,
    _format_page,
)


class TestNotionFormatting:
    def test_extract_text_empty(self):
        assert _extract_text([]) == ""

    def test_extract_text_paragraph(self):
        blocks = [
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Hello"}]}},
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "World"}]}},
        ]
        result = _extract_text(blocks)
        assert "Hello" in result
        assert "World" in result

    def test_extract_text_ignores_empty(self):
        blocks = [
            {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Title"}]}},
            {"type": "paragraph", "paragraph": {"rich_text": []}},
        ]
        result = _extract_text(blocks)
        assert "Title" in result

    def test_format_page_with_title(self):
        page = {
            "id": "abc123",
            "url": "https://notion.so/test",
            "last_edited_time": "2025-01-01",
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"plain_text": "My Page"}],
                },
            },
        }
        result = _format_page(page)
        assert "My Page" in result
        assert "abc123" in result
        assert "notion.so" in result

    def test_format_page_no_properties(self):
        page = {
            "id": "xyz",
            "properties": {},
        }
        result = _format_page(page)
        assert "xyz" in result


class TestNotionToolsList:
    def test_tools_defined(self):
        assert len(TOOLS) == 5
        names = [t.name for t in TOOLS]
        assert "notion_search" in names
        assert "notion_get_page" in names
        assert "notion_create_page" in names
        assert "notion_append_block" in names
        assert "notion_query_database" in names

    def test_all_tools_have_handlers(self):
        for tool in TOOLS:
            assert callable(tool.handler), f"{tool.name} has no handler"
