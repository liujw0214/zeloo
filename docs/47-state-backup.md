# 47. State Database Backup & Recovery

> Design and usage of the WAL + snapshot backup subsystem that
> protects `zeloo_state/state.sqlite` from corruption and accidental
> data loss.

---

## 47.1 Motivation

`zeloo_state` is the project's canonical state store (sessions,
messages, kanban rows, registry). The underlying engine is SQLite in
WAL mode, which gives us crash-safe transactional semantics —
**but does not protect against**:

* Disk corruption
* Operator error (accidental `DELETE`)
* In-place migration bugs that overwrite the schema
* Hardware failure (controller / SSD end-of-life)

A scheduled snapshot pipeline (off-host or to a separate volume)
gives us a recovery point.

---

## 47.2 Two-layer protection

| Layer | Mechanism | What it covers | Cost |
|-------|-----------|----------------|------|
| **WAL** | `PRAGMA journal_mode=WAL` + periodic `PRAGMA wal_checkpoint` | Crashes mid-transaction (atomic commit) | Always-on, ~free |
| **Snapshot backup** | `Connection.backup` API → single self-contained `.sqlite` file | Logical disasters (corruption, bad migration, accidental delete) | Bounded I/O on a schedule |

The two layers are independent: WAL is the **crash-safety net**,
snapshots are the **point-in-time recovery net**. Either alone is
insufficient — together they cover both classes of failure.

---

## 47.3 Module layout

```
zeloo_state/
├── wal.py            ← WALManager (lifecycle) + BackupManager (snapshots)
├── maintenance.py    ← nightly PRAGMA optimize, etc.
├── repair.py         ← auto-repair on schema mismatch
└── schema.py         ← schema bootstrap + migration
```

Both `WALManager` and `BackupManager` are stateful classes that
operate on a single `db_path`. They share a `threading.Lock` so a
backup cannot race with an in-progress WAL checkpoint or repair.

### 47.3.1 `WALManager`

```python
from zeloo_state.wal import WALManager, WALStats

mgr = WALManager(Path("~/.Zeloo/state.sqlite"))
print(mgr.enable())                    # → "wal"
stats: WALStats = mgr.checkpoint("TRUNCATE")
print(stats.wal_size_bytes, stats.frames_checkpointed)
print(mgr.get_total_size())
# → {'db': 4194304, 'wal': 0, 'shm': 32768, 'total': 4227072}
```

* `enable()` — issues `PRAGMA journal_mode=WAL` once.
* `checkpoint(mode)` — runs `PRAGMA wal_checkpoint(mode)` and returns a
  `WALStats` dataclass.
* `get_mode()` / `get_wal_size()` / `get_shm_size()` /
  `get_db_size()` / `get_total_size()` — observability.

### 47.3.2 `BackupManager`

```python
from zeloo_state.wal import BackupManager

mgr = BackupManager(
    db_path=Path("~/.Zeloo/state.sqlite"),
    backup_dir=Path("~/.Zeloo/backups"),
    retention_count=7,  # keep the 7 most recent
)
result = mgr.snapshot(label="pre-upgrade")
# → BackupResult(
#     backup_path=.../state-20260909T230047-pre-upgrade.sqlite,
#     pages_backed_up=126,
#     remaining_pages=0,
#     wal_size_at_snapshot=8192,
#     duration_seconds=0.04,
#     schema_version=4,
# )

# Verify before pushing off-host.
v = mgr.verify(result.backup_path)
assert v.ok

# Restore — atomic: live DB + WAL/SHM siblings are moved aside,
# the snapshot is copied in, on failure the original files are
# moved back.
mgr.restore(result.backup_path)

# List / cleanup
for path in mgr.list_snapshots():
    print(path)
mgr.cleanup(retention_count=7)
```

---

## 47.4 Algorithm: `Connection.backup`

The SQLite online backup API works in **page-sized chunks**:

```text
src = sqlite3.connect(db_path)
dst = sqlite3.connect(target_partial)
backup_iter = dst.backup(src, pages=N, sleep=0)

while True:
    remaining = next(backup_iter)  # blocks until N pages copied
    if remaining <= 0:
        break
backup_iter.close()  # ensures backup.finish() runs

os.replace(target_partial, target)  # atomic publish
```

Each iteration copies *N* pages from the source into the destination
within the same transaction. Crucially, the API **drains the WAL**
into the destination automatically — so the snapshot contains every
committed frame, even if the WAL has not been checkpointed.

Our wrapper (`BackupManager._iter_backup`) returns
`(pages_backed, remaining)` so callers can include those numbers in
operational dashboards.

---

## 47.5 Atomicity guarantees

We use the **write-then-rename** pattern so a crash never leaves a
half-written snapshot in the backup directory:

```
backup_dir/
  state-20260909T230047-pre-upgrade.sqlite       ← final snapshot
  state-20260909T230047-pre-upgrade.sqlite.partial ← never published
```

Three layers of protection:

1. **Per-iteration transactional write** — each iteration of
   `Connection.backup` runs inside the destination's transaction.
