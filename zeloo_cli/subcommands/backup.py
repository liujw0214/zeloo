"""Zeloo backup subcommand — backup management."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("backup")
class BackupCmd(Subcommand):
    name = "backup"
    help = "Create, list, restore or delete backups"

    BACKUP_METADATA_FILE = "backup_index.json"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="backup_action", help="Backup action")

        create_p = sub.add_parser("create", help="Create a new backup")
        create_p.add_argument("-o", "--output", type=Path, default=None, help="Output path for backup file")
        create_p.add_argument("--quick", action="store_true", help="Quick backup (config only)")

        sub.add_parser("list", help="List existing backups")

        restore_p = sub.add_parser("restore", help="Restore from a backup")
        restore_p.add_argument("path", type=Path, help="Path to backup file")
        restore_p.add_argument("--force", action="store_true", help="Overwrite existing files")

        delete_p = sub.add_parser("delete", help="Delete a backup")
        delete_p.add_argument("path", type=Path, help="Path to backup file")

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "backup_action", None)

        if action == "create":
            return self._create(args.output, args.quick)
        if action == "list":
            return self._list()
        if action == "restore":
            return self._restore(args.path, args.force)
        if action == "delete":
            return self._delete(args.path)

        print("Usage: Zeloo backup [create|list|restore|delete]")
        return 1

    def _get_zeloo_home(self) -> Path:
        from agent.zeloo_constants import get_zeloo_home
        return get_zeloo_home()

    def _get_backup_dir(self) -> Path:
        backup_dir = self._get_zeloo_home() / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir

    def _get_metadata_path(self) -> Path:
        return self._get_backup_dir() / self.BACKUP_METADATA_FILE

    def _load_metadata(self) -> dict:
        path = self._get_metadata_path()
        if not path.exists():
            return {"backups": []}
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"backups": []}

    def _save_metadata(self, metadata: dict) -> None:
        path = self._get_metadata_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def _get_backup_files(self) -> list:
        backup_dir = self._get_backup_dir()
        return sorted(
            [f for f in backup_dir.iterdir() if f.suffix == ".zip" and f.name != self.BACKUP_METADATA_FILE],
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )

    def _create(self, output: Path | None, quick: bool) -> int:
        from agent.zeloo_constants import get_zeloo_home

        home = get_zeloo_home()
        if not home.exists():
            print(f"Error: Zeloo home directory does not exist: {home}")
            return 1

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if output:
            backup_path = Path(output).expanduser().resolve()
        else:
            backup_path = self._get_backup_dir() / f"zeloo_backup_{timestamp}.zip"

        backup_path.parent.mkdir(parents=True, exist_ok=True)

        include_patterns = ["config.yaml", ".env", "profiles", "skills", "memories", "sessions"]
        if quick:
            include_patterns = ["config.yaml", ".env"]

        try:
            with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(home):
                    dirs[:] = [d for d in dirs if not d.startswith(".")]

                    for file in files:
                        if file.startswith("."):
                            continue

                        file_path = Path(root) / file
                        rel_path = file_path.relative_to(home)

                        should_include = False
                        for pattern in include_patterns:
                            if str(rel_path).startswith(pattern) or rel_path.name == pattern:
                                should_include = True
                                break

                        if should_include:
                            zf.write(file_path, rel_path)

            size = backup_path.stat().st_size
            print(f"Backup created: {backup_path}")
            print(f"Size: {size:,} bytes")

            metadata = self._load_metadata()
            metadata["backups"].append({
                "path": str(backup_path),
                "created_at": datetime.now().isoformat(),
                "size_bytes": size,
                "quick": quick,
            })
            self._save_metadata(metadata)

            return 0
        except PermissionError:
            print(f"Error: Permission denied writing to {backup_path}")
            return 1
        except Exception as exc:
            print(f"Backup failed: {exc}")
            return 1

    def _list(self) -> int:
        backups = self._get_backup_files()

        if not backups:
            print("No backups found.")
            print(f"Backup directory: {self._get_backup_dir()}")
            return 0

        print(f"Backups in {self._get_backup_dir()}:")
        print()

        for backup_file in backups:
            size = backup_file.stat().st_size
            mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)
            print(f"  {backup_file.name}")
            print(f"    Size: {size:,} bytes")
            print(f"    Created: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
            print()

        return 0

    def _restore(self, path: Path, force: bool) -> int:
        backup_path = Path(path).expanduser().resolve()

        if not backup_path.exists():
            print(f"Error: Backup file not found: {backup_path}")
            return 1

        if not backup_path.suffix == ".zip":
            print(f"Error: Not a valid backup file (expected .zip): {backup_path}")
            return 1

        home = self._get_zeloo_home()
        temp_dir = home.parent / f".zeloo_restore_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        try:
            temp_dir.mkdir(parents=True, exist_ok=True)

            print(f"Extracting backup: {backup_path}")
            with zipfile.ZipFile(backup_path, "r") as zf:
                zf.extractall(temp_dir)

            extracted_home = temp_dir
            for item in temp_dir.iterdir():
                if item.is_dir() and item.name == ".Zeloo":
                    extracted_home = item
                    break

            print(f"Restoring to: {home}")
            if force:
                if home.exists():
                    for item in home.iterdir():
                        if item.name in ("backups",):
                            continue
                        if item.is_dir():
                            shutil.rmtree(item)
                        else:
                            item.unlink()

            for item in extracted_home.iterdir():
                if item.name == "backups":
                    continue
                dest = home / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)

            shutil.rmtree(temp_dir)
            print("Restore completed successfully.")
            return 0

        except Exception as exc:
            print(f"Restore failed: {exc}")
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass
            return 1

    def _delete(self, path: Path) -> int:
        backup_path = Path(path).expanduser().resolve()

        if not backup_path.exists():
            print(f"Error: Backup file not found: {backup_path}")
            return 1

        try:
            backup_path.unlink()
            print(f"Deleted: {backup_path}")

            metadata = self._load_metadata()
            metadata["backups"] = [
                b for b in metadata.get("backups", [])
                if Path(b.get("path", "")).resolve() != backup_path
            ]
            self._save_metadata(metadata)

            return 0
        except Exception as exc:
            print(f"Delete failed: {exc}")
            return 1
