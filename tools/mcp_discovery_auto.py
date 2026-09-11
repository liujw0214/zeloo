"""Automatic MCP server discovery.

Walks the filesystem looking for MCP servers that aren't yet registered
in ``~/.Zeloo/config.yaml``. The discovery covers four sources:

* **npm** — global packages matching ``@modelcontextprotocol/*`` or
  ``mcp-server-*``.
* **pip** — user/global packages matching ``mcp-*-server`` or
  ``*-mcp-server``.
* **local** — ``mcp.json`` / ``mcp_servers.json`` files under the
  current working directory or any explicitly-supplied scan paths.
* **system** — heuristic detection of well-known system binaries
  (``uvx``, ``docker``, ``npx``) and the ``PATH`` lookup for any
  ``mcp-*-server`` binary.

Each match produces an :class:`MCPServerCandidate` that callers can
inspect and selectively ``auto_register`` into the Zeloo config.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: File names searched in each scan path.
_LOCAL_CONFIG_NAMES: tuple[str, ...] = (
    "mcp.json",
    "mcp_servers.json",
    ".mcp.json",
)

#: Package name patterns that we treat as MCP servers.
_NPM_PATTERNS: tuple[str, ...] = (
    "@modelcontextprotocol/",
    "mcp-server-",
)

#: pip package name patterns that we treat as MCP servers.
_PIP_PATTERNS: tuple[str, ...] = (
    "mcp-",
    "-mcp-server",
)

#: Subprocess timeout (seconds) for ``npm`` / ``pip`` probes.
_PROBE_TIMEOUT_S = 15.0


@dataclass
class MCPServerCandidate:
    """A discovered MCP server that may or may not be registered yet."""

    name: str
    source: str          # "npm" | "pip" | "local" | "system" | "config"
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    version: str | None = None
    description: str = ""
    auto_registered: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view suitable for config.yaml."""
        return {
            "command": self.command,
            "args": list(self.args),
            "env": dict(self.env),
        }