2. **Single atomic rename** — `Path.replace` (wrapping `os.replace`)
   publishes the snapshot to its final name in one syscall.
3. **Defensive cleanup** — `finally:` block deletes any leftover
   `.partial` file even when the rename fails after dst.close().

Combined, the snapshot directory is always either empty (no snapshot
exists yet) or contains only complete snapshots.

---

## 47.6 Restore semantics

`BackupManager.restore(backup_path)`:

1. `verify(backup_path)` first — refuse to install a snapshot that
   fails `PRAGMA integrity_check`.
2. Move existing live files (`state.sqlite`, `state.sqlite-wal`,
   `state.sqlite-shm` if any) into a sibling `restore_<uuid>/` staging
   directory.
3. Copy the snapshot to the target path.
4. On exception, restore every moved sidecar to its origin and
   re-raise.
5. Always remove the staging directory.

The restore is **atomic from the caller's perspective**: either the
live DB has been replaced with the snapshot, or the live DB is
untouched. This mirrors the `os.replace` semantics used by
`checkpoint.save_dict` (Round 45) and `credential_crypto.save_dict`
(Round 47).

---

## 47.7 Rotation policy

`BackupManager(retention_count=N)` keeps the N most recent snapshots
in `backup_dir`; older ones are deleted on every successful snapshot.
Set `retention_count=0` to disable rotation entirely (e.g. for manual
operational review).

Default: **7** — one per day for a week. Tune based on the agent's
operational tempo:

| Cadence | Suggested `retention_count` |
|---------|------------------------------|
| Hourly | 24 (one day) |
| Daily  | 7 (one week) |
| Weekly | 4 (one month) |

---

## 47.8 Schedule (recommended)

The backup is best triggered from a `cron`-style job in
`zeloo_cli` rather than from inside the agent loop:

```yaml
# config.yaml
backup:
  schedule: "0 3 * * *"        # 03:00 daily
  retention: 7
  dest: "/var/lib/zeloo/snapshots"  # may be a separate volume
  verify_before_keep: true
```

The agent itself only exposes the `BackupManager` API. The scheduler
calls `mgr.snapshot()` → `mgr.verify()` → push to remote storage →
`mgr.cleanup()`.

---

## 47.9 Failure modes and recovery

| Symptom | Likely cause | Recovery |
|---------|--------------|----------|
| `BackupVerification.ok = False` | Snapshot was truncated or partially written | Take a new snapshot; if persistent, suspect storage layer |
| `Integrity check returned: 'database disk image is malformed'` | SQLite corruption (disk failure, OOM-killer mid-write) | Restore from most recent snapshot; if recent snapshot also corrupt, walk retention backwards |
| `restore()` raises `RuntimeError` | Snapshot failed integrity check | Pick an older snapshot, or accept data loss and continue |
| `BackupManager.snapshot()` raises `FileNotFoundError` | Source DB missing (file moved, mount lost) | Re-mount / restore from snapshot before continuing |
| `os.replace` raises `PermissionError` on Windows | Anti-virus / file-lock from another process holding the DB | Retry after closing other processes; otherwise live with the snapshot in `.partial` form and rename manually |

---

## 47.10 Operations dashboard

A snapshot's `BackupResult` exposes enough metrics for an ops
dashboard:

```python
result = mgr.snapshot()
log.info(
    "backup size=%d pages=%d wal=%d dur=%.2fs schema=%d",
    result.backup_path.stat().st_size,
    result.pages_backed_up,
    result.wal_size_at_snapshot,
    result.duration_seconds,
    result.schema_version,
)
```

Hook this into your existing telemetry pipeline; on `duration > 30s`
or `wal_size_at_snapshot > 1 GiB`, page on-call.

---

## 47.11 Testing

`tests/unit/test_wal_backup.py` covers:

* **WALManager** — `enable`, `checkpoint`, file-size accessors.
* **BackupManager algorithm** — default backup dir, explicit backup
  dir, retention zero, missing source DB, `verify` on missing path,
  `list_snapshots` ordering, `cleanup` retention math.
* **End-to-end** — snapshot self-contained, WAL-only changes don't
  leak, partial cleanup on failure, label/user_version propagation,
  verify pass/fail, restore round-trip, concurrent snapshots.

The end-to-end tests are skipped on Windows because the test runner's
sandbox sometimes denies `os.replace` on `.sqlite.partial` files
inside per-test temp directories. The algorithmic tests run on all
platforms.

---

## 47.12 Future work

* **Off-host push** — currently the snapshot lives on the same
  filesystem as the source DB. Wire `BackupManager.push_to(s3://...)`
  so snapshots survive a full disk failure.
* **Incremental snapshots** — SQLite 3.45+ supports incremental
  backups via `Connection.backup(target, pages=N, sleep=0,
  incremental=True)`. Once we upgrade, the same `BackupManager`
  surface can offer `incremental=True`.
* **PITR from WAL** — keep a separate cron that copies `.db-wal`
  every 5 minutes so we can replay WAL pages on top of a snapshot for
  sub-day PITR. (Currently the snapshot itself drains the WAL, so we
  only recover to the snapshot moment.)
