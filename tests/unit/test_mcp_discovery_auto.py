"""Unit tests for tools/mcp_discovery_auto.py.

Covers:
- MCPServerCandidate dataclass and to_dict()
- MCPAutoDiscovery.scan_npm_global (mocked subprocess)
- MCPAutoDiscovery.scan_pip_global (mocked subprocess)
- MCPAutoDiscovery.scan_local_projects (real temp files)
- MCPAutoDiscovery.scan_system (mocked shutil.which / PATH)
- MCPAutoDiscovery.auto_register (writes YAML config)
- MCPAutoDiscovery.scan_all deduplication
- Tool entry-point functions: mcp_scan_all / mcp_scan_npm / mcp_scan_pip / mcp_auto_register
"""

# ruff: noqa: E402
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from tools.mcp_discovery_auto import (  # noqa: E402
    MCPAutoDiscovery,
    MCPServerCandidate,
    mcp_auto_register,
    mcp_scan_all,
    mcp_scan_npm,
    mcp_scan_pip,
)


# ─────────────────────────────────────────────────────────────────────────────
# MCPServerCandidate dataclass
# ─────────────────────────────────────────────────────────────────────────────


class TestMCPServerCandidate:
    def test_defaults(self) -> None:
        c = MCPServerCandidate(name="n", source="local", command="cmd")
        assert c.args == []
        assert c.env == {}
        assert c.version is None
        assert c.description == ""
        assert c.auto_registered is False

    def test_to_dict(self) -> None:
        c = MCPServerCandidate(
            name="x",
            source="npm",
            command="npx",
            args=["-y", "x"],
            env={"K": "V"},
            version="1.0.0",
        )
        d = c.to_dict()
        assert d["command"] == "npx"
        assert d["args"] == ["-y", "x"]
        assert d["env"] == {"K": "V"}

    def test_to_dict_ignores_non_yaml_fields(self) -> None:
        c = MCPServerCandidate(
            name="x",
            source="local",
            command="c",
            version="1.2.3",
            description="hello",
            auto_registered=True,
        )
        d = c.to_dict()
        # Only command/args/env are exported for config persistence.
        for k in d:
            assert k in {"command", "args", "env"}


# ─────────────────────────────────────────────────────────────────────────────
# scan_npm_global
# ─────────────────────────────────────────────────────────────────────────────


