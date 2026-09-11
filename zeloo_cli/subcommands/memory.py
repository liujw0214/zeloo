"""Zeloo ``memory`` subcommand — persistent memory file management.

Supports the full Hermes-aligned action set:

* ``list``     — list memory files
* ``show``     — show a memory file's contents
* ``add``      — append a new fact/preference to MEMORY.md
* ``search``   — keyword search across memory files
* ``forget``   — remove a memory entry (line-based)
* ``gc``       — invoke MemoryGarbageCollector
* ``compress`` — invoke MemoryCompressor
* ``export``   — dump memories to a JSON file
* ``import``   — restore memories from a JSON file
* ``stats``    — show memory statistics
* ``clear``    — clear memory files
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from zeloo_cli.subcommands import Subcommand, subcommand

logger = logging.getLogger(__name__)


@subcommand("memory")
class MemoryCmd(Subcommand):
    name = "memory"
    help = "Manage persistent memory files (list/show/add/search/forget/gc/compress/export/import/stats/clear)"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="memory_action", help="Memory action")

        sub.add_parser("list", help="List memory files")

        show_p = sub.add_parser("show", help="Show a memory file's contents")
        show_p.add_argument("file", help="Memory file name (e.g. MEMORY.md)")
        show_p.add_argument("--lines", "-n", type=int, default=None, help="Limit to last N lines")

        add_p = sub.add_parser("add", help="Append a fact to MEMORY.md")
        add_p.add_argument("content", help="Fact or preference text to remember")
        add_p.add_argument("--tag", action="append", default=[], help="Optional tags (repeatable)")
        add_p.add_argument("--file", default="MEMORY.md", help="Target file (default MEMORY.md)")

        search_p = sub.add_parser("search", help="Keyword search across memory files")
        search_p.add_argument("keyword", help="Keyword or phrase to search for")
        search_p.add_argument("--file", default=None, help="Limit to one file")
        search_p.add_argument("--limit", type=int, default=20, help="Max results (default 20)")
        search_p.add_argument("--json", action="store_true", help="Output JSON")

        forget_p = sub.add_parser("forget", help="Remove memory entries matching a pattern")
        forget_p.add_argument("pattern", help="Regex or literal text to remove")
        forget_p.add_argument("--file", default="MEMORY.md", help="Target file")
        forget_p.add_argument("--dry-run", action="store_true", help="Preview without writing")
        forget_p.add_argument("--yes", action="store_true", help="Skip confirmation")

        gc_p = sub.add_parser("gc", help="Run MemoryGarbageCollector")
        gc_p.add_argument("--max-age-days", type=int, default=90, help="Archive entries older than N days")
        gc_p.add_argument("--dry-run", action="store_true")
        gc_p.add_argument("--yes", action="store_true", help="Skip confirmation")

        compress_p = sub.add_parser("compress", help="Run MemoryCompressor (dedupe + merge)")
        compress_p.add_argument("--strategy", choices=["tfidf", "time_decay", "importance", "hybrid"], default="hybrid")
        compress_p.add_argument("--threshold", type=float, default=0.85, help="Similarity threshold 0-1")
        compress_p.add_argument("--yes", action="store_true")

        export_p = sub.add_parser("export", help="Export all memories to JSON file")
        export_p.add_argument("output", help="Output JSON file path")
        export_p.add_argument("--pretty", action="store_true")

        imp_p = sub.add_parser("import", help="Import memories from a JSON file")
        imp_p.add_argument("input", help="Input JSON file path")
        imp_p.add_argument("--merge", action="store_true", help="Merge with existing")
        imp_p.add_argument("--replace", action="store_true", help="Replace existing")
        imp_p.add_argument("--yes", action="store_true")

        stats_p = sub.add_parser("stats", help="Show memory statistics")
        stats_p.add_argument("--json", action="store_true")

        clear_p = sub.add_parser("clear", help="Clear memory files")
        clear_p.add_argument("--all", action="store_true", help="Clear all memory files")
        clear_p.add_argument("--force", action="store_true", help="Skip confirmation")

    # ──────────────────── dispatch ────────────────────

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "memory_action", None)
        if action == "list":
            return self._list()
        if action == "show":
            return self._show(args.file, args.lines)
        if action == "add":
            return self._add(args.content, args.file, args.tag)
        if action == "search":
            return self._search(args.keyword, args.file, args.limit, args.json)
        if action == "forget":
            return self._forget(args.pattern, args.file, args.dry_run, args.yes)
        if action == "gc":
            return self._gc(args.max_age_days, args.dry_run, args.yes)
        if action == "compress":
            return self._compress(args.strategy, args.threshold, args.yes)
        if action == "export":
            return self._export(args.output, args.pretty)
        if action == "import":
            return self._import(args.input, args.merge, args.replace, args.yes)
        if action == "stats":
            return self._stats(getattr(args, "json", False))
        if action == "clear":
            return self._clear(all_mem=getattr(args, "all", False), force=getattr(args, "force", False))
        print("Usage: Zeloo memory [list|show|add|search|forget|gc|compress|export|import|stats|clear]")
        return 1

    # ──────────────────── helpers ────────────────────

    def _get_zeloo_home(self) -> Path:
        val = os.environ.get("ZELOO_HOME", "").strip()
        if val:
            return Path(val)
        if sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA", "").strip()
            base = Path(local) if local else Path.home() / "AppData" / "Local"
            return base / "Zeloo"
        return Path.home() / ".Zeloo"

    def _get_memory_dirs(self) -> list[tuple[str, Path]]:
        home = self._get_zeloo_home()
        dirs: list[tuple[str, Path]] = []
        default_ws = home / "workspace" / "default"
        if default_ws.exists():
            mem_dir = default_ws / "memory"
            if mem_dir.exists():
                dirs.append(("default", mem_dir))
        return dirs

    def _format_size(self, size_bytes: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    def _format_time(self, timestamp: float) -> str:
        return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")

    # ──────────────────── actions ────────────────────

    def _list(self) -> int:
        dirs = self._get_memory_dirs()
        if not dirs:
            print("No memory directories found.")
            return 0

        from zeloo_cli.rich_render import make_console, make_table

        console = make_console()
        found_any = False
        for name, mem_dir in dirs:
            files = sorted(mem_dir.iterdir())
            if files:
                found_any = True
                print(f"\nWorkspace: {name}")
                table = make_table(
                    title=f"Memory files in {name}",
                    columns=[("FILENAME", "bold cyan"), ("SIZE", "yellow"), ("MODIFIED", "green")],
                )
                for f in files:
                    if f.is_file():
                        size_str = self._format_size(f.stat().st_size)
                        mtime_str = self._format_time(f.stat().st_mtime)
                        table.add_row(f.name, size_str, mtime_str)
                console.print(table)
            else:
                print(f"\nWorkspace: {name} — no memory files")

        if not found_any:
            print("No memory files found.")
        return 0

    def _show(self, filename: str, lines: int | None) -> int:
        target = self._resolve_file(filename)
        if target is None:
            print(f"Memory file not found: {filename}")
            return 1
        try:
            content = target.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"Read failed: {exc}")
            return 1
        if lines is not None:
            tail = content.splitlines()[-lines:]
            print("\n".join(tail))
        else:
            print(content)
        return 0

    def _add(self, content: str, filename: str, tags: list[str]) -> int:
        target = self._resolve_file(filename, create=True)
        if target is None:
            print(f"Cannot resolve target file: {filename}")
            return 1
        tag_str = ""
        if tags:
            tag_str = " " + " ".join(f"#{t}" for t in tags)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d")
        line = f"- [{timestamp}] {content}{tag_str}\n"
        try:
            with target.open("a", encoding="utf-8") as fh:
                fh.write(line)
            print(f"Added to {target.name}")
            return 0
        except Exception as exc:
            print(f"Write failed: {exc}")
            return 1

    def _search(self, keyword: str, filename: str | None, limit: int, as_json: bool) -> int:
        results: list[dict[str, Any]] = []
        needle = keyword.lower()
        for ws_name, mem_dir in self._get_memory_dirs():
            files = [mem_dir / filename] if filename else list(mem_dir.iterdir())
            for f in files:
                if not f.is_file():
                    continue
                try:
                    content = f.read_text(encoding="utf-8")
                except Exception:
                    continue
                for ln, text in enumerate(content.splitlines(), start=1):
                    if needle in text.lower():
                        results.append({
                            "file": f.name,
                            "line": ln,
                            "workspace": ws_name,
                            "text": text,
                        })
                        if len(results) >= limit:
                            break
                if len(results) >= limit:
                    break
        if as_json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
            return 0
        if not results:
            print(f"No matches for: {keyword}")
            return 0
        from zeloo_cli.rich_render import make_console, make_table
        console = make_console()
        table = make_table(
            title=f"Search results for '{keyword}'",
            columns=[("FILE", "cyan"), ("LINE", "yellow"), ("TEXT", "white")],
        )
        for r in results:
            table.add_row(f"{r['workspace']}/{r['file']}", str(r["line"]), r["text"])
        console.print(table)
        return 0

    def _forget(self, pattern: str, filename: str, dry_run: bool, yes: bool) -> int:
        target = self._resolve_file(filename)
        if target is None:
            print(f"Memory file not found: {filename}")
            return 1
        try:
            content = target.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"Read failed: {exc}")
            return 1
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = None
        kept: list[str] = []
        removed = 0
        for line in content.splitlines(keepends=True):
            stripped = line.strip()
            if regex is not None:
                hit = bool(regex.search(stripped))
            else:
                hit = pattern.lower() in stripped.lower()
            if hit and (stripped.startswith("- ") or stripped.startswith("# ")):
                removed += 1
                continue
            kept.append(line)
        if removed == 0:
            print(f"No entries matching '{pattern}' in {filename}")
            return 0
        if dry_run:
            print(f"[dry-run] Would remove {removed} entries matching '{pattern}' from {filename}")
            return 0
        if not yes:
            confirm = input(f"Remove {removed} entries from {filename}? [y/N] ")
            if confirm.lower() != "y":
                print("Cancelled.")
                return 0
        try:
            target.write_text("".join(kept), encoding="utf-8")
            print(f"Removed {removed} entries from {filename}")
            return 0
        except Exception as exc:
            print(f"Write failed: {exc}")
            return 1

    def _gc(self, max_age_days: int, dry_run: bool, yes: bool) -> int:
        try:
            from agent.memory_gc import MemoryGarbageCollector
        except ImportError as exc:
            print(f"GC module unavailable: {exc}")
            return 1
        collector = MemoryGarbageCollector(max_age_days=max_age_days)
        try:
            from agent.memory_manager import MemoryManager
            entries = MemoryManager().read_all() or []
        except Exception:
            entries = []
        candidates = collector.collect(entries) if entries else []
        if not candidates:
            print("No GC candidates found.")
            return 0
        if dry_run:
            print(f"[dry-run] Would archive {len(candidates)} entries")
            return 0
        if not yes:
            confirm = input(f"Archive {len(candidates)} entries? [y/N] ")
            if confirm.lower() != "y":
                print("Cancelled.")
                return 0
        collector.delete(entries, candidates)
        print(f"Archived {len(candidates)} entries.")
        return 0

    def _compress(self, strategy: str, threshold: float, yes: bool) -> int:
        try:
            from agent.memory_compressor import MemoryCompressor, CompressionStrategy
        except ImportError as exc:
            print(f"Compressor unavailable: {exc}")
            return 1
        try:
            from agent.memory_manager import MemoryManager
            entries = MemoryManager().read_all() or []
        except Exception:
            entries = []
        if not entries:
            print("No memory entries to compress.")
            return 0
        compressor = MemoryCompressor(strategy=CompressionStrategy(strategy))
        if not yes:
            confirm = input(f"Compress {len(entries)} entries? [y/N] ")
            if confirm.lower() != "y":
                print("Cancelled.")
                return 0
        compressed = compressor.compress(entries, similarity_threshold=threshold)
        print(f"Compressed {len(entries)} → {len(compressed)} entries.")
        return 0

    def _export(self, output: str, pretty: bool) -> int:
        target = Path(output).expanduser()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            print(f"Cannot create output dir: {exc}")
            return 1
        payload: dict[str, Any] = {"version": 1, "exported_at": datetime.datetime.utcnow().isoformat(), "workspaces": {}}
        for ws_name, mem_dir in self._get_memory_dirs():
            ws_data: dict[str, str] = {}
            for f in mem_dir.iterdir():
                if f.is_file():
                    try:
                        ws_data[f.name] = f.read_text(encoding="utf-8")
                    except Exception:
                        continue
            payload["workspaces"][ws_name] = ws_data
        try:
            target.write_text(
                json.dumps(payload, indent=2 if pretty else None, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"Exported to {target}")
            return 0
        except Exception as exc:
            print(f"Write failed: {exc}")
            return 1

    def _import(self, input_path: str, merge: bool, replace: bool, yes: bool) -> int:
        src = Path(input_path).expanduser()
        if not src.exists():
            print(f"Input file not found: {src}")
            return 1
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"Parse failed: {exc}")
            return 1
        workspaces = data.get("workspaces", {})
        if not workspaces:
            print("Nothing to import.")
            return 0
        target_workspaces = self._get_memory_dirs()
        if not target_workspaces:
            print("No target workspace found; run `zeloo init` first.")
            return 1
        if not merge and not replace:
            replace = True  # default
        if not yes:
            confirm = input(f"Import {sum(len(v) for v in workspaces.values())} files? [y/N] ")
            if confirm.lower() != "y":
                print("Cancelled.")
                return 0
        imported = 0
        for ws_name, ws_data in workspaces.items():
            target_dir = next((d for n, d in target_workspaces if n == ws_name), None)
            if target_dir is None:
                target_dir = target_workspaces[0][1]
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                continue
            for filename, content in ws_data.items():
                dest = target_dir / filename
                if dest.exists() and merge:
                    try:
                        existing = dest.read_text(encoding="utf-8")
                        if content.strip():
                            new_content = existing.rstrip() + "\n" + content + "\n"
                        else:
                            new_content = existing
                    except Exception:
                        new_content = content
                else:
                    new_content = content
                try:
                    dest.write_text(new_content, encoding="utf-8")
                    imported += 1
                except Exception:
                    continue
        print(f"Imported {imported} files.")
        return 0

    def _resolve_file(self, filename: str, create: bool = False) -> Path | None:
        for _ws, mem_dir in self._get_memory_dirs():
            candidate = mem_dir / filename
            if candidate.exists():
                return candidate
        if not create:
            return None
        for _ws, mem_dir in self._get_memory_dirs():
            try:
                mem_dir.mkdir(parents=True, exist_ok=True)
                target = mem_dir / filename
                if not target.exists():
                    target.write_text("# Persistent memory\n\n", encoding="utf-8")
                return target
            except Exception:
                continue
        return None

    def _stats(self, as_json: bool) -> int:
        from zeloo_state import SessionDB

        try:
            db = SessionDB()
            sessions = db.list_sessions(limit=100) or []
        except Exception as exc:
            print(f"Warning: Could not read session DB: {exc}")
            sessions = []

        session_count = len(sessions)
        total_messages = sum(s.get("message_count", 0) for s in sessions)

        dirs = self._get_memory_dirs()
        memory_files = 0
        memory_size = 0
        for _name, mem_dir in dirs:
            for f in mem_dir.iterdir():
                if f.is_file():
                    memory_files += 1
                    memory_size += f.stat().st_size

        if as_json:
            print(json.dumps({
                "sessions": session_count,
                "total_messages": total_messages,
                "memory_files": memory_files,
                "memory_size_bytes": memory_size,
                "memory_size_human": self._format_size(memory_size),
            }, indent=2, ensure_ascii=False))
            return 0

        from zeloo_cli.rich_render import make_console, render_keyvalue

        console = make_console()
        render_keyvalue([
            ("Sessions", str(session_count)),
            ("Total messages", str(total_messages)),
            ("Memory files", str(memory_files)),
            ("Memory size", self._format_size(memory_size)),
        ])
        return 0

    def _clear(self, all_mem: bool, force: bool) -> int:
        dirs = self._get_memory_dirs()
        if not dirs:
            print("No memory directories to clear.")
            return 0
        if not force:
            scope = "all memory files" if all_mem else "memory files"
            confirm = input(f"Clear {scope}? [y/N] ")
            if confirm.lower() != "y":
                print("Cancelled.")
                return 0
        cleared = 0
        for _name, mem_dir in dirs:
            for f in mem_dir.iterdir():
                if f.is_file():
                    try:
                        f.unlink()
                        cleared += 1
                    except Exception as exc:
                        print(f"  [WARN] Could not delete {f}: {exc}")
        print(f"Cleared {cleared} memory file(s).")
        return 0


def build_memory_parser(subparsers: Any, *, cmd_memory_handler: Any) -> None:
    """Attach the Hermes-style ``memory`` subparser."""
    from typing import Any

    memory_parser = subparsers.add_parser(
        "memory", help="Memory management", description="Manage persistent memory files"
    )
    memory_subparsers = memory_parser.add_subparsers(dest="memory_action")

    memory_subparsers.add_parser("list", help="List memory files")

    show_p = memory_subparsers.add_parser("show", help="Show a memory file's contents")
    show_p.add_argument("file", help="Memory file name (e.g. MEMORY.md)")
    show_p.add_argument("--lines", "-n", type=int, default=None)

    add_p = memory_subparsers.add_parser("add", help="Append a fact to MEMORY.md")
    add_p.add_argument("content", help="Fact text")
    add_p.add_argument("--tag", action="append", default=[])
    add_p.add_argument("--file", default="MEMORY.md")

    search_p = memory_subparsers.add_parser("search", help="Keyword search")
    search_p.add_argument("keyword")
    search_p.add_argument("--file", default=None)
    search_p.add_argument("--limit", type=int, default=20)
    search_p.add_argument("--json", action="store_true")

    forget_p = memory_subparsers.add_parser("forget", help="Remove matching entries")
    forget_p.add_argument("pattern")
    forget_p.add_argument("--file", default="MEMORY.md")
    forget_p.add_argument("--dry-run", action="store_true")
    forget_p.add_argument("--yes", action="store_true")

    gc_p = memory_subparsers.add_parser("gc", help="Run MemoryGarbageCollector")
    gc_p.add_argument("--max-age-days", type=int, default=90)
    gc_p.add_argument("--dry-run", action="store_true")
    gc_p.add_argument("--yes", action="store_true")

    compress_p = memory_subparsers.add_parser("compress", help="Run MemoryCompressor")
    compress_p.add_argument("--strategy", choices=["tfidf", "time_decay", "importance", "hybrid"], default="hybrid")
    compress_p.add_argument("--threshold", type=float, default=0.85)
    compress_p.add_argument("--yes", action="store_true")

    export_p = memory_subparsers.add_parser("export", help="Export memories to JSON")
    export_p.add_argument("output")
    export_p.add_argument("--pretty", action="store_true")

    imp_p = memory_subparsers.add_parser("import", help="Import memories from JSON")
    imp_p.add_argument("input")
    imp_p.add_argument("--merge", action="store_true")
    imp_p.add_argument("--replace", action="store_true")
    imp_p.add_argument("--yes", action="store_true")

    stats_p = memory_subparsers.add_parser("stats", help="Show memory statistics")
    stats_p.add_argument("--json", action="store_true")

    clear_p = memory_subparsers.add_parser("clear", help="Clear memory files")
    clear_p.add_argument("--all", action="store_true")
    clear_p.add_argument("--force", action="store_true")

    memory_parser.set_defaults(func=cmd_memory_handler)