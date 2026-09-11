"""Tests for Jira MCP server."""

from optional_mcps.jira import (
    TOOLS,
    _format_issue,
    _format_project,
)


class TestJiraFormatting:
    def test_format_issue(self):
        issue = {
            "key": "PROJ-123",
            "fields": {
                "summary": "Fix login bug",
                "status": {"name": "In Progress"},
                "assignee": {"displayName": "Alice"},
                "reporter": {"displayName": "Bob"},
            },
        }
        result = _format_issue(issue)
        assert "PROJ-123" in result
        assert "Fix login bug" in result
        assert "In Progress" in result
        assert "Alice" in result
        assert "Bob" in result

    def test_format_issue_minimal(self):
        issue = {"key": "X-1", "fields": {}}
        result = _format_issue(issue)
        assert "X-1" in result
        assert "No summary" in result
        assert "Unassigned" in result

    def test_format_issue_missing_assignee(self):
        issue = {
            "key": "X-2",
            "fields": {"summary": "Test", "reporter": {"displayName": "Test User"}},
        }
        result = _format_issue(issue)
        assert "Unassigned" in result
        assert "Test User" in result

    def test_format_project(self):
        project = {
            "key": "PROJ",
            "name": "My Project",
            "lead": {"displayName": "Charlie"},
            "projectTypeKey": "software",
        }
        result = _format_project(project)
        assert "PROJ" in result
        assert "My Project" in result
        assert "Charlie" in result
        assert "software" in result

    def test_format_project_minimal(self):
        project = {"key": "X"}
        result = _format_project(project)
        assert "X" in result
        assert "No lead" in result

    def test_format_project_missing_lead(self):
        project = {"key": "Y", "name": "Y Project", "projectTypeKey": "business"}
        result = _format_project(project)
        assert "Y" in result
        assert "Y Project" in result


class TestJiraToolsList:
    def test_tools_defined(self):
        assert len(TOOLS) == 5
        names = [t.name for t in TOOLS]
        assert "jira_search_issues" in names
        assert "jira_get_issue" in names
        assert "jira_create_issue" in names
        assert "jira_update_issue" in names
        assert "jira_list_projects" in names

    def test_all_tools_have_handlers(self):
        for tool in TOOLS:
            assert callable(tool.handler), f"{tool.name} has no handler"

    def test_all_tools_have_descriptions(self):
        for tool in TOOLS:
            assert tool.description, f"{tool.name} has no description"

    def test_all_tools_have_input_schema(self):
        for tool in TOOLS:
            assert tool.input_schema, f"{tool.name} has no input_schema"
