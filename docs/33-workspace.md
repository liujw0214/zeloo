# 33. 工作区管理（workspace）

> **作用域说明**：本工作区管理的是**运行时用户工作区**（位于 `~/.Zeloo/workspace/`），与项目根目录的 `AGENTS.md` / `SOUL.md`（开发 Agent 的项目级规范）**作用域不同**。工作区中的同名 MD 是**用户工作区初始化模板**，由 `workspace/templates/` 在创建新工作区时复制生成。两者内容互补而非重复。

## 33.1 模块总览

`workspace/` 是工作区管理的 Python 模块集合，提供自包含项目环境的创建、切换、快照与恢复功能：

```
workspace/                 # 工作区管理
├── __init__.py           # 导出 WorkspaceManager / WorkspaceSnapshot
├── manager.py            # WorkspaceManager + WorkspaceProfile + WORKSPACE_MD_FILES
├── snapshot.py           # WorkspaceSnapshot + ArchiveMetadata（快照管理）
├── importer.py           # WorkspaceBundle + export_workspace / import_workspace（跨机器迁移）
└── templates/            # 8 个 MD 模板文件（自动加载到每个工作区）
    ├── SOUL.md           # Agent 人格、身份、价值观
    ├── AGENTS.md         # Agent 集群规则、权限
    ├── USER.md           # 用户信息、偏好
    ├── TOOLS.md          # 工具定义与权限策略
    ├── IDENTITY.md       # 身份标识、运行时信息
    ├── HEARTBEAT.md      # 后台心跳/定时任务清单
    ├── BOOTSTRAP.md      # 启动引导 Prompt
    └── MEMORY.md         # 长期记忆存储
```

## 33.2 核心概念

**工作区（Workspace）** 是自包含的项目环境，包含：
- 工作目录（源代码、项目文件）
- Zeloo Profile（配置、记忆、技能）
- 元数据（描述、标签、创建/访问时间）

**档案（Archive）** 是工作区的冻结快照，可随时恢复。

目录布局：
```
~/.Zeloo/workspace/
├── workspace.json           # 所有工作区索引
├── default/                 # 默认工作区
│   ├── profile/             # Zeloo 配置（config.yaml、.env）
│   ├── memory/              # 持久记忆
│   ├── skills/              # 工作区本地技能
│   ├── SOUL.md              # Agent 人格（自动从模板生成）
│   ├── AGENTS.md            # 集群规则（自动从模板生成）
│   ├── USER.md              # 用户偏好（自动从模板生成）
│   ├── TOOLS.md             # 工具权限策略（自动从模板生成）
│   ├── IDENTITY.md          # 运行时身份（自动从模板生成）
│   ├── HEARTBEAT.md         # 后台任务清单（自动从模板生成）
│   ├── BOOTSTRAP.md         # 启动引导（自动从模板生成）
│   ├── MEMORY.md            # 长期记忆（自动从模板生成）
│   └── metadata.json        # 工作区元数据
├── project-alpha/           # 项目 A（同样包含全部 8 个 MD）
└── project-beta/            # 项目 B（同样包含全部 8 个 MD）
```

## 33.3 WorkspaceProfile 数据类

```python
from workspace.manager import WorkspaceProfile, WorkspaceManager

profile = WorkspaceProfile(
    name="project-alpha",
    path=Path("~/.Zeloo/workspace/project-alpha"),
    description="Alpha 项目工作区",
    memory_backend="localfile",
    tags=["python", "web"],
)
# profile.created_at     # 创建时间戳
# profile.last_active    # 最后活跃时间戳
# profile.to_dict()      # 序列化为字典
# WorkspaceProfile.from_dict(data)  # 从字典反序列化
```

## 33.4 WorkspaceManager — 工作区管理

```python
from workspace.manager import WorkspaceManager

manager = WorkspaceManager()

# 创建工作区
profile = manager.create_workspace(
    name="my-project",
    description="我的项目工作区",
    tags=["python"],
)

# 列出所有工作区
workspaces = manager.list_workspaces()

# 获取单个工作区
ws = manager.get_workspace("my-project")

# 切换工作区（更新 last_active）
manager.switch_workspace("my-project")

# 删除工作区（自动先快照）
manager.delete_workspace("my-project", confirm=True)

# 添加标签
manager.add_tag("my-project", "urgent")

# 按标签筛选
filtered = manager.list_workspaces(tag="urgent")
```

### 33.4.1 工作区 JSON 索引格式

```json
{
  "workspaces": {
    "default": {
      "name": "default",
      "path": "c:\\Users\\...\\.Zeloo\\workspace\\default",
      "description": "默认工作区",
      "created_at": 1725000000.0,
      "last_active": 1725000000.0,
      "memory_backend": "localfile",
      "tags": []
    }
  },
  "active": "default"
}
```

## 33.5 WorkspaceSnapshot — 快照管理

