"""Tests for Railway MCP server."""

from optional_mcps.railway import (
    TOOLS,
    _format_deployment,
    _format_project,
)


class TestRailwayFormatting:
    def test_format_project(self):
        project = {
            "id": "proj-123",
            "name": "My App",
            "description": "A great application",
            "createdAt": "2026-09-01T10:00:00Z",
        }
        result = _format_project(project)
        assert "proj-123" in result
        assert "My App" in result
        assert "A great application" in result
        assert "2026-09-01" in result

    def test_format_project_minimal(self):
        project = {"id": "x"}
        result = _format_project(project)
        assert "x" in result
        assert "unknown" in result
        assert "No description" in result

    def test_format_deployment(self):
        deployment = {
            "id": "dep-456",
            "status": "SUCCESS",
            "serviceName": "web",
            "environment": "production",
            "createdAt": "2026-09-07T10:30:00Z",
        }
        result = _format_deployment(deployment)
        assert "dep-456" in result
        assert "SUCCESS" in result
        assert "web" in result
        assert "production" in result

    def test_format_deployment_minimal(self):
        deployment = {}
        result = _format_deployment(deployment)
        assert "?" in result


class TestRailwayToolsList:
    def test_tools_defined(self):
        assert len(TOOLS) == 5
        names = [t.name for t in TOOLS]
        assert "railway_list_projects" in names
        assert "railway_get_project" in names
        assert "railway_list_deployments" in names
        assert "railway_get_deployment" in names
        assert "railway_trigger_deployment" in names

    def test_all_tools_have_handlers(self):
        for tool in TOOLS:
            assert callable(tool.handler), f"{tool.name} has no handler"

    def test_all_tools_have_descriptions(self):
        for tool in TOOLS:
            assert tool.description, f"{tool.name} has no description"

    def test_all_tools_have_input_schema(self):
        for tool in TOOLS:
            assert tool.input_schema, f"{tool.name} has no input_schema"
