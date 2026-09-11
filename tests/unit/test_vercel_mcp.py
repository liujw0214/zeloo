"""Tests for optional_mcps.vercel MCP server."""

from optional_mcps.vercel import TOOLS, _format_deployment


class TestVercelFormatting:
    def test_format_deployment_ready(self):
        dep = {
            "name": "my-app",
            "url": "my-app.vercel.app",
            "state": "READY",
            "createdAt": "2025-01-01T00:00:00Z",
            "ready": True,
        }
        result = _format_deployment(dep)
        assert "my-app" in result
        assert "READY" not in result
        assert "ready" in result
        assert "my-app.vercel.app" in result

    def test_format_deployment_error(self):
        dep = {
            "name": "broken",
            "url": "broken.vercel.app",
            "state": "ERROR",
            "ready": False,
        }
        result = _format_deployment(dep)
        assert "broken" in result
        assert "ERROR" in result

    def test_format_deployment_building(self):
        dep = {
            "name": "deploying",
            "url": "deploying.vercel.app",
            "state": "BUILDING",
            "ready": False,
        }
        result = _format_deployment(dep)
        assert "deploying" in result
        assert "BUILDING" in result


class TestVercelToolsList:
    def test_tools_defined(self):
        assert len(TOOLS) == 5
        names = [t.name for t in TOOLS]
        assert "vercel_list_deployments" in names
        assert "vercel_get_deployment" in names
        assert "vercel_list_projects" in names
        assert "vercel_get_project" in names
        assert "vercel_get_domain_records" in names

    def test_all_have_handlers(self):
        for tool in TOOLS:
            assert callable(tool.handler), f"{tool.name} has no handler"
