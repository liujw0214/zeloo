# Zeloo Agent — Workspace Conventions

This file defines the Agent's behavioral conventions for this project and is automatically injected into the system prompt context layer.

## Project Overview

Zeloo is a self-hosted, self-evolving AI Agent runtime framework.

## Development Standards

- Follow PEP 8 code style
- Type annotations must be complete
- All public functions must have docstrings
- All dependencies must use exact version pinning (`==X.Y.Z`)

## Architecture Conventions

- System Prompt has three layers: stable / context / volatile
- Tools are auto-registered via the `@tool` decorator
- Memory and skills are runtime-mutable; the cache layer stays stable
- Workspaces (`workspace/`) and Archives (`archive/`) are managed in isolation

## Workspace Conventions

### Workspace

Each workspace is an independent, self-contained project environment:

```
~/.Zeloo/workspace/
├── workspace.json       # Workspace index
├── default/            # Default workspace
│   ├── profile/        # Zeloo config (config.yaml, .env)
│   ├── memory/         # Persistent memory (MEMORY.md, USER.md)
│   ├── skills/         # Workspace-local skills
│   ├── SOUL.md         # Optional local identity
│   └── metadata.json   # Workspace metadata
├── project-alpha/       # Project A
└── project-beta/        # Project B
```

### Archive

Compressed snapshots of workspaces, restorable at any time:

```
~/.Zeloo/archive/
├── archive.json            # Archive index
├── default/                # Organized by workspace
│   ├── snap_20260907.tar.zst
│   └── snap_milestone.tar.zst
└── project-alpha/
    └── snap_pre_delete.tar.zst
```

### Operations

1. **Create workspace**: `workspace_create` — clone from an existing workspace or create fresh
2. **Switch workspace**: `workspace_switch` — updates the last_active timestamp
3. **Snapshot workspace**: `workspace_archive` — creates a .tar.zst compressed snapshot
4. **Restore workspace**: `workspace_restore` — restores snapshot as a new workspace
5. **Delete workspace** — auto-archives before deletion (unless explicitly disabled)

### Tagging and Search

- Workspaces support tags (`workspace_add_tag`)
- Filter workspace list by tags
- Sort by `last_active` timestamp

### Migration Rules

- Do not share `memory/` files across projects — each workspace is independent
- `profile/` contains sensitive config — ensure `.env` has no plaintext secrets before archiving
- Restore always creates a new workspace — never overwrites an existing workspace with the same name
