---
name: file-todos
class: tool
description: >-
  基于文件的待办和任务跟踪。用于创建、整理、列出或管理待办文件、跟踪工作项、管理积压。
platforms: [cli, tui, api]
toolsets: [terminal, file]
---

# 文件待办跟踪

## 文件命名约定

```
{issue_id}-{status}-{priority}-{description}.md
```

- **issue_id**: 序号（001, 002, 003...）— 永不重用
- **status**: `pending`（需整理）、`ready`（已批准）、`complete`（完成）
- **priority**: `p1`（关键）、`p2`（重要）、`p3`（可选）
- **description**: 短横线命名，简短描述

示例: `001-pending-p1-mailer-test.md`, `002-ready-p1-fix-n-plus-1.md`

## 文件结构

YAML frontmatter:
```yaml
---
status: ready              # pending | ready | complete
priority: p1               # p1 | p2 | p3
issue_id: "002"
tags: [typescript, performance, database]
dependencies: ["001"]      # 阻塞的Issue ID
---
```

**必需部分：** 问题陈述、发现、建议方案、推荐操作、验收标准、工作日志

**可选部分：** 技术细节、资源、备注

## 关键区别

| 系统 | 用途 |
|------|------|
| **文件待办系统（本技能）** | `todos/`目录中的Markdown文件，用于开发/项目跟踪 |
| **应用待办模型** | 用户界面的数据库模型 |
| **TodoWrite工具** | agent会话中的内存任务跟踪，非持久化 |

## 验证

在认为待办文件正确编写前，确认：
- `issue_id`唯一且是`todos/`中的下一个序号
- 所有必需frontmatter字段存在
- `status`和`priority`值与文件名及其枚举匹配

## 工作流程

### 创建待办
1. 确定下一个可用issue_id
2. 创建 `{issue_id}-{status}-{priority}-{description}.md`
3. 填充模板内容

### 整理待办
- `pending` → `ready`: 批准开始工作
- `ready` → `complete`: 完成工作并记录

### 跟踪依赖
- 检查`dependencies`字段
- 确保依赖的待办完成后再开始

### 完成任务
1. 验证所有验收标准满足
2. 添加工作日志记录
3. 将status改为`complete`
4. 检查是否有待办依赖它

## 参考命令

```bash
# 列出所有待办
ls todos/

# 查找待处理待办
ls todos/*-pending-*.md

# 查找特定优先级的待办
ls todos/*-p1-*.md

# 搜索待办
rg "status: pending" todos/
```
