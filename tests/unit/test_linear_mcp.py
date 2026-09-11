"""Tests for optional_mcps.linear MCP server."""

from optional_mcps.linear import TOOLS, _format_issue


class TestLinearFormatting:
    def test_format_issue_basic(self):
        issue = {
            "title": "Fix login bug",
            "identifier": "PRJ-42",
            "state": {"name": "In Progress"},
            "assignee": {"name": "Alice"},
            "priority": 2,
            "url": "https://linear.app/x/issue/PRJ-42",
            "estimate": 3,
        }
        result = _format_issue(issue)
        assert "PRJ-42" in result
        assert "Fix login bug" in result
        assert "In Progress" in result
        assert "Alice" in result
        assert "2" in result
        assert "3" in result

    def test_format_issue_no_assignee(self):
        issue = {
            "title": "T",
            "identifier": "X-1",
            "state": {"name": "Backlog"},
            "assignee": None,
            "priority": 0,
            "url": "https://x",
        }
        result = _format_issue(issue)
        assert "unassigned" in result
        assert "Backlog" in result

    def test_format_issue_no_estimate(self):
        issue = {
            "title": "T",
            "identifier": "X-1",
            "state": {"name": "Done"},
            "assignee": {},
            "priority": 4,
            "url": "https://x",
            "estimate": None,
        }
        result = _format_issue(issue)
        assert "unassigned" in result
        assert "Estimate:" not in result


class TestLinearToolsList:
    def test_tools_defined(self):
        assert len(TOOLS) == 5
        names = [t.name for t in TOOLS]
        assert "linear_list_issues" in names
        assert "linear_create_issue" in names
        assert "linear_update_issue" in names
        assert "linear_get_issue" in names
        assert "linear_list_teams" in names

    def test_all_have_handlers(self):
        for tool in TOOLS:
            assert callable(tool.handler), f"{tool.name} has no handler"
