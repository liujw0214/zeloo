"""Unit tests for GitHub integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from tools.integrations.github_integration import GitHubIntegration


def _resp(payload=None, code: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = code
    r.text = "" if code < 400 else "err"
    r.content = b"{}"
    r.headers = {}
    r.json.return_value = payload if payload is not None else {}
    return r


def _wire(mock_cls, resp: MagicMock) -> AsyncMock:
    client = AsyncMock()
    for m in ("request", "get", "post", "put", "delete"):
        setattr(client, m, AsyncMock(return_value=resp))
    client.aclose = AsyncMock(return_value=None)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    mock_cls.return_value = client
    return client


@pytest.fixture
def gh(tmp_path: Path) -> GitHubIntegration:
    return GitHubIntegration(config={
        "token": "ghp_test", "owner": "octocat", "repo": "hello",
    })


class TestGitHubInit:
    def test_init_config(self) -> None:
        g = GitHubIntegration(config={"token": "t", "owner": "o", "repo": "r"})
        assert g.token == "t" and g.default_owner == "o" and g.default_repo == "r"
        assert "Bearer t" in g.headers["Authorization"]

    def test_init_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "env-tk")
        g = GitHubIntegration(config={"owner": "o", "repo": "r"})
        assert g.token == "env-tk" and g.headers["Authorization"] == "Bearer env-tk"

    def test_no_token_no_auth(self) -> None:
        g = GitHubIntegration(config={"owner": "o", "repo": "r"})
        assert g.token == "" and "Authorization" not in g.headers

    def test_encode_decode_roundtrip(self) -> None:
        g = GitHubIntegration(config={"token": "t"})
        enc = g._encode_content("hi\n世界")
        assert g._decode_content(enc) == "hi\n世界"

    def test_resolve_owner_repo(self) -> None:
        g = GitHubIntegration(config={"token": "t", "owner": "def", "repo": "dr"})
        assert g._resolve_owner_repo("o", "r") == ("o", "r")
        assert g._resolve_owner_repo() == ("def", "dr")


class TestGitHubFiles:
    @patch("httpx.AsyncClient")
    async def test_get_file_decodes(self, mc, gh) -> None:
        enc = gh._encode_content("# Hello")
        _wire(mc, _resp({"path": "README.md", "sha": "abc",
                         "encoding": "base64", "size": 8, "content": enc}))
        out = await gh.get_file("README.md")
        assert out["ok"] and out["content"] == "# Hello" and out["sha"] == "abc"

    @patch("httpx.AsyncClient")
    async def test_create_file(self, mc, gh) -> None:
        client = _wire(mc, _resp({"commit": {"sha": "c1"}, "content": {"sha": "f"}}))
        out = await gh.create_file("a.txt", "data", message="add")
        assert out["ok"]
        body = client.request.call_args.kwargs["json"]
        assert body["message"] == "add" and body["content"] == gh._encode_content("data")
        assert client.request.call_args.args[0] == "PUT"


class TestGitHubIssues:
    @patch("httpx.AsyncClient")
    async def test_list_issues(self, mc, gh) -> None:
        client = _wire(mc, _resp([{"number": 1}, {"number": 2}]))
        issues = await gh.list_issues(state="open")
        assert len(issues) == 2
        assert client.request.call_args.kwargs["params"] == {"state": "open"}

    @patch("httpx.AsyncClient")
    async def test_create_issue(self, mc, gh) -> None:
        client = _wire(mc, _resp({"number": 42, "html_url": "https://gh/x"}))
        out = await gh.create_issue(title="Bug", body="x", labels=["bug"])
        assert out["ok"] and out["number"] == 42
        body = client.request.call_args.kwargs["json"]
        assert body["title"] == "Bug" and body["labels"] == ["bug"]

    @patch("httpx.AsyncClient")
    async def test_add_comment(self, mc, gh) -> None:
        client = _wire(mc, _resp({"id": 7, "html_url": "u"}))
        out = await gh.add_comment("hi", issue_number=3)
        assert out["ok"]
        assert client.request.call_args.args[1].endswith("/issues/3/comments")


class TestGitHubPullsAndActions:
    @patch("httpx.AsyncClient")
    async def test_create_pull(self, mc, gh) -> None:
        client = _wire(mc, _resp({"number": 7, "html_url": "u"}))
        out = await gh.create_pull(title="T", body="b", head="feat", base="main")
        assert out["ok"] and out["number"] == 7
        body = client.request.call_args.kwargs["json"]
        assert body["head"] == "feat" and body["base"] == "main"

    @patch("httpx.AsyncClient")
    async def test_trigger_workflow(self, mc, gh) -> None:
        client = _wire(mc, _resp({}, code=204))
        out = await gh.trigger_workflow("ci.yml", inputs={"env": "prod"}, ref="main")
        assert out["ok"]
        body = client.request.call_args.kwargs["json"]
        assert body["ref"] == "main" and body["inputs"] == {"env": "prod"}
        assert "/actions/workflows/ci.yml/dispatches" in client.request.call_args.args[1]

    @patch("httpx.AsyncClient")
    async def test_list_workflows(self, mc, gh) -> None:
        _wire(mc, _resp({"workflows": [{"id": 1, "name": "CI"}]}))
        wfs = await gh.list_workflows()
        assert len(wfs) == 1 and wfs[0]["name"] == "CI"


class TestGitHubErrors:
    @patch("httpx.AsyncClient")
    async def test_auth_error(self, mc, gh) -> None:
        _wire(mc, _resp(code=401))
        out = await gh.list_issues()
        assert isinstance(out, dict) and out["ok"] is False

    @patch("httpx.AsyncClient")
    async def test_not_found(self, mc, gh) -> None:
        _wire(mc, _resp(code=404))
        out = await gh.get_file("missing.txt")
        assert out["ok"] is False and out["code"] == "not_found"
