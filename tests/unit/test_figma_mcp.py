"""Tests for optional_mcps.figma MCP server."""

from optional_mcps.figma import (
    TOOLS,
    _format_comment,
    _format_file,
)


class TestFigmaFormatting:
    def test_format_file_with_name_and_lastModified(self):
        file = {
            "name": "My Design",
            "lastModified": "2025-01-15T10:30:00Z",
            "thumbnailUrl": "https://figma.com/thumb.png",
            "document": {
                "children": [
                    {
                        "children": [
                            {},
                        ],
                    },
                ],
            },
        }
        result = _format_file(file)
        assert "My Design" in result
        assert "2025-01-15T10:30:00Z" in result

    def test_format_file_minimal_data(self):
        file: dict = {}
        result = _format_file(file)
        assert "?" in result


class TestFigmaCommentFormatting:
    def test_format_comment_with_message_and_author(self):
        comment = {
            "message": "This looks great!",
            "user": {"handle": "designer", "email": "designer@figma.com"},
            "created_at": "2025-01-15T12:00:00Z",
            "resolved": False,
        }
        result = _format_comment(comment)
        assert "This looks great!" in result
        assert "designer" in result
        assert "Open" in result


class TestFigmaToolsList:
    def test_tools_defined(self):
        assert len(TOOLS) == 5
        names = [t.name for t in TOOLS]
        assert "figma_get_file" in names
        assert "figma_get_comments" in names
        assert "figma_list_components" in names
        assert "figma_get_styles" in names
        assert "figma_get_images" in names

    def test_all_tools_have_handlers(self):
        for tool in TOOLS:
            assert callable(tool.handler), f"{tool.name} has no handler"