```python
from workspace.snapshot import WorkspaceSnapshot, ArchiveMetadata

snapshot = WorkspaceSnapshot(manager)

# 创建快照（.tar.gz 格式）
archive = snapshot.create_snapshot(
    workspace_name="my-project",
    reason="milestone-v1",
)
# archive = ArchiveMetadata(
#     workspace_name="my-project",
#     archive_name="snap_milestone-v1_20260908.tar.gz",
#     created_at=...,
#     reason="milestone-v1",
#     size_bytes=1234567,
# )

# 列出所有快照
archives = snapshot.list_archives(workspace_name="my-project")

# 恢复快照（--dry-run 支持）
snapshot.restore_snapshot(
    archive_name="snap_milestone-v1_20260908.tar.gz",
    new_name="my-project-restored",
    dry_run=False,
)

# 删除快照
snapshot.delete_archive(
    archive_name="snap_milestone-v1_20260908.tar.gz",
)

# 导出/导入快照（跨机器迁移）
snapshot.export_archive(
    archive_name="snap_milestone-v1_20260908.tar.gz",
    output_path=Path("/tmp/backup.tar.gz"),
)
snapshot.import_archive(
    archive_path=Path("/tmp/backup.tar.gz"),
    new_name="imported-project",
)
```

### 33.5.1 ArchiveMetadata 数据类

```python
from workspace.snapshot import ArchiveMetadata

# 序列化
data = archive.to_dict()
# {"workspace_name": "my-project", "archive_name": "snap_xxx.tar.gz",
#  "created_at": 1725000000.0, "reason": "milestone-v1",
#  "size_bytes": 1234567, "version": 1}

# 反序列化
archive = ArchiveMetadata.from_dict(data)
```

## 33.6 CLI 子命令集成

`workspace/` 模块通过 `zeloo_cli/subcommands/workspace.py` 提供 CLI 接口：

```bash
# 创建工作区
Zeloo workspace create my-project --description "项目描述" --tag python

# 列出工作区
Zeloo workspace list
Zeloo workspace list --format json
Zeloo workspace list --tag urgent

# 切换工作区
Zeloo workspace switch my-project

# 创建快照
Zeloo workspace archive my-project --reason "milestone-v1"

# 恢复快照
Zeloo workspace restore snap_milestone-v1_20260908.tar.gz --new-name restored

# 删除工作区（自动先快照）
Zeloo workspace delete my-project --confirm
```

## 33.7 迁移规则

- 不要在项目间共享 `memory/` 文件 — 每个工作区独立
- `profile/` 包含敏感配置 — 快照前确保 `.env` 不含明文密钥
- 恢复时总是创建新工作区 — 不覆盖现有同名工作区

## 33.8 WorkspaceBundle — 跨机器迁移

`workspace/importer.py` 提供可移植的 JSON Bundle 格式，用于在不同机器之间分享工作区配置：

```python
from workspace.importer import (
    WorkspaceBundle,
    export_workspace,
    import_workspace,
    list_bundle_files,
)

# 导出工作区为 Bundle（默认 .env 密钥被脱敏为 "<redacted>"）
bundle = export_workspace(
    manager=manager,
    workspace_name="my-project",
    output_path=Path("./my-project.bundle.json"),
)
# 包含 .env 时可设置 include_secrets=True（仅加密存储场景）

# 列出 Bundle 中的文件清单
files = list_bundle_files(bundle)

# 从 Bundle 导入工作区
profile = import_workspace(
    bundle_path=Path("./my-project.bundle.json"),
    new_name="my-project-clone",
)

# 自定义 Bundle 创建
bundle = WorkspaceBundle(
    name="my-project",
    description="我的项目",
    tags=["python", "web"],
    memory_backend="localfile",
    profile={...},        # config.yaml + .env（密钥脱敏）
    memory={...},         # MEMORY.md + USER.md 内容
    skills=[...],         # 技能索引（仅文件名，技能本身在其仓库）
    created_at=time.time(),
    version=1,
)
```

### 33.8.1 WorkspaceBundle 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | str | 工作区名称 |
| `description` | str | 工作区描述 |
| `tags` | list[str] | 标签列表 |
| `memory_backend` | str | 记忆后端（localfile/honcho/mem0 等） |
| `profile` | dict | config.yaml + .env（默认 .env 中密钥脱敏） |
| `memory` | dict | MEMORY.md / USER.md 内容 |
| `skills` | list[str] | 技能索引（仅文件名） |
| `created_at` | float | 创建时间戳 |
| `version` | int | Bundle 格式版本（当前为 1） |

### 33.8.2 安全说明

- 默认 `export_workspace(include_secrets=False)` — `.env` 中所有 KEY/TOKEN/SECRET 字段值被替换为 `"<redacted>"`
- 仅在加密存储场景设置 `include_secrets=True`
- Bundle 本身就是 JSON 文件，建议外层加密传输（GPG/age）

## 33.9 测试覆盖

| 测试文件 | 覆盖功能 | 用例数 |
|----------|----------|--------|
| `test_workspace_cli.py` | workspace 子命令全流程 | 12 |

详见 [08-project-structure.md](./08-project-structure.md) 中的工作区规范。
