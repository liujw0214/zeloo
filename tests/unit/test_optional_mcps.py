"""Tests for optional_mcps base framework and GitHub MCP server."""


from optional_mcps.base import MCPServer, MCPTool, make_tool
from optional_mcps.github import (
    TOOLS,
    _format_issue,
    _format_pr,
    _format_repo,
)


class TestMCPTool:
    def test_make_tool_decorator(self):
        @make_tool(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {}},
        )
        def handler() -> str:
            return "result"

        assert isinstance(handler, MCPTool)
        assert handler.name == "test_tool"
        assert handler.description == "A test tool"
        assert handler.handler() == "result"


class TestMCPServer:
    def test_init(self):
        server = MCPServer(name="test", version="1.0.0", tools=[])
        assert server.name == "test"
        assert server.version == "1.0.0"
        assert server.tools == []

    def test_build_tools_response_empty(self):
        server = MCPServer(name="test", version="1.0.0", tools=[])
        resp = server._build_tools_response()
        assert resp == []

    def test_build_tools_response_single(self):
        tool = MCPTool(
            name="hello",
            description="Says hello",
            input_schema={"type": "object"},
            handler=lambda: "",
        )
        server = MCPServer(name="test", version="1.0.0", tools=[tool])
        resp = server._build_tools_response()
        assert len(resp) == 1
        assert resp[0]["name"] == "hello"
        assert resp[0]["description"] == "Says hello"
        assert resp[0]["inputSchema"] == {"type": "object"}

    def test_handle_initialize(self):
        server = MCPServer(name="my-server", version="2.0.0", tools=[])
        req = {"method": "initialize", "id": 1, "params": {}}
        resp = server._handle_request(req)
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert resp["result"]["serverInfo"]["name"] == "my-server"
        assert resp["result"]["serverInfo"]["version"] == "2.0.0"
        assert "tools" in resp["result"]["capabilities"]

    def test_handle_tools_list(self):
        tool = MCPTool(name="foo", description="desc", input_schema={}, handler=lambda: "")
        server = MCPServer(name="test", version="1.0.0", tools=[tool])
        req = {"method": "tools/list", "id": 2, "params": {}}
        resp = server._handle_request(req)
        assert resp["id"] == 2
        assert len(resp["result"]["tools"]) == 1
        assert resp["result"]["tools"][0]["name"] == "foo"

    def test_handle_tools_call_error(self):
        def fail() -> str:
            raise RuntimeError("something went wrong")

        tool = MCPTool(name="fail", description="", input_schema={}, handler=fail)
        server = MCPServer(name="test", version="1.0.0", tools=[tool])
        req = {
            "method": "tools/call",
            "id": 4,
            "params": {"name": "fail", "arguments": {}},
        }
        resp = server._handle_request(req)
        assert resp["id"] == 4
        assert resp["result"]["content"][0]["text"] == "Error: something went wrong"
        assert resp["result"]["content"][0]["type"] == "text"

    def test_handle_tools_call_not_found(self):
        server = MCPServer(name="test", version="1.0.0", tools=[])
        req = {
            "method": "tools/call",
            "id": 5,
            "params": {"name": "missing", "arguments": {}},
        }
        resp = server._handle_request(req)
        assert resp["error"]["code"] == -32601
        assert "missing" in resp["error"]["message"]

    def test_handle_notification_returns_none(self):
        server = MCPServer(name="test", version="1.0.0", tools=[])
        req = {"method": "notifications/initialized", "id": None, "params": {}}
        resp = server._handle_request(req)
        assert resp is None

    def test_handle_unknown_method(self):
        server = MCPServer(name="test", version="1.0.0", tools=[])
        req = {"method": "foo/bar", "id": 6, "params": {}}
        resp = server._handle_request(req)
        assert resp["error"]["code"] == -32601


class TestGitHubFormatting:
    def test_format_repo(self):
        repo = {
            "full_name": "octocat/Hello-World",
            "description": "A place for Hello World",
            "stargazers_count": 1000,
            "forks_count": 200,
            "language": "Python",
            "html_url": "https://github.com/octocat/Hello-World",
        }
        result = _format_repo(repo)
        assert "octocat/Hello-World" in result
        assert "A place for Hello World" in result
        assert "1000" in result
        assert "200" in result
        assert "Python" in result
        assert "https://github.com/octocat/Hello-World" in result

    def test_format_repo_missing_fields(self):
        repo = {"full_name": "x/y"}
        result = _format_repo(repo)
        assert "x/y" in result
        assert "(no description)" in result

    def test_format_issue(self):
        issue = {
            "number": 42,
            "title": "Bug in login",
            "state": "open",
            "user": {"login": "alice"},
            "html_url": "https://github.com/x/y/issues/42",
            "body": "Cannot log in",
            "labels": [{"name": "bug"}, {"name": "priority"}],
        }
        result = _format_issue(issue)
        assert "#42" in result
        assert "Bug in login" in result
        assert "open" in result
        assert "alice" in result
        assert "bug, priority" in result

    def test_format_issue_no_labels(self):
        issue = {"number": 1, "title": "Title", "state": "closed", "user": {"login": "bob"}}
        result = _format_issue(issue)
        assert "#1" in result
        assert "closed" in result

    def test_format_pr(self):
        pr = {
            "number": 7,
            "title": "Add feature X",
            "state": "open",
            "user": {"login": "carol"},
            "html_url": "https://github.com/x/y/pull/7",
            "body": "This PR adds feature X",
        }
        result = _format_pr(pr)
        assert "#7" in result
        assert "Add feature X" in result
        assert "open" in result
        assert "carol" in result

    def test_format_pr_truncates_long_body(self):
        pr = {
            "number": 1,
            "title": "T",
            "state": "open",
            "user": {"login": "u"},
            "body": "x" * 500,
            "html_url": "https://x",
        }
        result = _format_pr(pr)
        assert len(result) < 500


class TestGitHubToolsList:
    def test_tools_defined(self):
        assert len(TOOLS) == 6
        names = [t.name for t in TOOLS]
        assert "github_search_repos" in names
        assert "github_get_repo" in names
        assert "github_list_issues" in names
        assert "github_get_issue" in names
        assert "github_list_prs" in names
        assert "github_create_issue" in names

    def test_all_tools_have_handlers(self):
        for tool in TOOLS:
            assert callable(tool.handler), f"{tool.name} has no handler"
