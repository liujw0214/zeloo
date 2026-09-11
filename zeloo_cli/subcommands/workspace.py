"""Zeloo workspace subcommand — workspace lifecycle management.

create, list, switch, archive, restore workspaces.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("workspace")
class WorkspaceCmd(Subcommand):
    name = "workspace"
    help = "Manage workspaces (create, list, switch, archive, restore)"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="workspace_action", help="Workspace action")

        create_p = sub.add_parser("create", help="Create a new workspace")
        create_p.add_argument("name", help="Workspace name")
        create_p.add_argument("--template", help="Template to copy from", default=None)
        create_p.add_argument("--description", help="Workspace description", default="")
        create_p.add_argument(
            "--Zeloo-home", help="zeloo_HOME directory", default=None
        )

        list_p = sub.add_parser("list", help="List all workspaces")
        list_p.add_argument("--format", choices=["table", "json"], default="table")

        switch_p = sub.add_parser(
            "switch", help="Switch to a workspace by updating active symlink or config"
        )
        switch_p.add_argument("name", help="Workspace name to switch to")
        switch_p.add_argument(
            "--Zeloo-home", help="zeloo_HOME directory", default=None
        )

        archive_p = sub.add_parser("archive", help="Archive a workspace to a tar.zst snapshot")
        archive_p.add_argument("name", help="Workspace name to archive")
        archive_p.add_argument(
            "--Zeloo-home", help="zeloo_HOME directory", default=None
        )

        restore_p = sub.add_parser("restore", help="Restore a workspace from an archive")
        restore_p.add_argument("archive", help="Path to .tar.zst archive file")
        restore_p.add_argument(
            "--target-home", help="Target zeloo_HOME directory", default=None
        )
        restore_p.add_argument("--dry-run", action="store_true", help="Preview restore plan")
        restore_p.add_argument(
            "--Zeloo-home", help="zeloo_HOME directory", default=None
        )

        delete_p = sub.add_parser("delete", help="Archive-then-delete a workspace")
        delete_p.add_argument("name", help="Workspace name to archive-then-delete")
        delete_p.add_argument(
            "--Zeloo-home", help="zeloo_HOME directory", default=None
        )
        delete_p.add_argument("--confirm", action="store_true", help="Skip confirmation prompt")
        delete_p.add_argument(
            "--archive-only", action="store_true", help="Only archive, do not delete"
        )

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "workspace_action", None)
        if action is None:
            print(
                "Usage: Zeloo workspace {create,list,switch,archive,restore,delete} ..."
            )
            return 0

        zeloo_home = Path(
            getattr(args, "zeloo_home", None) or self._default_zeloo_home()
        )
        if action == "create":
            return self._create(args, zeloo_home)
        if action == "list":
            return self._list(args, zeloo_home)
        if action == "switch":
            return self._switch(args, zeloo_home)
        if action == "archive":
            return self._archive(args, zeloo_home)
        if action == "restore":
            return self._restore(args, zeloo_home)
        if action == "delete":
            return self._delete(args, zeloo_home)
        return 0

    def _default_zeloo_home(self) -> Path:
        import os
        env = os.environ.get("zeloo_HOME")
        if env:
            return Path(env)
        return Path.home() / ".Zeloo"

    def _workspace_index(self, zeloo_home: Path) -> dict:
        index_path = zeloo_home / "workspace.json"
        if index_path.exists():
            with open(index_path, encoding="utf-8") as f:
                return json.load(f)
        return {"workspaces": {}, "active": None}

    def _save_index(self, index: dict, zeloo_home: Path) -> None:
        zeloo_home.mkdir(parents=True, exist_ok=True)
        index_path = zeloo_home / "workspace.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)

    def _workspace_path(self, name: str, zeloo_home: Path) -> Path:
        return zeloo_home / f"workspace-{name}"

    def _archive_path(self, name: str, zeloo_home: Path) -> Path:
        return zeloo_home / "archive" / f"ws-{name}.tar.gz"

    def _create(self, args: argparse.Namespace, zeloo_home: Path) -> int:
        name = args.name
        if not name.replace("-", "").replace("_", "").isalnum():
            print("ERROR: name must be alphanumeric (hyphens/underscores allowed", file=sys.stderr)
            return 1
        ws_path = self._workspace_path(args.name, zeloo_home)
        zeloo_home.mkdir(parents=True, exist_ok=True)
        if ws_path.exists():
            print(f"ERROR: workspace '{name}' already exists", file=sys.stderr)
            return 1
        ws_path.mkdir(parents=True)
        (ws_path / "memory").mkdir()
        (ws_path / "skills").mkdir()
        index = self._workspace_index(zeloo_home)
        index["workspaces"][name] = {
            "path": str(ws_path),
            "created_at": self._now(),
        }
        if index.get("active") is None:
            index["active"] = name
        self._save_index(index, zeloo_home)
        print(f"Created workspace '{name}' at {ws_path}")
        return 0

    def _list(self, args: argparse.Namespace, zeloo_home: Path) -> int:
        index = self._workspace_index(zeloo_home)
        workspaces = index.get("workspaces", {})
        active = index.get("active")
        if args.format == "json":
            print(json.dumps(index, indent=2, ensure_ascii=False))
            return 0
        if not workspaces:
            print("No workspaces found.")
            return 0
        print(f"{'NAME':<20} {'CREATED':<26} {'PATH'}")
        print("-" * 70)
        for name, meta in sorted(workspaces.items()):
            marker = " *" if name == active else "  "
            print(f"{marker}{name:<18} {meta.get('created_at', ''):<26} {meta.get('path', '')}")
        return 0

    def _switch(self, args: argparse.Namespace, zeloo_home: Path) -> int:
        index = self._workspace_index(zeloo_home)
        name = args.name
        if name not in index.get("workspaces", {}):
            print(f"ERROR: workspace '{name}' not found", file=sys.stderr)
            return 1
        index["active"] = name
        self._save_index(index, zeloo_home)
        print(f"Switched to workspace '{name}'")
        return 0

    def _archive(self, args: argparse.Namespace, zeloo_home: Path) -> int:
        import tarfile
        name = args.name
        index = self._workspace_index(zeloo_home)
        if name not in index.get("workspaces", {}):
            print(f"ERROR: workspace '{name}' not found", file=sys.stderr)
            return 1
        ws_path = Path(index["workspaces"][name]["path"])
        archive_dir = zeloo_home / "archive"
        archive_dir.mkdir(exist_ok=True)
        archive_path = self._archive_path(name, zeloo_home)
        with tarfile.open(archive_path, "w:gz") as tf:
            tf.addtree = getattr(tf, "addtree", None) or (lambda a, b: None)
            tf.add(ws_path, arcname=ws_path.name)
        print(f"Archived '{name}' -> {archive_path}")
        return 0

    def _restore(self, args: argparse.Namespace, zeloo_home: Path) -> int:
        import tarfile
        archive_path = Path(args.archive)
        if not archive_path.exists():
            print(f"ERROR: archive not found: {archive_path}", file=sys.stderr)
            return 1
        target_home = Path(args.target_home) if args.target_home else zeloo_home
        if args.dry_run:
            with tarfile.open(archive_path) as tf:
                print(f"Would restore to {target_home}:")
                for m in tf.getnames():
                    print(f"  {m}")
            return 0
        target_home.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path) as tf:
            tf.extractall(target_home)
        print(f"Restored archive to {target_home}")
        return 0

    def _delete(self, args: argparse.Namespace, zeloo_home: Path) -> int:
        name = args.name
        index = self._workspace_index(zeloo_home)
        if name not in index.get("workspaces", {}):
            print(f"ERROR: workspace '{name}' not found", file=sys.stderr)
            return 1
        if not args.confirm:
            confirm = input(f"Archive and delete workspace '{name}'? [y/N] ")
            if confirm.strip().lower() not in ("y", "yes"):
                print("Aborted.")
                return 1
        archive_path = self._archive_path(name, zeloo_home)
        ws_path = Path(index["workspaces"][name]["path"])
        import tarfile
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "w:gz") as tf:
            tf.add(ws_path, arcname=ws_path.name)
        if not args.archive_only:
            shutil.rmtree(ws_path)
            del index["workspaces"][name]
            if index.get("active") == name:
                remaining = list(index["workspaces"].keys())
                index["active"] = remaining[0] if remaining else None
            self._save_index(index, zeloo_home)
        tail = "" if args.archive_only else " and deleted workspace"
        print(f"Archived to {archive_path}{tail}")
        return 0

    @staticmethod
    def _now() -> str:
        from datetime import datetime
        return datetime.now().isoformat()