class TestScanNpmGlobal:
    def test_returns_empty_when_npm_missing(self) -> None:
        with patch("tools.mcp_discovery_auto.shutil.which", return_value=None):
            assert MCPAutoDiscovery().scan_npm_global() == []

    def test_filters_matching_packages(self) -> None:
        payload = {
            "dependencies": {
                "@modelcontextprotocol/server-fs": {"version": "1.0.0"},
                "mcp-server-git": {"version": "0.5.0"},
                "lodash": {"version": "4.17.0"},  # not an MCP server
            },
        }
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(payload)
        with patch("tools.mcp_discovery_auto.shutil.which", return_value="/usr/bin/npm"):
            with patch(
                "tools.mcp_discovery_auto.subprocess.run",
                return_value=mock_proc,
            ):
                results = MCPAutoDiscovery().scan_npm_global()
        names = {c.name for c in results}
        assert "@modelcontextprotocol/server-fs" in names
        assert "mcp-server-git" in names
        assert "lodash" not in names

    def test_non_json_output_returns_empty(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "not json {"
        with patch("tools.mcp_discovery_auto.shutil.which", return_value="/usr/bin/npm"):
            with patch(
                "tools.mcp_discovery_auto.subprocess.run",
                return_value=mock_proc,
            ):
                assert MCPAutoDiscovery().scan_npm_global() == []

    def test_nonzero_returncode(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = "{}"
        with patch("tools.mcp_discovery_auto.shutil.which", return_value="/usr/bin/npm"):
            with patch(
                "tools.mcp_discovery_auto.subprocess.run",
                return_value=mock_proc,
            ):
                assert MCPAutoDiscovery().scan_npm_global() == []

    def test_npm_timeout(self) -> None:
        import subprocess as sp

        with patch("tools.mcp_discovery_auto.shutil.which", return_value="/usr/bin/npm"):
            with patch(
                "tools.mcp_discovery_auto.subprocess.run",
                side_effect=sp.TimeoutExpired(cmd="npm", timeout=15),
            ):
                assert MCPAutoDiscovery().scan_npm_global() == []

    def test_candidate_uses_npx_command(self) -> None:
        payload = {"dependencies": {"mcp-server-x": {"version": "0.1"}}}
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(payload)
        with patch("tools.mcp_discovery_auto.shutil.which", return_value="/usr/bin/npm"):
            with patch(
                "tools.mcp_discovery_auto.subprocess.run",
                return_value=mock_proc,
            ):
                results = MCPAutoDiscovery().scan_npm_global()
        assert len(results) == 1
        assert results[0].command == "npx"
        assert results[0].args == ["-y", "mcp-server-x"]
        assert results[0].source == "npm"


# ─────────────────────────────────────────────────────────────────────────────
# scan_pip_global
# ─────────────────────────────────────────────────────────────────────────────


class TestScanPipGlobal:
    def test_returns_empty_when_pip_missing(self) -> None:
        with patch("tools.mcp_discovery_auto.shutil.which", return_value=None):
            assert MCPAutoDiscovery().scan_pip_global() == []

    def test_filters_matching_packages(self) -> None:
        payload = [
            {"name": "mcp-foo-server", "version": "0.1"},
            {"name": "requests", "version": "2.31"},  # skip
            {"name": "bar-mcp-server", "version": "1.0"},
        ]
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(payload)
        with patch("tools.mcp_discovery_auto.shutil.which", return_value="/usr/bin/pip"):
            with patch(
                "tools.mcp_discovery_auto.subprocess.run",
                return_value=mock_proc,
            ):
                results = MCPAutoDiscovery().scan_pip_global()
        names = {c.name for c in results}
        assert "mcp-foo-server" in names
        assert "bar-mcp-server" in names
        assert "requests" not in names

    def test_non_json_output(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "not-json"
        with patch("tools.mcp_discovery_auto.shutil.which", return_value="/usr/bin/pip"):
            with patch(
                "tools.mcp_discovery_auto.subprocess.run",
                return_value=mock_proc,
            ):
                assert MCPAutoDiscovery().scan_pip_global() == []

    def test_pip_candidate_command(self) -> None:
        payload = [{"name": "mcp-x-server", "version": "0.1"}]
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(payload)

        def fake_which(name: str) -> str | None:
            if name == "pip":
                return "/usr/bin/pip"
            return None  # uvx missing

        with patch("tools.mcp_discovery_auto.shutil.which", side_effect=fake_which):
            with patch(
                "tools.mcp_discovery_auto.subprocess.run",
                return_value=mock_proc,
            ):
                results = MCPAutoDiscovery().scan_pip_global()
        assert len(results) == 1
        # Without uvx installed, the candidate uses python -m.
        assert results[0].command == "python"
        assert results[0].args == ["-m", "mcp-x-server"]

    def test_pip_candidate_command_with_uvx(self) -> None:
        payload = [{"name": "mcp-y-server", "version": "0.2"}]
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(payload)

        def fake_which(name: str) -> str | None:
            if name in {"pip", "uvx"}:
                return f"/usr/bin/{name}"
            return None

        with patch("tools.mcp_discovery_auto.shutil.which", side_effect=fake_which):
            with patch(
                "tools.mcp_discovery_auto.subprocess.run",
                return_value=mock_proc,
            ):
                results = MCPAutoDiscovery().scan_pip_global()
        assert len(results) == 1
        assert results[0].command == "uvx"
        assert results[0].args == ["mcp-y-server"]


# ─────────────────────────────────────────────────────────────────────────────
# scan_local_projects
# ─────────────────────────────────────────────────────────────────────────────


class TestScanLocalProjects:
    def test_scan_local_mcp_json(self, tmp_path: Path) -> None:
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps(
                {
                    "servers": {
                        "local-server": {
                            "command": "node",
                            "args": ["server.js"],
                            "env": {"API": "key"},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        discovery = MCPAutoDiscovery(scan_paths=[tmp_path])
        results = discovery.scan_local_projects()
        names = {c.name for c in results}
        assert "local-server" in names
        c = results[0]
        assert c.command == "node"
        assert c.args == ["server.js"]
        assert c.env == {"API": "key"}
        assert c.source == "local"

    def test_scan_local_mcpServers_alias(self, tmp_path: Path) -> None:
        mcp_json = tmp_path / "mcp_servers.json"
        mcp_json.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "alias-server": {
                            "command": "python",
                            "args": ["-m", "srv"],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        discovery = MCPAutoDiscovery(scan_paths=[tmp_path])
        results = discovery.scan_local_projects()
        assert any(c.name == "alias-server" for c in results)

    def test_scan_missing_path(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        discovery = MCPAutoDiscovery(scan_paths=[missing])
        assert discovery.scan_local_projects() == []

    def test_scan_corrupt_json(self, tmp_path: Path) -> None:
        (tmp_path / "mcp.json").write_text("not-json", encoding="utf-8")
        discovery = MCPAutoDiscovery(scan_paths=[tmp_path])
        assert discovery.scan_local_projects() == []

    def test_scan_recurses_into_subdirs(self, tmp_path: Path) -> None:
        sub = tmp_path / "deep" / "nested"
        sub.mkdir(parents=True)
        (sub / ".mcp.json").write_text(
            json.dumps({"servers": {"nested-srv": {"command": "x", "args": []}}}),
            encoding="utf-8",
        )
        discovery = MCPAutoDiscovery(scan_paths=[tmp_path])
        results = discovery.scan_local_projects()
        assert any(c.name == "nested-srv" for c in results)


# ─────────────────────────────────────────────────────────────────────────────
# scan_system
# ─────────────────────────────────────────────────────────────────────────────


class TestScanSystem:
    def test_finds_uvx(self, monkeypatch, tmp_path: Path) -> None:
        # Use a fake PATH that contains nothing.
        monkeypatch.setenv("PATH", str(tmp_path))
        with patch("tools.mcp_discovery_auto.shutil.which") as fake:
            fake.side_effect = lambda n: f"/usr/bin/{n}" if n == "uvx" else None
            results = MCPAutoDiscovery().scan_system()
        names = {c.name for c in results}
        assert "system-uvx" in names

    def test_finds_docker(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setenv("PATH", str(tmp_path))
        with patch("tools.mcp_discovery_auto.shutil.which") as fake:
            fake.side_effect = lambda n: f"/usr/bin/{n}" if n == "docker" else None
            results = MCPAutoDiscovery().scan_system()
        assert any(c.name == "system-docker" for c in results)

    def test_walks_path_for_mcp_server_binary(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        # Create a fake "mcp-foo-server" file (no executable bit needed on Windows).
        (bin_dir / "mcp-foo-server").write_text("#!/bin/sh\n")
        (bin_dir / "unrelated-tool").write_text("#!/bin/sh\n")
        with patch.dict("os.environ", {"PATH": str(bin_dir)}):
            results = MCPAutoDiscovery().scan_system()
        names = {c.name for c in results}
        assert "mcp-foo-server" in names
        assert "unrelated-tool" not in names

    def test_no_system_tools(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"PATH": str(tmp_path)}):
            with patch("tools.mcp_discovery_auto.shutil.which", return_value=None):
                results = MCPAutoDiscovery().scan_system()
        # No uvx / docker / podman / mcp-*-server present.
        assert results == []


# ─────────────────────────────────────────────────────────────────────────────
# auto_register
# ─────────────────────────────────────────────────────────────────────────────


class TestAutoRegister:
    def test_register_writes_yaml(self, tmp_path: Path) -> None:
        config = tmp_path / "config.yaml"
        candidates = [
            MCPServerCandidate(
                name="new-server",
                source="local",
                command="node",
                args=["s.js"],
            ),
        ]
        added = MCPAutoDiscovery().auto_register(candidates, config)
        assert added == 1
        assert config.exists()
        # Re-parse the YAML to verify contents.
        import yaml

        payload = yaml.safe_load(config.read_text(encoding="utf-8"))
        assert "mcp" in payload
        assert "new-server" in payload["mcp"]["servers"]
        assert payload["mcp"]["servers"]["new-server"]["command"] == "node"

    def test_skip_existing_entries(self, tmp_path: Path) -> None:
        import yaml

        config = tmp_path / "config.yaml"
        config.write_text(
            yaml.safe_dump(
                {"mcp": {"servers": {"existing": {"command": "old", "args": []}}}},
                default_flow_style=False,
            ),
            encoding="utf-8",
        )
        candidates = [
            MCPServerCandidate(name="existing", source="local", command="new"),
            MCPServerCandidate(name="fresh", source="local", command="cmd"),
        ]
        added = MCPAutoDiscovery().auto_register(candidates, config)
        assert added == 1
        payload = yaml.safe_load(config.read_text(encoding="utf-8"))
        # Existing entry must keep its old command.
        assert payload["mcp"]["servers"]["existing"]["command"] == "old"
        assert "fresh" in payload["mcp"]["servers"]

    def test_marks_candidate_registered(self, tmp_path: Path) -> None:
        config = tmp_path / "config.yaml"
        cand = MCPServerCandidate(name="z", source="local", command="x")
        assert cand.auto_registered is False
        MCPAutoDiscovery().auto_register([cand], config)
        assert cand.auto_registered is True


# ─────────────────────────────────────────────────────────────────────────────
# scan_all deduplication
# ─────────────────────────────────────────────────────────────────────────────


class TestScanAll:
    def test_dedupes_by_name_command_args(self, tmp_path: Path) -> None:
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps(
                {
                    "servers": {
                        "shared": {"command": "node", "args": ["a.js"]},
                    }
                }
            ),
            encoding="utf-8",
        )
        # Stub npm/pip/system to return the same candidate shape.
        npm_payload = {"dependencies": {"mcp-server-shared": {"version": "0.1"}}}
        npm_proc = MagicMock(returncode=0, stdout=json.dumps(npm_payload))
        pip_payload = [{"name": "mcp-shared-server", "version": "0.1"}]
        pip_proc = MagicMock(returncode=0, stdout=json.dumps(pip_payload))

        with patch("tools.mcp_discovery_auto.shutil.which", return_value="/usr/bin/_"):
            with patch(
                "tools.mcp_discovery_auto.subprocess.run",
                side_effect=[npm_proc, pip_proc],
            ):
                discovery = MCPAutoDiscovery(scan_paths=[tmp_path])
                results = discovery.scan_all()

        # Duplicates collapsed: at most one "shared" with (node, [a.js]).
        shared_matches = [
            c for c in results
            if c.name == "shared" and c.command == "node" and c.args == ["a.js"]
        ]
        assert len(shared_matches) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Tool entry-points
# ─────────────────────────────────────────────────────────────────────────────


class TestToolEntryPoints:
    def test_mcp_scan_all_returns_summary(self) -> None:
        with patch.object(MCPAutoDiscovery, "scan_all", return_value=[]):
            result = mcp_scan_all()
        assert result["total"] == 0
        assert result["by_source"] == {}
        assert result["candidates"] == []

    def test_mcp_scan_npm_calls_scanner(self) -> None:
        with patch.object(MCPAutoDiscovery, "scan_npm_global", return_value=[]):
            result = mcp_scan_npm()
        assert "candidates" in result

    def test_mcp_scan_pip_calls_scanner(self) -> None:
        with patch.object(MCPAutoDiscovery, "scan_pip_global", return_value=[]):
            result = mcp_scan_pip()
        assert "candidates" in result

    def test_mcp_auto_register_invokes_discovery(self, tmp_path: Path) -> None:
        target = tmp_path / "out.yaml"
        with patch.object(MCPAutoDiscovery, "scan_all", return_value=[]):
            result = mcp_auto_register(config_path=str(target))
        assert result["scanned"] == 0
        assert result["added"] == 0
        assert str(target) in result["config_path"]