class MCPAutoDiscovery:
    """Discover MCP server candidates from multiple sources."""

    def __init__(self, scan_paths: list[Path] | None = None) -> None:
        self._scan_paths: list[Path] = list(scan_paths) if scan_paths else [Path.cwd()]

    # ----- public API ---------------------------------------------------

    def scan_all(self) -> list[MCPServerCandidate]:
        """Aggregate every discovery source and return the union."""
        candidates: list[MCPServerCandidate] = []
        candidates.extend(self.scan_npm_global())
        candidates.extend(self.scan_pip_global())
        candidates.extend(self.scan_local_projects())
        candidates.extend(self.scan_system())
        # Deduplicate by (name, command, args tuple).
        seen: set[tuple[str, str, tuple[str, ...]]] = set()
        unique: list[MCPServerCandidate] = []
        for cand in candidates:
            key = (cand.name, cand.command, tuple(cand.args))
            if key in seen:
                continue
            seen.add(key)
            unique.append(cand)
        return unique

    def scan_npm_global(self) -> list[MCPServerCandidate]:
        """Scan globally-installed npm packages for MCP servers."""
        if not shutil.which("npm"):
            logger.debug("npm not on PATH; skipping global scan")
            return []
        try:
            proc = subprocess.run(
                ["npm", "list", "-g", "--depth=0", "--json"],
                capture_output=True,
                text=True,
                timeout=_PROBE_TIMEOUT_S,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.debug("npm list failed: %s", exc)
            return []

        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            logger.debug("npm list returned non-JSON output")
            return []

        deps = (payload.get("dependencies") or {})
        candidates: list[MCPServerCandidate] = []
        for name, meta in deps.items():
            if not isinstance(name, str):
                continue
            if not any(name.startswith(p) or p in name for p in _NPM_PATTERNS):
                continue
            version = meta.get("version") if isinstance(meta, dict) else None
            candidates.append(MCPServerCandidate(
                name=name,
                source="npm",
                command="npx",
                args=["-y", name],
                version=version,
                description=f"Global npm MCP server: {name}",
            ))
        return candidates

    def scan_pip_global(self) -> list[MCPServerCandidate]:
        """Scan globally-installed pip packages for MCP servers."""
        if not shutil.which("pip"):
            logger.debug("pip not on PATH; skipping global scan")
            return []
        try:
            proc = subprocess.run(
                ["pip", "list", "--format=json"],
                capture_output=True,
                text=True,
                timeout=_PROBE_TIMEOUT_S,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.debug("pip list failed: %s", exc)
            return []

        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        try:
            packages = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return []

        candidates: list[MCPServerCandidate] = []
        if not isinstance(packages, list):
            return candidates
        for entry in packages:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name", "")
            if not isinstance(name, str) or not name:
                continue
            if not any(name.startswith(p) or p in name for p in _PIP_PATTERNS):
                continue
            version = entry.get("version")
            candidates.append(MCPServerCandidate(
                name=name,
                source="pip",
                command="uvx" if shutil.which("uvx") else "python",
                args=["-m", name] if shutil.which("uvx") is None else [name],
                version=version,
                description=f"pip MCP server: {name}",
            ))
        return candidates

    def scan_local_projects(self) -> list[MCPServerCandidate]:
        """Scan the configured paths for local ``mcp.json`` files."""
        candidates: list[MCPServerCandidate] = []
        for root in self._scan_paths:
            if not root.exists():
                continue
            candidates.extend(self._scan_single_path(root))
        return candidates

    def scan_system(self) -> list[MCPServerCandidate]:
        """Detect system-level MCP server tools.

        The check is intentionally conservative: it only emits a
        candidate when the executable actually exists on ``PATH``.
        """
        candidates: list[MCPServerCandidate] = []
        # Common host binaries that can launch MCP servers.
        for binary in ("uvx", "docker", "podman"):
            path = shutil.which(binary)
            if path is None:
                continue
            candidates.append(MCPServerCandidate(
                name=f"system-{binary}",
                source="system",
                command=path,
                args=[],
                description=f"System binary capable of running MCP servers: {binary}",
            ))
        # Walk PATH for ``mcp-*-server`` executables.
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            if not directory:
                continue
            try:
                entries = list(Path(directory).iterdir())
            except (FileNotFoundError, PermissionError, OSError):
                continue
            for entry in entries:
                if not entry.is_file():
                    continue
                name = entry.name
                if not (name.startswith("mcp-") and name.endswith("-server")):
                    continue
                candidates.append(MCPServerCandidate(
                    name=name,
                    source="system",
                    command=str(entry),
                    args=[],
                    description=f"PATH-resident MCP server: {name}",
                ))
        return candidates

    def auto_register(
        self,
        candidates: list[MCPServerCandidate],
        config_path: Path,
    ) -> int:
        """Write the supplied candidates into *config_path* under ``mcp.servers``.

        Existing entries are preserved. The function returns the number
        of *new* entries that were added (existing ones are skipped).
        """
        existing: dict[str, Any] = {}
        if config_path.exists():
            try:
                import yaml  # local import: optional dependency
                with open(config_path, encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not load existing config: %s", exc)
                existing = {}

        mcp_section = existing.setdefault("mcp", {})
        servers_section = mcp_section.setdefault("servers", {})
        if not isinstance(servers_section, dict):
            servers_section = {}
            mcp_section["servers"] = servers_section

        added = 0
        for cand in candidates:
            if cand.name in servers_section:
                continue
            servers_section[cand.name] = cand.to_dict()
            cand.auto_registered = True
            added += 1

        if added > 0:
            try:
                import yaml
                config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(
                        existing,
                        f,
                        default_flow_style=False,
                        sort_keys=False,
                        allow_unicode=True,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to write config %s: %s", config_path, exc)
                return 0
        return added

    def get_npm_global_path(self) -> Path:
        """Return the path to the global ``node_modules`` directory.

        Falls back to ``~/.npm-global/lib/node_modules`` when the
        ``npm root -g`` query fails.
        """
        if shutil.which("npm"):
            try:
                proc = subprocess.run(
                    ["npm", "root", "-g"],
                    capture_output=True,
                    text=True,
                    timeout=_PROBE_TIMEOUT_S,
                    check=False,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    return Path(proc.stdout.strip())
            except (subprocess.TimeoutExpired, OSError):
                pass
        return Path.home() / ".npm-global" / "lib" / "node_modules"

    def get_pip_user_path(self) -> Path:
        """Return the user-level ``site-packages`` directory."""
        # Honour the platform-appropriate env vars first.
        for var in ("PYTHONUSERBASE", "PIP_TARGET"):
            value = os.environ.get(var)
            if value:
                return Path(value)
        # Common platform defaults.
        if os.name == "nt":
            return Path.home() / "AppData" / "Roaming" / "Python"
        return Path.home() / ".local" / "lib" / "python" / "site-packages"

    # ----- internal helpers --------------------------------------------

    def _scan_single_path(self, root: Path) -> list[MCPServerCandidate]:
        """Recursively look for ``mcp.json``-style files under *root*."""
        candidates: list[MCPServerCandidate] = []
        try:
            config_files: list[Path] = []
            for name in _LOCAL_CONFIG_NAMES:
                config_files.extend(root.rglob(name))
        except OSError as exc:
            logger.debug("rglob failed under %s: %s", root, exc)
            return candidates

        for config_file in config_files:
            try:
                with open(config_file, encoding="utf-8") as f:
                    payload = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                logger.debug("Skipping %s: %s", config_file, exc)
                continue
            if not isinstance(payload, dict):
                continue
            servers = payload.get("servers") or payload.get("mcpServers") or {}
            if not isinstance(servers, dict):
                continue
            for name, conf in servers.items():
                if not isinstance(name, str) or not isinstance(conf, dict):
                    continue
                command = conf.get("command")
                if not isinstance(command, str):
                    continue
                raw_args = conf.get("args") or []
                if not isinstance(raw_args, list):
                    raw_args = []
                env_map = conf.get("env") or {}
                if not isinstance(env_map, dict):
                    env_map = {}
                candidates.append(MCPServerCandidate(
                    name=name,
                    source="local",
                    command=command,
                    args=[str(a) for a in raw_args],
                    env={str(k): str(v) for k, v in env_map.items()},
                    description=f"Local MCP server from {config_file}",
                ))
        return candidates


# ---------------------------------------------------------------------------
# @tool-wrapped convenience functions for the agent runtime.
# ---------------------------------------------------------------------------

def _make_summary(candidates: list[MCPServerCandidate]) -> dict[str, Any]:
    """Helper to produce a JSON-friendly summary of a discovery run."""
    by_source: dict[str, int] = {}
    for cand in candidates:
        by_source[cand.source] = by_source.get(cand.source, 0) + 1
    return {
        "total": len(candidates),
        "by_source": by_source,
        "candidates": [
            {
                "name": c.name,
                "source": c.source,
                "command": c.command,
                "args": list(c.args),
                "version": c.version,
                "description": c.description,
            }
            for c in candidates
        ],
    }


def mcp_scan_all() -> dict[str, Any]:
    """Tool entry point: run every scanner and return a summary."""
    discovery = MCPAutoDiscovery()
    return _make_summary(discovery.scan_all())


def mcp_scan_npm() -> dict[str, Any]:
    """Tool entry point: run the npm scanner only."""
    return _make_summary(MCPAutoDiscovery().scan_npm_global())


def mcp_scan_pip() -> dict[str, Any]:
    """Tool entry point: run the pip scanner only."""
    return _make_summary(MCPAutoDiscovery().scan_pip_global())


def mcp_auto_register(config_path: str | None = None) -> dict[str, Any]:
    """Tool entry point: discover candidates and write them into the config."""
    target = Path(config_path).expanduser() if config_path else (
        Path.home() / ".Zeloo" / "config.yaml"
    )
    discovery = MCPAutoDiscovery()
    candidates = discovery.scan_all()
    added = discovery.auto_register(candidates, target)
    return {
        "scanned": len(candidates),
        "added": added,
        "config_path": str(target),
        "candidates": [c.name for c in candidates],
    }


__all__ = [
    "MCPServerCandidate",
    "MCPAutoDiscovery",
    "mcp_scan_all",
    "mcp_scan_npm",
    "mcp_scan_pip",
    "mcp_auto_register",
]
