# workspace/AGENTS.md

## 本包职责

Workspace 管理工作区：负责工作区的创建、快照、迁移。

## 核心模块

- `manager.py`：WorkspaceManager + WORKSPACE_MD_FILES
- `snapshot.py`：WorkspaceSnapshot + ArchiveMetadata
- `importer.py`：WorkspaceBundle 跨机器迁移
- `templates/`：8 个 MD 模板（自动加载到每个工作区）
  - SOUL.md / AGENTS.md / USER.md / TOOLS.md
  - IDENTITY.md / HEARTBEAT.md / BOOTSTRAP.md / MEMORY.md

## 工作区生命周期

1. `workspace_create` — 从已有工作区复制或全新创建
2. `workspace_switch` — 更新活跃时间戳
3. `workspace_archive` — 创建 .tar.zst 压缩快照
4. `workspace_restore` — 从快照恢复为新工作区

## 注意事项

- 工作区与档案（archive）隔离管理
- 删除前自动先快照（除非显式禁用）
- 不在项目间共享 `memory/` 文件
- `profile/` 包含敏感配置 — 快照前确保 `.env` 不含明文密钥
