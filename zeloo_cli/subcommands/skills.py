"""Zeloo ``skills`` subcommand — skill discovery, installation and management."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from zeloo_cli.subcommands import Subcommand, subcommand


# --------------------------------------------------------------------------- #
# Local skill marketplace index.
# Each entry: name, description, tags, repository URL (optional).
# Used by ``skills search`` to demonstrate marketplace discovery without
# requiring network access.
# --------------------------------------------------------------------------- #
_SKILL_INDEX: list[dict[str, Any]] = [
    {
        "name": "code-review",
        "description": "Structured code review covering correctness, security, performance and maintainability.",
        "tags": ["review", "quality", "security", "pr"],
        "url": "https://github.com/zeloo/skills-code-review",
    },
    {
        "name": "debugging",
        "description": "Systematic debugging workflow for production and test failures.",
        "tags": ["debug", "trace", "fix", "incident"],
        "url": "https://github.com/zeloo/skills-debugging",
    },
    {
        "name": "refactor",
        "description": "Safe refactoring patterns to reduce complexity without breaking behavior.",
        "tags": ["refactor", "cleanup", "quality"],
        "url": "https://github.com/zeloo/skills-refactor",
    },
    {
        "name": "test-gen",
        "description": "Generate test cases from code or spec, including edge cases.",
        "tags": ["test", "coverage", "qa"],
        "url": "https://github.com/zeloo/skills-test-gen",
    },
    {
        "name": "db-schema",
        "description": "Design and review relational database schemas with indexes and constraints.",
        "tags": ["database", "schema", "sql"],
        "url": "https://github.com/zeloo/skills-db-schema",
    },
    {
        "name": "api-design",
        "description": "REST/GraphQL API design patterns and review checklist.",
        "tags": ["api", "rest", "graphql", "design"],
        "url": "https://github.com/zeloo/skills-api-design",
    },
    {
        "name": "planning",
        "description": "Project planning, milestones, risk assessment and dependency mapping.",
        "tags": ["plan", "milestone", "roadmap"],
        "url": "https://github.com/zeloo/skills-planning",
    },
    {
        "name": "reflect",
        "description": "Self-reflection workflow for post-mortem and continuous improvement.",
        "tags": ["reflect", "postmortem", "review"],
        "url": "https://github.com/zeloo/skills-reflect",
    },
    {
        "name": "file-todos",
        "description": "Manage TODO lists stored in markdown files alongside code.",
        "tags": ["todo", "task", "markdown"],
        "url": "https://github.com/zeloo/skills-file-todos",
    },
    {
        "name": "caveman",
        "description": "Simplify language to plain, concrete terms.",
        "tags": ["writing", "simplify"],
        "url": "https://github.com/zeloo/skills-caveman",
    },
    {
        "name": "ponytail",
        "description": "Forces the laziest working solution via YAGNI ladder.",
        "tags": ["yagni", "minimal", "simple"],
        "url": "https://github.com/zeloo/skills-ponytail",
    },
    {
        "name": "rtk",
        "description": "Rust-style command line output compression utility.",
        "tags": ["cli", "output", "tooling"],
        "url": "https://github.com/zeloo/skills-rtk",
    },
]


@subcommand("skills")
class SkillsCmd(Subcommand):
    name = "skills"
    help = "List, search, install and inspect skills"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="skills_action", help="Skills action")

        list_p = sub.add_parser("list", help="List installed skills")
        list_p.add_argument(
            "--json", action="store_true",
            help="Output as machine-readable JSON",
        )

        search_p = sub.add_parser("search", help="Search skills in directory")
        search_p.add_argument("query", help="Search query string")
        search_p.add_argument(
            "--json", action="store_true",
            help="Output as machine-readable JSON",
        )

        install_p = sub.add_parser(
            "install", help="Install a skill from a local path, Git URL or ZIP",
        )
        install_p.add_argument(
            "identifier",
            help="Skill identifier: local path, git URL or ZIP URL",
        )
        install_p.add_argument(
            "--name", default=None,
            help="Override the installed skill directory name",
        )
        install_p.add_argument(
            "--force", action="store_true",
            help="Overwrite an existing installed skill",
        )

        update_p = sub.add_parser(
            "update", help="Update an installed skill (re-runs install logic)",
        )
        update_p.add_argument("name", help="Skill name to update")
        update_p.add_argument(
            "--source", default=None,
            help="Source URL/path to pull from (defaults to registry)",
        )

        inspect_p = sub.add_parser("inspect", help="Show detailed skill info")
        inspect_p.add_argument("name", help="Skill name to inspect")

        sub.add_parser("check", help="Check skill integrity")

        sub.add_parser("enable", help="Enable a disabled skill (alias: install)")
        sub.add_parser("disable", help="Disable an installed skill (no-op stub)")

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "skills_action", None)
        if action == "list":
            return self._list(getattr(args, "json", False))
        if action == "search":
            return self._search(args.query, getattr(args, "json", False))
        if action == "install":
            return self._install(args.identifier, name=getattr(args, "name", None),
                                 force=getattr(args, "force", False))
        if action == "update":
            return self._update(args.name, getattr(args, "source", None))
        if action == "inspect":
            return self._inspect(args.name)
        if action == "check":
            return self._check()
        if action == "enable":
            print("Use 'skills install <name>' to enable a new skill.")
            return 0
        if action == "disable":
            print("skills disable is a no-op stub for backward compatibility.")
            return 0
        print("Usage: Zeloo skills [list|search|install|update|inspect|check|enable|disable]")
        return 1

    # -- helpers ---------------------------------------------------------- #

    def _get_skills_dirs(self) -> list[Path]:
        home = self._get_zeloo_home()
        return [
            home / "skills",
            Path(__file__).parent.parent.parent / "skills",
        ]

    def _get_zeloo_home(self) -> Path:
        val = os.environ.get("ZELOO_HOME", "").strip()
        if val:
            return Path(val)
        if sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA", "").strip()
            base = Path(local) if local else Path.home() / "AppData" / "Local"
            return base / "Zeloo"
        return Path.home() / ".Zeloo"

    def _installed_names(self) -> set[str]:
        names: set[str] = set()
        for sd in self._get_skills_dirs():
            if not sd.exists():
                continue
            for p in sd.iterdir():
                if p.is_dir():
                    names.add(p.name)
        return names

    def _discover_skills(self) -> list[dict]:
        skills: list[dict] = []
        for sd in self._get_skills_dirs():
            if not sd.exists():
                continue
            for skill_dir in sorted(sd.iterdir()):
                if not skill_dir.is_dir():
                    continue
                manifest = skill_dir / "manifest.md"
                skill_md = skill_dir / "SKILL.md"
                if manifest.exists():
                    info = self._parse_manifest(manifest, skill_dir.name)
                    if info:
                        info["source"] = str(sd)
                        skills.append(info)
                elif skill_md.exists():
                    info = self._parse_skill_md(skill_md, skill_dir.name)
                    if info:
                        info["source"] = str(sd)
                        skills.append(info)
        return skills

    def _parse_manifest(self, path: Path, fallback_name: str) -> dict | None:
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return None
        meta = self._parse_frontmatter(content)
        return {
            "name": meta.get("name", fallback_name),
            "description": meta.get("description", ""),
            "version": meta.get("version", "unknown"),
            "requires": meta.get("requires", []),
            "path": str(path.parent),
        }

    def _parse_skill_md(self, path: Path, fallback_name: str) -> dict | None:
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return None
        meta = self._parse_frontmatter(content)
        return {
            "name": meta.get("name", fallback_name),
            "description": meta.get("description", ""),
            "version": meta.get("version", "unknown"),
            "requires": meta.get("requires", []),
            "path": str(path.parent),
        }

    def _parse_frontmatter(self, content: str) -> dict:
        """Parse YAML frontmatter from markdown content."""
        try:
            import yaml
        except ImportError:
            return {}
        lines = content.splitlines()
        if not lines:
            return {}
        first_line = lines[0].strip().lstrip("\ufeff")
        if not first_line == "---":
            return {}
        fm_lines: list[str] = []
        for line in lines[1:]:
            if line.strip() == "---":
                break
            fm_lines.append(line)
        fm_text = "\n".join(fm_lines)
        try:
            data = yaml.safe_load(fm_text) or {}
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    # -- listing ---------------------------------------------------------- #

    def _list(self, as_json: bool) -> int:
        skills = self._discover_skills()
        if not skills:
            print("No skills found.")
            return 0

        if as_json:
            print(json.dumps(skills, indent=2, ensure_ascii=False))
            return 0

        from zeloo_cli.rich_render import make_console, make_table

        console = make_console()
        table = make_table(
            title=f"Installed skills ({len(skills)})",
            columns=[
                ("NAME", "bold cyan"),
                ("VERSION", "yellow"),
                ("DESCRIPTION", "white"),
                ("SOURCE", "dim"),
            ],
        )
        for s in skills:
            table.add_row(
                s.get("name", "?"),
                s.get("version", "?"),
                (s.get("description", "") or "")[:60],
                s.get("source", "?")[:40],
            )
        console.print(table)
        return 0

    # -- search ----------------------------------------------------------- #

    def _search(self, query: str, as_json: bool) -> int:
        """Search the local skill index for *query* (case-insensitive)."""
        if not query or not query.strip():
            print("Usage: Zeloo skills search <query>")
            return 1

        q = query.strip().lower()
        installed = self._installed_names()
        results: list[dict] = []

        for entry in _SKILL_INDEX:
            haystack_parts = [
                entry.get("name", "").lower(),
                entry.get("description", "").lower(),
                " ".join(entry.get("tags", [])).lower(),
            ]
            haystack = " ".join(haystack_parts)
            if q in haystack:
                results.append({
                    "name": entry.get("name"),
                    "description": entry.get("description", ""),
                    "tags": entry.get("tags", []),
                    "url": entry.get("url"),
                    "installed": entry.get("name") in installed,
                })

        if as_json:
            print(json.dumps({"query": query, "count": len(results), "results": results},
                             indent=2, ensure_ascii=False))
            return 0

        if not results:
            print(f"No skills match '{query}'.")
            return 0

        from zeloo_cli.rich_render import make_console, make_table

        console = make_console()
        table = make_table(
            title=f"Search results for '{query}' ({len(results)})",
            columns=[
                ("NAME", "bold cyan"),
                ("TAGS", "magenta"),
                ("STATUS", "green"),
                ("DESCRIPTION", "white"),
            ],
        )
        for r in results:
            status = "installed" if r["installed"] else "available"
            table.add_row(
                r["name"],
                ", ".join(r.get("tags", []))[:40],
                status,
                (r.get("description", "") or "")[:60],
            )
        console.print(table)
        return 0

    # -- install ---------------------------------------------------------- #

    def _install(self, identifier: str, name: str | None = None,
                 force: bool = False) -> int:
        """Install a skill from a local path, git URL or ZIP URL."""
        if not identifier or not identifier.strip():
            print("Usage: Zeloo skills install <path-or-url>")
            return 1

        target_root = self._get_zeloo_home() / "skills"
        target_root.mkdir(parents=True, exist_ok=True)

        identifier = identifier.strip()
        # Strip trailing slashes / .git suffix for git URLs.
        if identifier.endswith(".git"):
            identifier = identifier[:-4]

        try:
            if identifier.startswith(("http://", "https://")):
                if identifier.lower().endswith(".zip"):
                    return self._install_from_zip(identifier, target_root, name, force)
                return self._install_from_git(identifier, target_root, name, force)
            return self._install_from_path(identifier, target_root, name, force)
        except (urllib.error.URLError, OSError, subprocess.CalledProcessError,
                zipfile.BadZipFile, ValueError) as exc:
            print(f"[ERROR] Failed to install '{identifier}': {exc}")
            return 1

    def _install_from_path(self, src: str, target_root: Path,
                           name: str | None, force: bool) -> int:
        src_path = Path(src).expanduser()
        if not src_path.exists():
            raise ValueError(f"local path does not exist: {src_path}")

        skill_dir = self._resolve_skill_dir(src_path)
        if skill_dir is None:
            raise ValueError(
                f"no SKILL.md or manifest.md found under: {src_path}"
            )

        target_name = name or skill_dir.name
        dest = target_root / target_name
        if dest.exists():
            if not force:
                print(f"[ERROR] Skill '{target_name}' already installed. "
                      f"Use --force to overwrite.")
                return 1
            shutil.rmtree(dest)

        shutil.copytree(skill_dir, dest)
        return self._report_install(dest)

    def _install_from_git(self, url: str, target_root: Path,
                          name: str | None, force: bool) -> int:
        target_name = name or self._name_from_url(url)
        dest = target_root / target_name
        if dest.exists():
            if not force:
                print(f"[ERROR] Skill '{target_name}' already installed. "
                      f"Use --force to overwrite.")
                return 1
            shutil.rmtree(dest)

        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", url + ".git", str(dest)],
                check=True, capture_output=True, text=True,
            )
        except FileNotFoundError as exc:
            raise ValueError("git executable not found on PATH") from exc
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or "").strip() or str(exc)
            raise ValueError(f"git clone failed: {err}") from exc

        # Some repos wrap the SKILL.md one level deeper.
        skill_dir = self._resolve_skill_dir(dest)
        if skill_dir is None or skill_dir != dest:
            # If nested, surface a clearer error.
            raise ValueError(
                f"cloned repository has no SKILL.md at root: {dest}"
            )
        return self._report_install(dest)

    def _install_from_zip(self, url: str, target_root: Path,
                          name: str | None, force: bool) -> int:
        target_name = name or self._name_from_url(url)
        dest = target_root / target_name
        if dest.exists():
            if not force:
                print(f"[ERROR] Skill '{target_name}' already installed. "
                      f"Use --force to overwrite.")
                return 1
            shutil.rmtree(dest)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            zip_path = tmp_root / "skill.zip"
            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    data = resp.read()
            except urllib.error.URLError as exc:
                raise ValueError(f"failed to download zip: {exc}") from exc
            zip_path.write_bytes(data)
            try:
                with zipfile.ZipFile(zip_path) as zf:
                    zf.extractall(tmp_root / "extracted")
            except zipfile.BadZipFile as exc:
                raise ValueError(f"downloaded file is not a valid zip: {exc}") from exc

            extracted = tmp_root / "extracted"
            skill_dir = self._resolve_skill_dir(extracted)
            if skill_dir is None:
                raise ValueError(
                    f"downloaded zip contains no SKILL.md: {url}"
                )
            shutil.copytree(skill_dir, dest)
        return self._report_install(dest)

    def _report_install(self, dest: Path) -> int:
        skill_md = dest / "SKILL.md"
        manifest = dest / "manifest.md"
        meta: dict = {}
        path = skill_md if skill_md.exists() else manifest if manifest.exists() else None
        if path:
            meta = self._parse_frontmatter(path.read_text(encoding="utf-8"))

        name = meta.get("name", dest.name)
        version = meta.get("version", "unknown")
        requires = meta.get("requires", [])
        print(f"[OK] Installed skill '{name}' (version {version}) to {dest}")

        if requires:
            missing = [r for r in requires
                       if isinstance(r, str) and r not in self._installed_names()]
            if missing:
                print(f"[WARN] Missing dependencies: {', '.join(missing)}")
                print("       Run: Zeloo skills install <dep-name>")
            else:
                print(f"[OK] All dependencies present: {', '.join(requires)}")
        return 0

    def _resolve_skill_dir(self, base: Path) -> Path | None:
        """Locate a directory containing SKILL.md or manifest.md."""
        if not base.exists() or not base.is_dir():
            return None
        if (base / "SKILL.md").exists() or (base / "manifest.md").exists():
            return base
        for child in sorted(base.iterdir()):
            if child.is_dir() and ((child / "SKILL.md").exists()
                                   or (child / "manifest.md").exists()):
                return child
        return None

    @staticmethod
    def _name_from_url(url: str) -> str:
        # Strip trailing slash, take last path segment, strip any extension.
        cleaned = url.rstrip("/").rsplit("/", 1)[-1]
        if cleaned.lower().endswith(".zip"):
            cleaned = cleaned[:-4]
        if cleaned.lower().endswith(".git"):
            cleaned = cleaned[:-4]
        return cleaned or "skill"

    def _update(self, name: str, source: str | None) -> int:
        """Update an installed skill by re-running the install flow."""
        if not name:
            print("Usage: Zeloo skills update <name>")
            return 1

        target_root = self._get_zeloo_home() / "skills"
        dest = target_root / name
        if not dest.exists():
            print(f"[ERROR] Skill '{name}' is not installed.")
            return 1

        # Read manifest to find a source URL hint.
        if not source:
            skill_md = dest / "SKILL.md"
            if skill_md.exists():
                meta = self._parse_frontmatter(skill_md.read_text(encoding="utf-8"))
                source = meta.get("source") or meta.get("repository") or meta.get("url")

        if not source:
            print(f"[ERROR] No source URL known for '{name}'. "
                  f"Re-run with --source <url-or-path>.")
            return 1

        print(f"Updating '{name}' from {source} ...")
        return self._install(source, name=name, force=True)

    # -- inspect / check -------------------------------------------------- #

    def _inspect(self, name: str) -> int:
        skills = self._discover_skills()
        for skill in skills:
            if skill.get("name") == name:
                print(f"Skill: {skill.get('name')}")
                print(f"  Version:   {skill.get('version')}")
                print(f"  Description: {skill.get('description')}")
                print(f"  Requires:  {skill.get('requires', [])}")
                print(f"  Path:      {skill.get('path')}")
                print(f"  Source:    {skill.get('source')}")
                return 0
        print(f"Skill not found: {name}")
        return 1

    def _check(self) -> int:
        print("Checking skill integrity...")
        skills = self._discover_skills()
        ok_count = 0
        warn_count = 0
        for skill in skills:
            path = Path(skill.get("path", ""))
            manifest = path / "manifest.md"
            skill_md = path / "SKILL.md"
            if manifest.exists() or skill_md.exists():
                ok_count += 1
            else:
                warn_count += 1
                print(f"  [WARN] {skill.get('name')}: No manifest or SKILL.md found")
        print(f"Integrity check complete: {ok_count} OK, {warn_count} warnings")
        return 0 if warn_count == 0 else 1


def build_skills_parser(subparsers: Any, *, cmd_skills_handler: Any) -> None:
    """Attach the Hermes-style ``skills`` subparser."""
    from typing import Any

    skills_parser = subparsers.add_parser(
        "skills", help="Skill management", description="List, search, install and inspect skills"
    )
    skills_subparsers = skills_parser.add_subparsers(dest="skills_action")

    list_p = skills_subparsers.add_parser("list", help="List installed skills")
    list_p.add_argument(
        "--json", action="store_true",
        help="Output as machine-readable JSON",
    )

    search_p = skills_subparsers.add_parser("search", help="Search skills in directory")
    search_p.add_argument("query", help="Search query string")
    search_p.add_argument("--json", action="store_true")

    install_p = skills_subparsers.add_parser(
        "install", help="Install a skill from a local path, Git URL or ZIP",
    )
    install_p.add_argument("identifier", help="Skill identifier (name or URL)")
    install_p.add_argument("--name", default=None)
    install_p.add_argument("--force", action="store_true")

    update_p = skills_subparsers.add_parser("update", help="Update an installed skill")
    update_p.add_argument("name", help="Skill name to update")
    update_p.add_argument("--source", default=None)

    inspect_p = skills_subparsers.add_parser("inspect", help="Show detailed skill info")
    inspect_p.add_argument("name", help="Skill name to inspect")

    skills_subparsers.add_parser("check", help="Check skill integrity")
    skills_subparsers.add_parser("enable", help="Enable a disabled skill")
    skills_subparsers.add_parser("disable", help="Disable an installed skill")

    skills_parser.set_defaults(func=cmd_skills_handler)
