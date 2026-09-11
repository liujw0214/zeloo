"""Tests for optional_mcps.sentry MCP server."""

from optional_mcps.sentry import TOOLS, _fmt_event, _fmt_issue, _fmt_project


class TestSentryFormatting:
    def test_fmt_issue(self):
        issue = {
            "id": "abc123",
            "title": "TypeError in login",
            "culprit": "src/auth.py in handle_login",
            "count": 42,
            "userCount": 5,
            "status": "unresolved",
            "level": "error",
            "lastSeen": "2025-01-01T12:00:00Z",
            "permalink": "https://sentry.io/issue/abc123/",
        }
        result = _fmt_issue(issue)
        assert "abc123" in result
        assert "TypeError" in result
        assert "auth.py" in result
        assert "42" in result
        assert "5" in result

    def test_fmt_event(self):
        event = {
            "eventID": "evt-1",
            "title": "Click failed",
            "message": "Cannot read property of undefined",
            "level": "warning",
            "dateCreated": "2025-01-01T00:00:00Z",
        }
        result = _fmt_event(event)
        assert "evt-1" in result
        assert "Click failed" in result
        assert "warning" in result

    def test_fmt_event_truncates_message(self):
        event = {"eventID": "1", "title": "t", "message": "x" * 500}
        result = _fmt_event(event)
        assert len(result) < 400

    def test_fmt_project(self):
        project = {"name": "web", "slug": "web-prod", "platform": "javascript"}
        result = _fmt_project(project)
        assert "web" in result
        assert "javascript" in result


class TestSentryToolsList:
    def test_tools_defined(self):
        assert len(TOOLS) == 5
        names = [t.name for t in TOOLS]
        assert "sentry_list_issues" in names
        assert "sentry_get_issue" in names
        assert "sentry_list_events" in names
        assert "sentry_list_projects" in names
        assert "sentry_resolve_issue" in names

    def test_all_have_handlers(self):
        for tool in TOOLS:
            assert callable(tool.handler), f"{tool.name} has no handler"