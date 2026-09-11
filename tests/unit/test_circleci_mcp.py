"""Tests for CircleCI MCP server."""

from optional_mcps.circleci import (
    TOOLS,
    _format_pipeline,
    _format_project,
)


class TestCircleCIFormatting:
    def test_format_project(self):
        project = {
            "vcs_url": "https://github.com/acme/myapp",
            "username": "acme",
            "reponame": "myapp",
            "default_branch": "main",
            "last_built": "2026-09-07T10:30:00Z",
        }
        result = _format_project(project)
        assert "github.com/acme/myapp" in result
        assert "acme/myapp" in result
        assert "main" in result
        assert "2026-09-07" in result

    def test_format_project_minimal(self):
        project = {"vcs_url": "gh", "username": "x", "reponame": "y"}
        result = _format_project(project)
        assert "gh" in result
        assert "x/y" in result
        assert "unknown" in result

    def test_format_pipeline(self):
        pipeline = {
            "id": "abc-123",
            "number": 42,
            "state": "created",
            "created_at": "2026-09-07T10:00:00Z",
        }
        result = _format_pipeline(pipeline)
        assert "abc-123" in result
        assert "42" in result
        assert "created" in result
        assert "2026-09-07" in result

    def test_format_pipeline_minimal(self):
        pipeline = {}
        result = _format_pipeline(pipeline)
        assert "unknown" in result


class TestCircleCIToolsList:
    def test_tools_defined(self):
        assert len(TOOLS) == 5
        names = [t.name for t in TOOLS]
        assert "circleci_list_projects" in names
        assert "circleci_list_pipelines" in names
        assert "circleci_trigger_pipeline" in names
        assert "circleci_list_workflows" in names
        assert "circleci_get_pipeline" in names

    def test_all_tools_have_handlers(self):
        for tool in TOOLS:
            assert callable(tool.handler), f"{tool.name} has no handler"

    def test_all_tools_have_descriptions(self):
        for tool in TOOLS:
            assert tool.description, f"{tool.name} has no description"

    def test_all_tools_have_input_schema(self):
        for tool in TOOLS:
            assert tool.input_schema, f"{tool.name} has no input_schema"
