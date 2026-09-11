# Zeloo Agent 工作区约定

本文件定义了 Agent 在本项目中的行为约定，会被自动注入 system prompt 的 context 层。

## 项目概况

Zeloo 是一个自托管、自进化的常驻型 AI Agent 运行时框架。

## 开发规范

- 遵循 PEP 8 代码风格
- 类型注解必须完整
- 公共函数必须有 docstring
- 所有依赖精确版本锁定（==X.Y.Z）

## 架构约定

- System Prompt 分三层：stable / context / volatile
- 工具通过 @tool 装饰器自动注册
- 记忆与技能运行时可变，缓存层保持稳定
- 工作区（workspace/）与档案（archive/）隔离管理

## 工作区规范

### 工作区（Workspace）

每个工作区是独立的、自包含的项目环境：

```
~/.Zeloo/workspace/
├── workspace.json       # 所有工作区索引
├── default/            # 默认工作区
│   ├── profile/        # Zeloo 配置（config.yaml、.env）
│   ├── memory/         # 持久记忆（MEMORY.md、USER.md）
│   ├── skills/         # 工作区本地技能
│   ├── SOUL.md        # 可选的本地身份设定
│   └── metadata.json   # 工作区元数据
├── project-alpha/      # 项目 A
└── project-beta/       # 项目 B
```

### 档案（Archive）

工作区的压缩快照，可随时恢复：

```
~/.Zeloo/archive/
├── archive.json               # 所有档案索引
├── default/                  # 按工作区分目录
│   ├── snap_20260907.tar.zst
│   └── snap_milestone.tar.zst
└── project-alpha/
    └── snap_pre_delete.tar.zst
```

### 操作规范

1. **创建工作区**：`workspace_create` — 从已有工作区复制或全新创建
2. **切换工作区**：`workspace_switch` — 更新活跃时间戳
3. **快照工作区**：`workspace_archive` — 创建 .tar.zst 压缩快照
4. **恢复工作区**：`workspace_restore` — 从快照恢复为新工作区
5. **删除工作区** — 删除前自动先快照（除非显式禁用）

### 标签与搜索

- 工作区支持标签（`workspace_add_tag`）
- 支持按标签过滤工作区列表
- 按 `last_active` 时间排序

### 迁移规则

- 不要在项目间共享 `memory/` 文件 — 每个工作区独立
- `profile/` 包含敏感配置 — 快照前确保 `.env` 不含明文密钥
- 恢复时总是创建新工作区 — 不覆盖现有同名工作区
