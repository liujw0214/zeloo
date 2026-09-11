"""Tests for optional_mcps.datadog MCP server."""

from optional_mcps.datadog import TOOLS, _format_host, _format_monitor


class TestDatadogFormatting:
    def test_format_monitor_with_name_state_tags(self):
        monitor = {
            "name": "High CPU Alert",
            "type": "metric alert",
            "overall_state": "Alert",
            "message": "CPU usage is high",
            "tags": ["env:prod", "service:api"],
        }
        result = _format_monitor(monitor)
        assert "High CPU Alert" in result
        assert "Alert" in result
        assert "metric alert" in result
        assert "env:prod" in result
        assert "service:api" in result
        assert "CPU usage is high" in result

    def test_format_monitor_minimal(self):
        monitor = {
            "name": "Minimal Monitor",
        }
        result = _format_monitor(monitor)
        assert "Minimal Monitor" in result
        assert "?" in result

    def test_format_host_with_hostname_status(self):
        host = {
            "hostname": "web-server-01",
            "status": "up",
            "last_report_time": "2025-01-01T12:00:00Z",
            "tags_by_source": ["env:prod", "region:us-east"],
        }
        result = _format_host(host)
        assert "web-server-01" in result
        assert "up" in result
        assert "2025-01-01T12:00:00Z" in result
        assert "env:prod" in result


class TestDatadogToolsList:
    def test_tools_defined(self):
        assert len(TOOLS) == 5
        names = [t.name for t in TOOLS]
        assert "datadog_search_metrics" in names
        assert "datadog_query_metrics" in names
        assert "datadog_list_monitors" in names
        assert "datadog_get_monitor" in names
        assert "datadog_list_hosts" in names

    def test_all_have_handlers(self):
        for tool in TOOLS:
            assert callable(tool.handler), f"{tool.name} has no handler"
