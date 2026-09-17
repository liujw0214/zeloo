#!/usr/bin/env python3
"""workspace_bootstrap.py — Zeloo workspace 初始化引导 + 双端同步桥接逻辑。

在 WSL Python 环境中直接运行(from pathlib import Path):
    python3 /root/zeloo/workspace_bootstrap.py

职责:
1. 确保 /root/zeloo/workspace_templates/ 目录存在
2. 把 workspace_templates/ 里的所有 .md 模板文件同步到:
     - /root/zeloo/workspace/           (活动工作区,Agent 实时读取)
     - /root/zeloo/memories/           (长期记忆区,仅限特定模板)
3. 同步策略:workspace_templates/ 是"黄金源码",workspace/ 和 memories/ 是"部署副本"
4. 仅当目标文件不存在(首次 init)或源文件更新时才覆盖
5. 输出同步报告(含文件大小、字节数)
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ZELOO_ROOT = Path("/root/zeloo")
TEMPLATES_DIR = ZELOO_ROOT / "workspace_templates"
WORKSPACE_DIR = ZELOO_ROOT / "workspace"
MEMORIES_DIR = ZELOO_ROOT / "memories"
STATE_DB = ZELOO_ROOT / "state.db"
BACKUPS_DIR = ZELOO_ROOT / "backups"

TEMPLATE_ROUTES: dict[str, Path | None] = {
    "HEARTBEAT.md": WORKSPACE_DIR,
    "MEMORY.md": MEMORIES_DIR,
    "AGENTS.md": WORKSPACE_DIR,
    "USER.md": WORKSPACE_DIR,
    "IDENTITY.md": WORKSPACE_DIR,
    "SOUL.md": WORKSPACE_DIR,
    "TOOLS.md": WORKSPACE_DIR,
    "PROJECTS.md": WORKSPACE_DIR,
}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dirs() -> None:
    for d in [TEMPLATES_DIR, WORKSPACE_DIR, MEMORIES_DIR, BACKUPS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def _file_sig(p: Path) -> dict:
    return {
        "path": str(p),
        "size_bytes": p.stat().st_size,
        "mtime": p.stat().st_mtime,
        "mtime_iso": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
    }


def _should_sync(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return True
    src_sig = _file_sig(src)
    dst_sig = _file_sig(dst)
    if src_sig["size_bytes"] != dst_sig["size_bytes"]:
        return True
    if src_sig["mtime"] > dst_sig["mtime"]:
        return True
    return False


def _sync_file(src: Path, dst: Path, dry_run: bool = False) -> dict:
    result: dict = {
        "src": str(src),
        "dst": str(dst),
        "action": None,
        "src_size": src.stat().st_size,
        "dst_size": None,
        "timestamp": _ts(),
    }
    if dry_run:
        result["action"] = "skip-dry-run" if dst.exists() else "create-dry-run"
        return result
    if _should_sync(src, dst):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        result["action"] = "copied"
        result["dst_size"] = dst.stat().st_size
    else:
        result["action"] = "skipped-identical"
        result["dst_size"] = dst.stat().st_size
    return result


def _init_state_db() -> None:
    if STATE_DB.exists():
        return
    STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(STATE_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bootstrap_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            action TEXT NOT NULL,
            src TEXT,
            dst TEXT,
            src_size INTEGER,
            dst_size INTEGER,
            payload TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workspace_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO workspace_meta VALUES (?, ?, ?)",
        ("initialized_at", _ts(), _ts()),
    )
    conn.commit()
    conn.close()


def _log_to_db(records: list[dict]) -> None:
    if not STATE_DB.exists():
        return
    conn = sqlite3.connect(str(STATE_DB))
    for rec in records:
        conn.execute(
            "INSERT INTO bootstrap_log (ts, action, src, dst, src_size, dst_size, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                rec["timestamp"],
                rec["action"],
                rec.get("src"),
                rec.get("dst"),
                rec.get("src_size"),
                rec.get("dst_size"),
                json.dumps(rec, ensure_ascii=False),
            ),
        )
    conn.commit()
    conn.close()


def _report_summary(results: list[dict]) -> None:
    total = len(results)
    copied = sum(1 for r in results if r["action"] == "copied")
    skipped = sum(1 for r in results if r["action"] in ("skipped-identical", "skip-dry-run"))
    dry_run_count = sum(1 for r in results if "dry-run" in (r["action"] or ""))

    print()
    print("=" * 60)
    print(f"  Bootstrap report @ {_ts()}")
    print(f"  Templates : {TEMPLATES_DIR}")
    print(f"  Workspace : {WORKSPACE_DIR}")
    print(f"  Memories  : {MEMORIES_DIR}")
    print(f"  Total     : {total}  copied={copied}  skipped={skipped}  dry={dry_run_count}")
    print("=" * 60)
    if results:
        print()
        print(f"  {'File':<24} {'Action':<20} {'Src B':>8}  {'Dst B':>8}")
        print(f"  {'-'*24} {'-'*20} {'-'*8}  {'-'*8}")
        for r in results:
            src_name = Path(r["src"]).name if r.get("src") else "?"
            print(
                f"  {src_name:<24} {r['action']:<20} "
                f"{r.get('src_size', 0):>8}  {r.get('dst_size') or '':>8}"
            )


def bootstrap(*, dry_run: bool = False, verbose: bool = False) -> list[dict]:
    print()
    print(f"[bootstrap] starting @ {_ts()}  dry_run={dry_run}")
    print(f"  ZELOO_ROOT   = {ZELOO_ROOT}")
    print(f"  TEMPLATES    = {TEMPLATES_DIR}")
    print(f"  WORKSPACE    = {WORKSPACE_DIR}")
    print(f"  MEMORIES     = {MEMORIES_DIR}")
    print()

    _ensure_dirs()
    _init_state_db()

    results: list[dict] = []

    if not TEMPLATES_DIR.exists():
        print(f"  [warn]   Templates dir does not exist: {TEMPLATES_DIR}")
        return results

    template_files = sorted(TEMPLATES_DIR.glob("*.md"))
    if not template_files:
        print(f"  [warn]   No .md files found in {TEMPLATES_DIR}")
        return results

    print(f"  Found {len(template_files)} template(s): {[f.name for f in template_files]}")
    print()

    for src in template_files:
        filename = src.name
        dst_root = TEMPLATE_ROUTES.get(filename)
        if dst_root is None:
            continue
        dst = dst_root / filename
        result = _sync_file(src, dst, dry_run=dry_run)
        results.append(result)

    _log_to_db(results)
    _report_summary(results)
    return results


def main() -> int:
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        print()
        print("Usage: python3 workspace_bootstrap.py [options]")
        print("  --dry-run, -n   show what would be done, without writing files")
        print("  --verbose, -v   print extra detail for each file")
        print("  --help, -h      show this message")
        return 0

    bootstrap(dry_run=dry_run, verbose=verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
